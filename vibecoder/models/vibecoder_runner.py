# -*- coding: utf-8 -*-
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time

from odoo import api, models
from odoo.modules.registry import Registry

from ..lib.github_api import uncap_child_memory

_logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Vibecoder, a headless coding agent building a web application inside "
    "a git repository on behalf of a non-technical end user. "
    "Your working directory IS the project's git checkout — the user cannot see a "
    "file tree, only the running preview and your chat replies, so describe what "
    "you changed in plain language rather than dumping code. "
    "Use Read/Write/Edit/Glob/Grep to inspect and modify files, and Bash for "
    "installing packages, running scripts, and git. "
    "The project is a Vite + React app; a dev server is already running against "
    "this checkout and serves the latest files on disk automatically (no restart "
    "needed after an edit). "
    "IMPORTANT: at the end of every turn where you changed files, stage and commit "
    "your changes with `git add -A && git commit -m \"...\"` and `git push` so the "
    "user's GitHub repository stays in sync — never leave uncommitted work. "
    "Be concise in your replies; the user reads them as chat messages, not as a "
    "commit log."
)


class VibecoderRunner(models.AbstractModel):
    _name = "vibecoder.runner"
    _description = "Vibecoder Coding Agent CLI Runner"

    # ------------------------------------------------------------------
    # Launch (runs in the request env), background worker (own cursor)
    # ------------------------------------------------------------------
    def _launch(self, session, prompt, is_first):
        cli_path = session._resolve_cli_path()
        model = session._config("model", "claude-sonnet-4-5")
        max_turns = int(session._config("max_turns", 40))
        timeout_s = int(session._config("timeout_s", 900))
        oauth_env = session._oauth_env()
        cwd = session.project_id._get_local_path()

        if not is_first and not session._claude_session_exists(
                oauth_env.get("CLAUDE_CONFIG_DIR", "")):
            is_first = True

        ctx = {
            "dbname": self.env.cr.dbname,
            "session_id": session.id,
            "claude_session_id": session.claude_session_id,
            "prompt": prompt,
            "is_first": is_first,
            "cli_path": cli_path,
            "cwd": cwd,
            "model": model,
            "max_turns": max_turns,
            "timeout_s": timeout_s,
            "oauth_env": oauth_env,
        }
        thread = threading.Thread(
            target=self._run_worker, args=(ctx,), daemon=True,
            name="vibecoder_run_%s" % session.id)
        # Start only after the request transaction commits, so the worker's own
        # cursor sees the committed session state (state=running).
        self.env.cr.postcommit.add(thread.start)

    def _run_worker(self, ctx):
        registry = Registry(ctx["dbname"])
        with registry.cursor() as cr:
            env = api.Environment(cr, 1, {})
            session = env["vibecoder.session"].browse(ctx["session_id"])
            runner = env["vibecoder.runner"]
            try:
                runner._execute(env, session, ctx)
            except Exception as e:  # noqa: BLE001
                _logger.exception("Vibecoder run failed")
                session.write({"state": "error", "last_error": str(e)})
                session.event_seq += 1
                cr.commit()

    def _execute(self, env, session, ctx):
        argv = self._build_argv(ctx)
        run_env = self._build_env(ctx)

        _logger.info("Vibecoder: spawning %s (session %s, cwd %s)",
                     ctx["cli_path"], ctx["session_id"], ctx["cwd"])
        proc = subprocess.Popen(
            argv, cwd=ctx["cwd"], env=run_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
            preexec_fn=uncap_child_memory)

        session.write({"last_run_pid": proc.pid})
        session.event_seq += 1
        env.cr.commit()

        deadline = time.time() + ctx["timeout_s"]
        msg_map = {}
        line_q = queue.Queue()

        def _pump(pipe, q):
            try:
                for ln in pipe:
                    q.put(ln)
            finally:
                q.put(None)

        reader = threading.Thread(
            target=_pump, args=(proc.stdout, line_q), daemon=True,
            name="vibecoder_read_%s" % ctx["session_id"])
        reader.start()
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    proc.kill()
                    raise TimeoutError("Run exceeded timeout")
                try:
                    line = line_q.get(timeout=min(remaining, 5))
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    continue
                if line is None:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except ValueError:
                    continue
                self._handle_event(env, session, evt, msg_map)
                env.cr.commit()
            try:
                rc = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
        finally:
            pass

        stderr = proc.stderr.read() if proc.stderr else ""
        session.write({
            "last_run_pid": False,
            "turn_count": session.turn_count + 1,
        })
        if session.state == "running":
            if rc != 0:
                session.write({"state": "error", "last_error": stderr[:2000]})
            else:
                session.write({"state": "done"})
        session.event_seq += 1
        env.cr.commit()

        # "Hot reload": the dev server already serves rebuilt files on disk; we
        # only need to respawn it if it died mid-run.
        try:
            session.project_id.ensure_preview_running()
        except Exception:  # noqa: BLE001
            _logger.exception("Vibecoder: could not ensure preview running")
        env.cr.commit()

    # ------------------------------------------------------------------
    # Event handling: stream-json -> DB (polled by SSE controller)
    # ------------------------------------------------------------------
    def _handle_event(self, env, session, evt, msg_map):
        etype = evt.get("type")
        if etype == "system" and evt.get("subtype") == "init":
            sid = evt.get("session_id")
            if sid and session.claude_session_id != sid:
                session.claude_session_id = sid
            return

        if etype == "assistant":
            self._upsert_assistant(env, session, evt, msg_map)
            return

        if etype == "user":
            self._patch_tool_results(env, session, evt, msg_map)
            return

        if etype == "result":
            text = evt.get("result") or ""
            if not text and evt.get("errors"):
                text = "; ".join(str(e) for e in evt["errors"])
            if evt.get("is_error"):
                session.write({"state": "error", "last_error": text[:2000]})
            else:
                session.write({"state": "done"})
            session.event_seq += 1
            return

    def _upsert_assistant(self, env, session, evt, msg_map):
        message = evt.get("message") or {}
        cid = message.get("id")
        content = message.get("content") or []
        text_parts = []
        tool_calls = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text") or "")
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "name": block.get("name") or "",
                    "input": block.get("input") or {},
                    "result": None,
                    "status": "running",
                })
        body = "\n".join(p for p in text_parts if p)

        Msg = env["vibecoder.message"]
        rec_id = msg_map.get(cid)
        if rec_id:
            rec = Msg.browse(rec_id)
            vals = {}
            if body:
                vals["body"] = (rec.body or "") + body
            if tool_calls:
                existing = rec.tool_calls or []
                by_id = {t["id"]: t for t in existing}
                for t in tool_calls:
                    by_id.setdefault(t["id"], t)
                vals["tool_calls"] = list(by_id.values())
            if vals:
                rec.write(vals)
        else:
            rec = Msg.create({
                "session_id": session.id,
                "role": "assistant",
                "claude_msg_id": cid,
                "body": body,
                "tool_calls": tool_calls or False,
                "seq": session.event_seq + 1,
            })
            if cid:
                msg_map[cid] = rec.id
        session.event_seq += 1

    def _patch_tool_results(self, env, session, evt, msg_map):
        message = evt.get("message") or {}
        content = message.get("content") or []
        results = {}
        for block in content:
            if block.get("type") == "tool_result":
                tid = block.get("tool_use_id")
                rc = block.get("content")
                if isinstance(rc, list):
                    rc = "\n".join(b.get("text", "") for b in rc if isinstance(b, dict))
                results[tid] = {"text": rc, "is_error": bool(block.get("is_error"))}
        if not results:
            return
        Msg = env["vibecoder.message"]
        changed_any = False
        for rec_id in msg_map.values():
            rec = Msg.browse(rec_id)
            calls = rec.tool_calls or []
            changed = False
            for call in calls:
                if call.get("id") in results:
                    r = results[call["id"]]
                    call["result"] = (r["text"] or "")[:4000]
                    call["status"] = "error" if r["is_error"] else "done"
                    changed = True
            if changed:
                rec.tool_calls = calls
                changed_any = True
        if changed_any:
            session.event_seq += 1

    # ------------------------------------------------------------------
    # Command / env construction
    # ------------------------------------------------------------------
    def _build_argv(self, ctx):
        allowed = "Bash,Read,Write,Edit,Glob,Grep"
        argv = [
            ctx["cli_path"], "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--model", ctx["model"],
            "--max-turns", str(ctx["max_turns"]),
            "--permission-mode", "acceptEdits",
            "--allowedTools", allowed,
            "--append-system-prompt", SYSTEM_PROMPT,
        ]
        if ctx["is_first"]:
            argv += ["--session-id", ctx["claude_session_id"]]
        else:
            argv += ["--resume", ctx["claude_session_id"]]
        argv.append(ctx["prompt"])
        return argv

    def _build_env(self, ctx):
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        env.update(ctx["oauth_env"])
        return env
