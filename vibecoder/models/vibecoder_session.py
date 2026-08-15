# -*- coding: utf-8 -*-
import glob
import logging
import os
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_CLI_GLOB = "/opt/odoo/.local/bin/claude"


class VibecoderSession(models.Model):
    _name = "vibecoder.session"
    _description = "Vibecoder Chat Session"
    _order = "write_date desc, id desc"

    name = fields.Char(default=lambda self: _("New conversation"), required=True)
    project_id = fields.Many2one(
        "vibecoder.project", required=True, ondelete="cascade", index=True)
    claude_session_id = fields.Char(copy=False, index=True)
    state = fields.Selection(
        [("idle", "Idle"), ("running", "Running"),
         ("done", "Done"), ("error", "Error")],
        default="idle", required=True, copy=False)
    turn_count = fields.Integer(default=0, copy=False)
    last_run_pid = fields.Integer(copy=False)
    last_error = fields.Text(copy=False)
    event_seq = fields.Integer(default=0, copy=False,
                                help="Bumped on every message/state change; polled by the SSE stream.")

    message_ids = fields.One2many("vibecoder.message", "session_id")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("claude_session_id", str(uuid.uuid4()))
        return super().create(vals_list)

    @api.model
    def _config(self, key, default=None):
        val = self.env["ir.config_parameter"].sudo().get_param("vibecoder.%s" % key)
        return val if val not in (None, False, "") else default

    @api.model
    def _cron_reap_stale(self):
        timeout = int(self._config("timeout_s", 900))
        cutoff = fields.Datetime.now() - __import__("datetime").timedelta(
            seconds=timeout + 120)
        stale = self.search([("state", "=", "running"), ("write_date", "<", cutoff)])
        for session in stale:
            if session.last_run_pid:
                try:
                    os.kill(session.last_run_pid, 9)
                except (ProcessLookupError, PermissionError):
                    pass
            session.write({
                "state": "error", "last_run_pid": False,
                "last_error": "Reaped by cron (stale run).",
            })
            session.event_seq += 1
        return True

    def action_stop(self):
        self.ensure_one()
        if self.last_run_pid:
            try:
                os.kill(self.last_run_pid, 15)
            except (ProcessLookupError, PermissionError):
                pass
        self.write({"state": "idle", "last_run_pid": False})
        self.event_seq += 1
        return True

    def _claude_session_exists(self, config_dir):
        self.ensure_one()
        if not self.claude_session_id:
            return False
        pattern = os.path.join(
            config_dir, "projects", "*", self.claude_session_id + ".jsonl")
        return bool(glob.glob(pattern))

    @api.model
    def _resolve_cli_path(self):
        explicit = self._config("cli_path", DEFAULT_CLI_GLOB)
        if explicit and os.path.exists(explicit):
            return explicit
        matches = glob.glob(self._config("cli_glob", DEFAULT_CLI_GLOB))
        if not matches:
            raise UserError(_(
                "Claude CLI binary not found. Set the System Parameter "
                "'vibecoder.cli_path'."))
        return matches[0]

    def _oauth_env(self):
        self.ensure_one()
        partner = self.project_id.partner_id.sudo()
        config_dir = partner._vibecoder_ai_config_dir(create=True)
        return {
            "HOME": partner._vibecoder_ai_home_dir(),
            "CLAUDE_CONFIG_DIR": config_dir,
        }

    # ------------------------------------------------------------------
    # Public entry point (called from the controller)
    # ------------------------------------------------------------------
    def send_message(self, body):
        self.ensure_one()
        body = (body or "").strip()
        if not body:
            raise UserError(_("Empty message."))
        if self.state == "running":
            raise UserError(_("The assistant is still working on the previous message."))

        max_runs = int(self._config("max_concurrent_claude_runs", 2) or 0)
        if max_runs > 0:
            active = self.search_count([("state", "=", "running")])
            if active >= max_runs:
                raise UserError(_(
                    "Vibecoder is busy right now (%(active)s of %(max)s runs in "
                    "progress). Please wait a moment and send your message again.",
                    active=active, max=max_runs))

        partner = self.project_id.partner_id.sudo()
        if not partner._vibecoder_ai_is_authenticated():
            raise UserError(_(
                "Connect your Claude account before chatting."))
        if self.project_id.state != "ready":
            raise UserError(_("The project isn't ready yet."))

        seq = self.event_seq + 1
        user_msg = self.env["vibecoder.message"].create({
            "session_id": self.id, "role": "user", "body": body, "seq": seq,
        })
        if self.turn_count == 0 and self.name == _("New conversation"):
            self.name = (body[:60] + ("…" if len(body) > 60 else "")) or self.name

        is_first = self.turn_count == 0
        self.write({"state": "running", "event_seq": seq})
        self.env["vibecoder.runner"]._launch(self, body, is_first)
        return {"message_id": user_msg.id, "session_id": self.id}
