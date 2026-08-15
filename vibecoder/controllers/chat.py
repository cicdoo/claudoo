# -*- coding: utf-8 -*-
import json
import time

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request, Response
from odoo.modules.registry import Registry

from ._helpers import current_vibecoder_partner

POLL_INTERVAL = 0.3
STREAM_MAX_SECONDS = 55
KEEPALIVE_SECONDS = 15


class VibecoderChat(http.Controller):

    def _own_session(self, session_id):
        partner = current_vibecoder_partner()
        if not partner:
            raise UserError("Please log in first.")
        session = request.env["vibecoder.session"].sudo().browse(int(session_id))
        if not session.exists() or session.project_id.partner_id.id != partner.id:
            raise UserError("Session not found.")
        return session

    @http.route("/vibecoder/projects/<int:project_id>/sessions", type="jsonrpc", auth="public", csrf=False)
    def list_sessions(self, project_id):
        partner = current_vibecoder_partner()
        if not partner:
            raise UserError("Please log in first.")
        project = request.env["vibecoder.project"].sudo().browse(project_id)
        if not project.exists() or project.partner_id.id != partner.id:
            raise UserError("Project not found.")
        sessions = request.env["vibecoder.session"].sudo().search(
            [("project_id", "=", project.id)], limit=50)
        return {"sessions": [{"id": s.id, "name": s.name, "state": s.state} for s in sessions]}

    @http.route("/vibecoder/projects/<int:project_id>/sessions/new", type="jsonrpc", auth="public", csrf=False)
    def new_session(self, project_id):
        partner = current_vibecoder_partner()
        if not partner:
            raise UserError("Please log in first.")
        project = request.env["vibecoder.project"].sudo().browse(project_id)
        if not project.exists() or project.partner_id.id != partner.id:
            raise UserError("Project not found.")
        session = request.env["vibecoder.session"].sudo().create({"project_id": project.id})
        return {"id": session.id, "name": session.name, "state": session.state}

    @http.route("/vibecoder/session/<int:session_id>/messages", type="jsonrpc", auth="public", csrf=False)
    def messages(self, session_id):
        session = self._own_session(session_id)
        return {
            "id": session.id, "state": session.state, "event_seq": session.event_seq,
            "messages": session.message_ids._to_frontend(),
        }

    @http.route("/vibecoder/session/<int:session_id>/send", type="jsonrpc", auth="public", csrf=False)
    def send(self, session_id, body=None):
        session = self._own_session(session_id)
        return session.send_message(body)

    @http.route("/vibecoder/session/<int:session_id>/stop", type="jsonrpc", auth="public", csrf=False)
    def stop(self, session_id):
        session = self._own_session(session_id)
        session.action_stop()
        return {"state": session.state}

    @http.route("/vibecoder/session/<int:session_id>/stream", type="http", auth="public", csrf=False)
    def stream(self, session_id, after_seq=0):
        # Ownership check happens here, in the original request env, BEFORE we
        # hand off to a generator that opens its own short-lived cursors.
        session = self._own_session(session_id)
        dbname = request.env.cr.dbname
        sid = session.id
        try:
            after_seq = int(after_seq)
        except (TypeError, ValueError):
            after_seq = 0

        def generate():
            last_seq = after_seq
            last_keepalive = time.time()
            deadline = time.time() + STREAM_MAX_SECONDS
            registry = Registry(dbname)
            while time.time() < deadline:
                with registry.cursor() as cr:
                    cr.execute(
                        "SELECT state, event_seq FROM vibecoder_session WHERE id = %s", (sid,))
                    row = cr.fetchone()
                    if not row:
                        return
                    state, event_seq = row
                    new_msgs = []
                    if event_seq != last_seq:
                        cr.execute(
                            "SELECT id FROM vibecoder_message WHERE session_id = %s "
                            "AND seq > %s ORDER BY seq ASC", (sid, last_seq))
                        ids = [r[0] for r in cr.fetchall()]
                        if ids:
                            env = _env(cr)
                            new_msgs = env["vibecoder.message"].browse(ids)._to_frontend()
                        last_seq = event_seq
                for m in new_msgs:
                    yield ("event: message\ndata: %s\n\n" % json.dumps(m)).encode()
                if state in ("done", "error") and not new_msgs:
                    yield ("event: done\ndata: %s\n\n" % json.dumps({"state": state})).encode()
                    return
                now = time.time()
                if now - last_keepalive > KEEPALIVE_SECONDS:
                    yield b": keep-alive\n\n"
                    last_keepalive = now
                time.sleep(POLL_INTERVAL)
            yield b"event: timeout\ndata: {}\n\n"

        headers = [
            ("Content-Type", "text/event-stream"),
            ("Cache-Control", "no-cache"),
            ("X-Accel-Buffering", "no"),
        ]
        return Response(generate(), headers=headers, direct_passthrough=True)


def _env(cr):
    from odoo import api
    return api.Environment(cr, 1, {})
