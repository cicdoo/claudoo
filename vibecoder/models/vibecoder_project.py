# -*- coding: utf-8 -*-
import logging
import os
import random
import shutil
import signal
import socket
import subprocess
import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..lib.github_api import GITHUB_API_BASE, gh_json, uncap_child_memory

_logger = logging.getLogger(__name__)

SCAFFOLD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "static", "scaffold", "vite-react-starter")

GIT_RETRY_ATTEMPTS = 3
IDLE_PREVIEW_MINUTES = 30


class VibecoderProject(models.Model):
    _name = "vibecoder.project"
    _description = "Vibecoder Project"
    _order = "write_date desc, id desc"

    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="cascade", index=True)
    name = fields.Char(required=True)
    github_repo_full_name = fields.Char()
    github_default_branch = fields.Char(default="main")
    local_path = fields.Char(copy=False)
    preview_port = fields.Integer(copy=False)
    preview_pid = fields.Integer(copy=False)
    preview_last_active = fields.Datetime(copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("creating", "Creating"),
         ("ready", "Ready"), ("error", "Error")],
        default="draft", required=True, copy=False)
    last_error = fields.Text(copy=False)

    session_ids = fields.One2many("vibecoder.session", "project_id", string="Chat Sessions")

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------
    @api.model
    def _config(self, key, default=None):
        val = self.env["ir.config_parameter"].sudo().get_param("vibecoder.%s" % key)
        return val if val not in (None, False, "") else default

    @api.model
    def _workspace_root(self):
        return self._config("workspace_root", "/var/lib/odoo/vibecoder_workspaces")

    def _get_local_path(self):
        self.ensure_one()
        path = os.path.join(self._workspace_root(), str(self.id))
        if self.local_path != path:
            self.local_path = path
        return path

    # ------------------------------------------------------------------
    # Project creation: GitHub repo + scaffold + initial commit/push
    # ------------------------------------------------------------------
    def action_create_project(self):
        """Create the GitHub repo, seed it with the starter scaffold, and push
        the initial commit. All filesystem/git/network steps are wrapped so a
        failure leaves a clear UserError and state='error', never a bare 500."""
        self.ensure_one()
        if self.state in ("creating", "ready"):
            return True
        account = self.env["vibecoder.github_account"].sudo().search(
            [("partner_id", "=", self.partner_id.id)], limit=1)
        if not account:
            raise UserError(_("Connect your GitHub account before creating a project."))

        self.write({"state": "creating", "last_error": False})
        try:
            token = account.get_token()
            repo = gh_json(
                "POST", "%s/user/repos" % GITHUB_API_BASE, token=token,
                json={
                    "name": self._suggest_repo_name(),
                    "private": True,
                    "auto_init": False,
                    "description": "Created with Vibecoder",
                })
            full_name = repo.get("full_name")
            default_branch = repo.get("default_branch") or "main"
            clone_url = repo.get("clone_url")
            if not (full_name and clone_url):
                raise UserError(_("GitHub did not return a repository URL."))

            path = self._get_local_path()
            self._provision_local_repo(path, clone_url, default_branch, token)

            self.write({
                "github_repo_full_name": full_name,
                "github_default_branch": default_branch,
                "state": "ready",
            })
        except UserError as e:
            self.write({"state": "error", "last_error": str(e)})
            raise
        except Exception as e:  # noqa: BLE001
            _logger.exception("Vibecoder project creation failed (project %s)", self.id)
            self.write({"state": "error", "last_error": str(e)})
            raise UserError(_("Could not create the project: %s") % e)
        return True

    def _suggest_repo_name(self):
        base = "".join(c if c.isalnum() or c in "-_" else "-" for c in (self.name or "app"))
        base = base.strip("-") or "vibecoder-app"
        return "%s-%s" % (base[:80], self.id or int(time.time()))

    def _provision_local_repo(self, path, clone_url, default_branch, token):
        if os.path.isdir(SCAFFOLD_DIR):
            os.makedirs(path, exist_ok=True)
            for entry in os.listdir(SCAFFOLD_DIR):
                src = os.path.join(SCAFFOLD_DIR, entry)
                dst = os.path.join(path, entry)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
        else:
            os.makedirs(path, exist_ok=True)

        auth_url = clone_url.replace(
            "https://", "https://x-access-token:%s@" % token, 1)

        self._git(path, ["init", "-q", "-b", default_branch])
        self._git(path, ["config", "user.email", "vibecoder@localhost"])
        self._git(path, ["config", "user.name", "Vibecoder"])
        self._git(path, ["add", "-A"])
        self._git(path, ["commit", "-q", "-m", "Initial commit (Vibecoder starter template)"])
        self._git(path, ["remote", "add", "origin", auth_url])
        self._git_with_retry(path, ["push", "-u", "origin", default_branch])

    def _git(self, cwd, args):
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise UserError(_(
                "git %(cmd)s failed: %(err)s") % {
                    "cmd": " ".join(args), "err": (proc.stderr or proc.stdout)[:500]})
        return proc

    def _git_with_retry(self, cwd, args):
        """Retry network-facing git commands (push/fetch/clone) with back-off."""
        last_exc = None
        for attempt in range(1, GIT_RETRY_ATTEMPTS + 1):
            try:
                return self._git(cwd, args)
            except UserError as e:
                last_exc = e
                if attempt < GIT_RETRY_ATTEMPTS:
                    delay = min(2 ** attempt + random.uniform(0, 1), 15)
                    _logger.warning(
                        "git %s failed (attempt %s/%s), retrying in %.1fs: %s",
                        " ".join(args), attempt, GIT_RETRY_ATTEMPTS, delay, e)
                    time.sleep(delay)
        raise last_exc

    # ------------------------------------------------------------------
    # Preview process (npm run dev) lifecycle
    # ------------------------------------------------------------------
    def _port_range(self):
        raw = self._config("preview_port_range", "17000-17199")
        lo, _sep, hi = raw.partition("-")
        try:
            return int(lo), int(hi)
        except ValueError:
            return 17000, 17199

    def _port_in_use(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _allocate_port(self):
        lo, hi = self._port_range()
        taken = set(self.sudo().search(
            [("preview_port", "!=", False)]).mapped("preview_port"))
        for port in range(lo, hi + 1):
            if port in taken:
                continue
            if self._port_in_use(port):
                continue
            return port
        raise UserError(_("No free preview port available in range %s-%s.") % (lo, hi))

    def action_start_preview(self):
        self.ensure_one()
        if self.state != "ready":
            raise UserError(_("Create the project before starting a preview."))
        if self.preview_pid and self._pid_alive(self.preview_pid):
            self.preview_last_active = fields.Datetime.now()
            return True

        max_previews = int(self._config("max_concurrent_previews", 4) or 4)
        active = self.sudo().search_count(
            [("preview_pid", "!=", False), ("id", "!=", self.id)])
        if active >= max_previews:
            raise UserError(_(
                "The maximum number of concurrent previews (%s) is running. "
                "Stop another project's preview first.") % max_previews)

        path = self._get_local_path()
        if not os.path.isdir(path):
            raise UserError(_("Project workspace is missing on disk."))

        if not os.path.isdir(os.path.join(path, "node_modules")):
            self._npm_install(path)

        port = self.preview_port or self._allocate_port()
        base = "/vibecoder/preview/%s/" % self.id
        env = dict(os.environ)
        env["CI"] = "true"
        proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port),
             "--host", "127.0.0.1", "--base", base, "--strictPort"],
            cwd=path, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
            preexec_fn=uncap_child_memory)
        self.write({
            "preview_port": port,
            "preview_pid": proc.pid,
            "preview_last_active": fields.Datetime.now(),
        })
        return True

    def _npm_install(self, path):
        last_exc = None
        for attempt in range(1, GIT_RETRY_ATTEMPTS + 1):
            try:
                proc = subprocess.run(
                    ["npm", "install", "--no-audit", "--no-fund"],
                    cwd=path, capture_output=True, text=True, timeout=300,
                    preexec_fn=uncap_child_memory)
                if proc.returncode != 0:
                    raise UserError(_(
                        "npm install failed: %s") % (proc.stderr or proc.stdout)[-800:])
                return
            except (UserError, subprocess.TimeoutExpired) as e:
                last_exc = e if isinstance(e, UserError) else UserError(
                    _("npm install timed out."))
                if attempt < GIT_RETRY_ATTEMPTS:
                    delay = min(2 ** attempt + random.uniform(0, 1), 15)
                    _logger.warning(
                        "npm install failed (attempt %s/%s), retrying in %.1fs",
                        attempt, GIT_RETRY_ATTEMPTS, delay)
                    time.sleep(delay)
        raise last_exc

    def action_stop_preview(self):
        self.ensure_one()
        if self.preview_pid:
            self._kill_pid(self.preview_pid)
        self.write({"preview_pid": False, "preview_port": False})
        return True

    def ensure_preview_running(self):
        """Called after a Claude turn finishes. Vite's own file watcher already
        serves rebuilt code on the next request — no hard restart is needed for
        'hot reload'; we only need to respawn the dev server if it died."""
        self.ensure_one()
        if self.state != "ready":
            return
        if self.preview_pid and not self._pid_alive(self.preview_pid):
            self.write({"preview_pid": False})
            self.action_start_preview()

    @staticmethod
    def _pid_alive(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _kill_pid(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def touch_preview_activity(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if not self.preview_last_active or (
                now - self.preview_last_active).total_seconds() > 30:
            self.preview_last_active = now

    @api.model
    def _cron_reap_idle_previews(self):
        cutoff = fields.Datetime.now() - __import__("datetime").timedelta(
            minutes=IDLE_PREVIEW_MINUTES)
        idle = self.sudo().search([
            ("preview_pid", "!=", False),
            "|", ("preview_last_active", "<", cutoff),
            ("preview_last_active", "=", False),
        ])
        for project in idle:
            _logger.info("Vibecoder: reaping idle preview for project %s", project.id)
            project.action_stop_preview()
        self._gc_stale_uploads()
        return True

    def _gc_stale_uploads(self, max_age_hours=24):
        """Remove abandoned chunked-upload temp dirs (init'd but never
        completed) older than max_age_hours, across every project workspace."""
        cutoff = time.time() - max_age_hours * 3600
        for project in self.sudo().search([("local_path", "!=", False)]):
            uploads_root = os.path.join(project.local_path, ".uploads")
            if not os.path.isdir(uploads_root):
                continue
            for entry in os.listdir(uploads_root):
                upload_dir = os.path.join(uploads_root, entry)
                meta_path = os.path.join(upload_dir, "meta.json")
                try:
                    mtime = os.path.getmtime(meta_path)
                except OSError:
                    continue
                if mtime < cutoff:
                    shutil.rmtree(upload_dir, ignore_errors=True)
