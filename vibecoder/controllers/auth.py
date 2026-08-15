# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ._helpers import current_vibecoder_partner, login_partner, logout_partner, client_ip


class VibecoderAuth(http.Controller):

    @http.route("/vibecoder/auth/signup", type="jsonrpc", auth="public", csrf=False)
    def signup(self, login=None, password=None, name=None, **kw):
        partner = request.env["res.partner"].sudo()._vibecoder_signup(login, password, name)
        login_partner(partner)
        return {"partner": _partner_dict(partner)}

    @http.route("/vibecoder/auth/login", type="jsonrpc", auth="public", csrf=False)
    def login(self, login=None, password=None, **kw):
        Attempt = request.env["vibecoder.login_attempt"].sudo()
        ip = client_ip()
        wait = Attempt.check_and_touch(login, ip)
        if wait > 0:
            raise UserError(
                "Too many attempts. Please wait %s seconds and try again." % int(wait) + 1)
        partner = request.env["res.partner"].sudo()._vibecoder_check_credentials(login, password)
        if not partner:
            Attempt.register_failure(login, ip)
            raise UserError("Invalid email or password.")
        Attempt.register_success(login, ip)
        login_partner(partner)
        return {"partner": _partner_dict(partner)}

    @http.route("/vibecoder/auth/logout", type="jsonrpc", auth="public", csrf=False)
    def logout(self):
        logout_partner()
        return {"ok": True}

    @http.route("/vibecoder/auth/me", type="jsonrpc", auth="public", csrf=False)
    def me(self):
        partner = current_vibecoder_partner()
        if not partner:
            return {"partner": None}
        return {"partner": _partner_dict(partner)}


def _partner_dict(partner):
    account = request.env["vibecoder.github_account"].sudo().search(
        [("partner_id", "=", partner.id)], limit=1)
    return {
        "id": partner.id,
        "name": partner.name,
        "login": partner.vibecoder_login,
        "claude_connected": partner._vibecoder_ai_is_authenticated(),
        "github_connected": bool(account),
        "github_login": account.github_login if account else None,
    }
