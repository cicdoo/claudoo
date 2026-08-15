# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ._helpers import current_vibecoder_partner


class VibecoderClaudeOauth(http.Controller):

    def _require_partner(self):
        partner = current_vibecoder_partner()
        if not partner:
            raise UserError("Please log in first.")
        return partner

    @http.route("/vibecoder/claude/status", type="jsonrpc", auth="public", csrf=False)
    def status(self):
        partner = self._require_partner()
        return {"authenticated": partner._vibecoder_ai_is_authenticated()}

    @http.route("/vibecoder/claude/start", type="jsonrpc", auth="public", csrf=False)
    def start(self):
        partner = self._require_partner()
        return {"url": partner._vibecoder_ai_oauth_start()}

    @http.route("/vibecoder/claude/complete", type="jsonrpc", auth="public", csrf=False)
    def complete(self, code=None):
        partner = self._require_partner()
        partner._vibecoder_ai_oauth_complete(code)
        return {"authenticated": True}

    @http.route("/vibecoder/claude/logout", type="jsonrpc", auth="public", csrf=False)
    def logout(self):
        partner = self._require_partner()
        partner._vibecoder_ai_logout()
        return {"authenticated": False}
