# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import json

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request


class AiAssistantChat(http.Controller):

    def _session(self, session_id):
        """Fetch a session owned by the current user (record rule enforced)."""
        session = request.env["claudoo.session"].browse(int(session_id))
        if not session.exists() or session.user_id != request.env.user:
            raise UserError("Session not found.")
        return session

    # ------------------------------------------------------------------
    # Per-user Claude authentication (OAuth login gate)
    # ------------------------------------------------------------------
    @http.route("/claudoo/auth/status", type="json", auth="user")
    def auth_status(self):
        return {"authenticated": request.env.user._ai_is_authenticated()}

    @http.route("/claudoo/auth/start", type="json", auth="user")
    def auth_start(self):
        """Return the Claude authorization URL to open in the user's browser."""
        return {"url": request.env.user._ai_oauth_start()}

    @http.route("/claudoo/auth/complete", type="json", auth="user")
    def auth_complete(self, code=None):
        """Exchange the pasted authorization code and persist credentials."""
        request.env.user._ai_oauth_complete(code)
        return {"authenticated": True}

    @http.route("/claudoo/auth/logout", type="json", auth="user")
    def auth_logout(self):
        request.env.user._ai_logout()
        return {"authenticated": False}

    @http.route("/claudoo/sessions", type="json", auth="user")
    def sessions(self):
        recs = request.env["claudoo.session"].search(
            [("user_id", "=", request.env.uid)], limit=50)
        return [{"id": s.id, "name": s.name, "state": s.state} for s in recs]

    @http.route("/claudoo/new", type="json", auth="user")
    def new(self):
        session = request.env["claudoo.session"].create({
            "user_id": request.env.uid})
        return {"id": session.id, "name": session.name, "state": session.state}

    @http.route("/claudoo/messages", type="json", auth="user")
    def messages(self, session_id=None):
        session = self._session(session_id)
        return {
            "id": session.id,
            "name": session.name,
            "state": session.state,
            "messages": session.message_ids._to_frontend(),
        }

    @http.route("/claudoo/upload", type="http", auth="user", methods=["POST"])
    def upload(self, session_id=None, ufile=None, **kw):
        """Accept one or more uploaded files for a session (multipart form).

        Stores each as an ir.attachment linked to the session and returns their
        descriptors as JSON. type="http" (not json) so the browser can post the
        raw file via FormData."""
        headers = [("Content-Type", "application/json")]
        try:
            session = self._session(session_id)
            files = request.httprequest.files.getlist("ufile")
            if not files:
                raise UserError("No file received.")
            out = [session._store_upload(f.filename, f.read()) for f in files]
            return request.make_response(json.dumps({"attachments": out}), headers)
        except UserError as e:
            return request.make_response(
                json.dumps({"error": str(e)}), headers, status=400)

    @http.route("/claudoo/send", type="json", auth="user")
    def send(self, session_id=None, body=None, attachment_ids=None):
        session = self._session(session_id)
        return session.send_message(body, attachment_ids=attachment_ids)

    @http.route("/claudoo/stop", type="json", auth="user")
    def stop(self, session_id=None):
        session = self._session(session_id)
        session.action_stop()
        return {"state": session.state}
