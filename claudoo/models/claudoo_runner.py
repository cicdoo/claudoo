# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import json
import logging
import os
import queue
import shlex
import subprocess
import sys
import threading
import time

from odoo import api, models
from odoo.modules.registry import Registry

from .claudoo_session import (
    DISALLOWED_BUILTINS, UPLOADS_SUBDIR, WEB_TOOLS, WEB_TOOL_BUILTINS)

_logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an AI assistant embedded inside an Odoo 18 ERP system. "
    "You help the current Odoo user query data and build reports. "
    "You act through the provided `mcp__odoo__*` tools — you have no shell access. "
    "Web access (WebFetch/WebSearch) is available only when the tool grant in the "
    "ODOO USER CONTEXT block below lists it; otherwise assume you cannot reach the web. "
    "The only filesystem tool available is `Read`, and it is restricted to "
    "the files the user attached to this conversation (in your working directory); "
    "use it to open those attachments when the user refers to them, but do not "
    "attempt to read or write anything else. All actions run with the user's own Odoo permissions, "
    "so respect AccessError results and never try to work around them. "
    "Use `model_introspect` to discover models/fields before querying — consult its "
    "`effective_access` map to see which actions (read/write/create/unlink) are actually "
    "available to you here before attempting them. "
    "Use `orm_search_read`/`orm_read`/`orm_call` for normal data access (these honor "
    "record rules). Use `sql_select` only for read-only reporting when available. "
    "Write tools (`orm_create`/`orm_write`/`orm_unlink`) may be available; only some "
    "users are granted them. When you change data, confirm what you did concisely. "
    "Action tools may also be available (check `model_introspect`'s `ai_tools_allowed`): "
    "use `orm_action` to call business methods like `action_confirm`/`action_post`/"
    "`button_validate` on records (method names are allowlisted), `run_wizard` to create "
    "and run a wizard in one step, and `run_server_action` to run an admin-allowlisted "
    "server action. Prefer these over raw `orm_write` when an Odoo business action exists, "
    "so state machines and validations run correctly. "
    "Be concise. When you present data, format it as a clear Markdown table when useful. "
    "IDENTITY: You are acting on behalf of a specific Odoo user, whose identity, company, "
    "locale and roles are given in the 'ODOO USER CONTEXT' block below. You are THAT Odoo "
    "user's assistant — never identify yourself as a Claude/Anthropic subscription account, "
    "and address the user by their Odoo name. Any account email shown elsewhere in your "
    "environment (e.g. a 'userEmail' context line) is the underlying Claude subscription used "
    "to run you — it is NOT the user; the authoritative email and identity are the ones in the "
    "ODOO USER CONTEXT block. Assume ONLY the roles and privileges listed in "
    "that block; never assume administrator rights you have not been shown. Every tool runs "
    "with this user's own Odoo permissions, so an AccessError is authoritative: report it "
    "plainly and never try to work around it. "
    "CRITICAL: Only ever call tools through the real tool-calling mechanism. NEVER write "
    "tool calls, XML/function tags, or fabricated tool results as text in your reply, and "
    "NEVER invent data. If the mcp__odoo__* tools are not visible to you, reply exactly "
    "'AI tools are not available right now, please retry.' and nothing else — do not guess."
)


class AiAssistantRunner(models.AbstractModel):
    _name = "claudoo.runner"
    _description = "Claudoo AI Assistant CLI Runner"

    # ------------------------------------------------------------------
    # Launch (runs in the request env, as the user)
    # ------------------------------------------------------------------
    def _launch(self, session, prompt, is_first, token):
        """Resolve config in the request env, then spawn a background thread."""
        cli_path = session._resolve_cli_path()
        scratch = session._get_scratch_dir()
        model = session._config("model", "claude-sonnet-4-5")
        max_turns = int(session._config("max_turns", 30))
        timeout_s = int(session._config("timeout_s", 900))
        base_url = session._config("base_url", "http://127.0.0.1:8069")
        # Interpreter used to run the bundled bridge/read_guard scripts. Defaults
        # to the Python currently running Odoo; override via the `claudoo.python_bin`
        # system parameter if the bridge needs a different interpreter/venv.
        python_bin = session._config("python_bin", "") or sys.executable
        target_db = session._target_db()
        routing_sid = session._mint_routing_sid(target_db)
        bridge_script = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "bridge", "mcp_server.py")
        oauth_env = session._oauth_env()
        # Align the CLI's stored account identity (the '# userEmail' it injects)
        # with this Odoo user, so it stops reporting the personal Claude account.
        session.user_id._ai_sync_cli_account()
        # Effective tool set + model denylist for THIS user (computed once here,
        # in the request env, as the user). Consumed by --allowedTools and the
        # bridge env below; the controller re-derives them authoritatively.
        allowed_tools = sorted(session._effective_tools())
        # Granted built-in web tools (WebFetch/WebSearch). These are the CLI's own
        # built-ins, not mcp__odoo__* tools, so they bypass the bridge: they are
        # lifted from the deny list and added to --allowedTools by raw name below.
        web_builtins = [WEB_TOOL_BUILTINS[t] for t in allowed_tools if t in WEB_TOOLS]
        excluded_models = sorted(session._ai_excluded_models())
        # Per-user identity/role block appended to the system prompt so the model
        # acts AS this Odoo user (built here, in the request env, as the user).
        identity = session.user_id._ai_identity_prompt(set(allowed_tools))

        # Only resume when this conversation's transcript actually exists in the
        # user's current config dir; otherwise start a fresh CLI session (reusing
        # the stored UUID) so the turn doesn't fail with "No conversation found".
        if not is_first and not session._claude_session_exists(
                oauth_env.get("CLAUDE_CONFIG_DIR", "")):
            is_first = True

        ctx = {
            "dbname": self.env.cr.dbname,
            "uid": session.user_id.id,
            "session_id": session.id,
            "claude_session_id": session.claude_session_id,
            "prompt": prompt,
            "is_first": is_first,
            "cli_path": cli_path,
            "scratch": scratch,
            "model": model,
            "max_turns": max_turns,
            "timeout_s": timeout_s,
            "base_url": base_url,
            "python_bin": python_bin,
            "target_db": target_db,
            "routing_sid": routing_sid,
            "bridge_script": bridge_script,
            "token": token,
            "oauth_env": oauth_env,
            "allowed_tools": allowed_tools,
            "web_builtins": web_builtins,
            "excluded_models": excluded_models,
            "identity": identity,
        }
        thread = threading.Thread(
            target=self._run_worker, args=(ctx,), daemon=True,
            name="claudoo_run_%s" % session.id)
        # Start only AFTER the request transaction commits, so the worker's own
        # cursor sees the committed session state (state=running) and bridge token
        # (bridge_jti). Starting inline races the request transaction and causes
        # "could not serialize access due to concurrent update" / token rejection.
        self.env.cr.postcommit.add(thread.start)

    # ------------------------------------------------------------------
    # Background worker (own cursor)
    # ------------------------------------------------------------------
    def _run_worker(self, ctx):
        dbname = ctx["dbname"]
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, ctx["uid"], {})
            session = env["claudoo.session"].browse(ctx["session_id"])
            runner = env["claudoo.runner"]
            try:
                runner._execute(env, session, ctx)
            except Exception as e:
                _logger.exception("AI assistant run failed")
                session.write({"state": "error", "last_error": str(e)})
                runner._emit(session, {"kind": "error", "error": str(e)})
                cr.commit()

    def _execute(self, env, session, ctx):
        mcp_config_path = self._write_mcp_config(ctx)
        settings_path = self._write_settings(ctx)
        argv = self._build_argv(ctx, mcp_config_path, settings_path)
        run_env = self._build_env(ctx)

        _logger.info("AI assistant: spawning %s (session %s)",
                     ctx["cli_path"], ctx["session_id"])
        proc = subprocess.Popen(
            argv, cwd=ctx["scratch"], env=run_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, bufsize=1)

        session.write({"last_run_pid": proc.pid})
        self._emit(session, {"kind": "started"})
        env.cr.commit()

        deadline = time.time() + ctx["timeout_s"]
        # in-memory map: claude_msg_id -> claudoo.message record id
        msg_map = {}
        # Read stdout via a helper thread feeding a queue, so the deadline is
        # enforced even when the CLI goes SILENT (produces no output and does not
        # exit — e.g. a tool call stalls). Iterating proc.stdout directly would
        # block indefinitely there and never re-check the deadline, leaving the
        # UI "running" until the stale-session cron reaps it minutes later.
        line_q = queue.Queue()

        def _pump(pipe, q):
            try:
                for ln in pipe:
                    q.put(ln)
            finally:
                q.put(None)  # sentinel: stdout closed (process exiting)

        reader = threading.Thread(
            target=_pump, args=(proc.stdout, line_q), daemon=True,
            name="claudoo_read_%s" % ctx["session_id"])
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
                    # No output this tick. If the process has died without
                    # closing the pipe, stop waiting; otherwise loop and
                    # re-check the deadline.
                    if proc.poll() is not None:
                        break
                    continue
                if line is None:  # stdout closed -> process is exiting
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
            for p in (mcp_config_path, settings_path):
                try:
                    os.remove(p)
                except OSError:
                    pass
            env["claudoo.session"]._delete_routing_sid(ctx.get("routing_sid"))

        stderr = proc.stderr.read() if proc.stderr else ""
        session.write({
            "last_run_pid": False,
            "turn_count": session.turn_count + 1,
        })
        if session.state == "running":
            # No explicit result event; treat as done unless rc indicates failure.
            if rc != 0:
                session.write({"state": "error", "last_error": stderr[:2000]})
                self._emit(session, {"kind": "error",
                                     "error": stderr[:500] or "CLI exited %s" % rc})
            else:
                session.write({"state": "done"})
                self._emit(session, {"kind": "done"})
        env.cr.commit()

    # ------------------------------------------------------------------
    # Event handling: stream-json -> DB + bus
    # ------------------------------------------------------------------
    def _handle_event(self, env, session, evt, msg_map):
        etype = evt.get("type")
        if etype == "system" and evt.get("subtype") == "init":
            # Persist the actual session id the CLI is using (should match ours).
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
            is_error = evt.get("is_error")
            if is_error:
                session.write({"state": "error", "last_error": text[:2000]})
                self._emit(session, {"kind": "error", "error": text[:500]})
            else:
                session.write({"state": "done"})
                self._emit(session, {"kind": "done"})
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
                    "name": (block.get("name") or "").replace("mcp__odoo__", ""),
                    "input": block.get("input") or {},
                    "result": None,
                    "status": "running",
                })
        body = "\n".join(p for p in text_parts if p)

        Msg = env["claudoo.message"]
        rec_id = msg_map.get(cid)
        if rec_id:
            rec = Msg.browse(rec_id)
            vals = {}
            # Text arrives as separate per-block events for one message id, so
            # APPEND rather than replace to preserve earlier blocks.
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
            })
            if cid:
                msg_map[cid] = rec.id
        self._emit_message(session, rec)

    def _patch_tool_results(self, env, session, evt, msg_map):
        message = evt.get("message") or {}
        content = message.get("content") or []
        results = {}
        for block in content:
            if block.get("type") == "tool_result":
                tid = block.get("tool_use_id")
                rc = block.get("content")
                if isinstance(rc, list):
                    rc = "\n".join(
                        b.get("text", "") for b in rc if isinstance(b, dict))
                results[tid] = {
                    "text": rc,
                    "is_error": bool(block.get("is_error")),
                }
        if not results:
            return
        Msg = env["claudoo.message"]
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
                self._emit_message(session, rec)

    # ------------------------------------------------------------------
    # Bus
    # ------------------------------------------------------------------
    def _emit(self, session, payload):
        payload = dict(payload, session_id=session.id)
        session.user_id.partner_id._bus_send("claudoo", payload)

    def _emit_message(self, session, rec):
        self._emit(session, {
            "kind": "message",
            "message": rec._to_frontend()[0],
        })

    # ------------------------------------------------------------------
    # Command / env / mcp config construction
    # ------------------------------------------------------------------
    def _build_argv(self, ctx, mcp_config_path, settings_path):
        # ToolSearch must be allowed: the mcp__odoo__* tools are deferred and the
        # model loads them via ToolSearch. It only loads tool schemas, nothing else.
        # Web tools are CLI built-ins, so they go in by bare name (WebFetch/
        # WebSearch) — never with the mcp__odoo__ prefix the bridge tools carry.
        odoo_tools = [t for t in ctx["allowed_tools"] if t not in WEB_TOOLS]
        allowed = ",".join(
            ["mcp__odoo__%s" % t for t in odoo_tools]
            + ctx["web_builtins"] + ["ToolSearch"])
        # NB: we intentionally do NOT use --disallowedTools. In this CLI version
        # that flag prevents the stdio MCP server's tools from attaching at all
        # (the model then sees no mcp__odoo__* tools and hallucinates tool calls
        # as text). Built-ins are blocked via the settings file's permissions.deny
        # instead, which restricts them without breaking MCP.
        argv = [
            ctx["cli_path"], "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--model", ctx["model"],
            "--max-turns", str(ctx["max_turns"]),
            "--permission-mode", "default",
            "--strict-mcp-config",
            "--mcp-config", mcp_config_path,
            "--settings", settings_path,
            "--allowedTools", allowed,
            "--append-system-prompt", SYSTEM_PROMPT + "\n\n" + ctx["identity"],
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

    def _write_settings(self, ctx):
        """Write a settings.json that denies all built-in tools (so the model can
        only act through mcp__odoo__*), without using --disallowedTools.

        ToolSearch is intentionally NOT denied: in this CLI version the MCP
        (mcp__odoo__*) tools are *deferred* and the model can only load/see them by
        calling ToolSearch first. Denying ToolSearch makes the MCP tools invisible
        to the model, so it reports "no tools" and fabricates calls. ToolSearch only
        loads tool schemas (it executes nothing), so allowing it is safe.

        The MCP resource tools are also left out — our bridge exposes no resources.

        Read is the one filesystem tool we re-enable, so the model can open
        files the user attached — but it is sandboxed to the per-session uploads
        dir by TWO layers:

        1. A path-scoped allow rule auto-approves reads under uploads/.
        2. A PreToolUse hook (read_guard.py) hard-DENIES any Read whose path
           resolves outside uploads/. This is the authoritative boundary: in
           `default` mode the CLI auto-approves read-only tools, so the allow
           rule alone would not stop a read elsewhere — but a PreToolUse `deny`
           runs before permission evaluation and overrides that auto-approval.

        The scope deliberately excludes the scratch root, which holds mcp.json
        (the bridge token) and this settings file. Glob/Grep stay fully denied,
        so the hook only needs to guard Read."""
        keep_allowed = ("ListMcpResources", "ReadMcpResource", "ToolSearch", "Read")
        # Per-user web grant: lift WebFetch/WebSearch from the deny list so the CLI
        # may run them. Ungranted, they stay denied like the rest of the built-ins.
        keep = set(keep_allowed) | set(ctx["web_builtins"])
        deny = [t for t in DISALLOWED_BUILTINS if t not in keep]
        uploads_dir = os.path.join(ctx["scratch"].rstrip("/"), UPLOADS_SUBDIR)
        # Absolute-path allow rule uses the // prefix (uploads_dir already starts
        # with "/", so "/" + uploads_dir yields "//var/lib/...").
        uploads_glob = "Read(/%s/**)" % uploads_dir
        guard = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "bridge", "read_guard.py")
        guard_cmd = "%s %s %s" % (
            shlex.quote(ctx["python_bin"]),
            shlex.quote(guard),
            shlex.quote(uploads_dir))
        cfg = {
            "permissions": {"deny": deny, "allow": [uploads_glob]},
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Read",
                    "hooks": [{"type": "command", "command": guard_cmd}],
                }],
            },
        }
        path = os.path.join(ctx["scratch"], "settings.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f)
        return path

    def _write_mcp_config(self, ctx):
        cfg = {
            "mcpServers": {
                "odoo": {
                    "type": "stdio",
                    "command": ctx["python_bin"],
                    "args": [ctx["bridge_script"]],
                    "env": {
                        "AI_ODOO_BASE": ctx["base_url"],
                        "AI_ODOO_DB": ctx["target_db"],
                        "AI_ODOO_SID": ctx["routing_sid"],
                        "AI_BRIDGE_TOKEN": ctx["token"],
                        "AI_SESSION_ID": str(ctx["session_id"]),
                        # Advisory UX: which tool schemas the bridge advertises.
                        # The controller enforces the same set authoritatively.
                        # Built-in web tools are excluded: the bridge serves only
                        # mcp__odoo__* tools, never WebFetch/WebSearch.
                        "AI_ALLOWED_TOOLS": ",".join(
                            t for t in ctx["allowed_tools"] if t not in WEB_TOOLS),
                        "AI_EXCLUDED_MODELS": ",".join(ctx["excluded_models"]),
                    },
                }
            }
        }
        path = os.path.join(ctx["scratch"], "mcp.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f)
        return path
