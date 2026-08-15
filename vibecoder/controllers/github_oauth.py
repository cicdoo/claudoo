# -*- coding: utf-8 -*-
import logging
import secrets
from urllib.parse import urlencode

import requests

from odoo import http
from odoo.http import request

from ._helpers import current_vibecoder_partner
from ..lib.github_api import gh_json

_logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_STATE_SESSION_KEY = "vibecoder_github_oauth_state"


class VibecoderGithubOauth(http.Controller):

    def _config(self, key):
        return request.env["ir.config_parameter"].sudo().get_param("vibecoder.%s" % key)

    @http.route("/vibecoder/github/connect", type="http", auth="public", csrf=False)
    def connect(self, **kw):
        partner = current_vibecoder_partner()
        if not partner:
            return request.redirect("/vibecoder/login")
        client_id = self._config("github_client_id")
        if not client_id:
            return request.make_response(
                "GitHub connection is not configured yet. Ask an administrator to "
                "set the GitHub OAuth Client ID/Secret in Settings.", status=503)

        state = secrets.token_urlsafe(24)
        request.session[GITHUB_STATE_SESSION_KEY] = state
        base_url = request.httprequest.url_root.rstrip("/")
        params = {
            "client_id": client_id,
            "redirect_uri": "%s/vibecoder/github/callback" % base_url,
            "scope": "repo",
            "state": state,
        }
        return request.redirect("%s?%s" % (GITHUB_AUTHORIZE_URL, urlencode(params)), local=False)

    @http.route("/vibecoder/github/callback", type="http", auth="public", csrf=False)
    def callback(self, code=None, state=None, **kw):
        partner = current_vibecoder_partner()
        if not partner:
            return request.redirect("/vibecoder/login")

        expected_state = request.session.get(GITHUB_STATE_SESSION_KEY)
        request.session.pop(GITHUB_STATE_SESSION_KEY, None)
        if not code or not state or not expected_state or state != expected_state:
            return request.make_response(
                "GitHub authorization failed (state mismatch). Please try again.", status=400)

        client_id = self._config("github_client_id")
        client_secret = self._config("github_client_secret")
        base_url = request.httprequest.url_root.rstrip("/")
        try:
            resp = requests.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": "%s/vibecoder/github/callback" % base_url,
                },
                headers={"Accept": "application/json"}, timeout=30)
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            _logger.warning("GitHub token exchange failed: %s", e)
            return request.make_response("Could not reach GitHub. Please try again.", status=502)

        token = data.get("access_token")
        if not token:
            _logger.warning("GitHub token exchange returned no token: %s", data)
            return request.make_response(
                "GitHub did not return an access token: %s" % data.get(
                    "error_description", "unknown error"), status=400)

        profile = gh_json("GET", "https://api.github.com/user", token=token)

        Account = request.env["vibecoder.github_account"].sudo()
        account = Account.search([("partner_id", "=", partner.id)], limit=1)
        vals = {
            "partner_id": partner.id,
            "github_login": profile.get("login"),
            "github_user_id": profile.get("id"),
            "scopes": data.get("scope", ""),
        }
        if account:
            account.write(vals)
        else:
            account = Account.create(vals)
        account.set_token(token)

        return request.redirect("/vibecoder")
