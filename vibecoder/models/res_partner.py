# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import logging
import os
import secrets
import time

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.mail import email_normalize

_logger = logging.getLogger(__name__)

# --- Claude Code OAuth (subscription login) constants -----------------------
# Public Claude Code OAuth client parameters used by the `claude setup-token` /
# `/login` flow (cloned from claudoo's res_users.py). The server has no browser,
# so we use the manual "copy code" redirect: the visitor authorizes in their own
# browser and pastes the returned `code#state` string back into Vibecoder.
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
OAUTH_SCOPES = "org:create_api_key user:profile user:inference"

_PKCE_PARAM = "vibecoder.oauth_pkce.%s"

MIN_PASSWORD_LEN = 8


class ResPartner(models.Model):
    _inherit = "res.partner"

    vibecoder_login = fields.Char(
        string="Vibecoder Login", copy=False, index=True,
        help="Email used to sign in to the Vibecoder site.")
    vibecoder_password_hash = fields.Char(string="Vibecoder Password Hash", copy=False)
    vibecoder_active = fields.Boolean(string="Vibecoder Account Active", default=True)

    vibecoder_claude_oauth_set = fields.Boolean(
        compute="_compute_vibecoder_claude_oauth_set",
        string="Personal Claude Linked")

    _vibecoder_login_uniq = models.Constraint(
        "unique(vibecoder_login)",
        "A Vibecoder account with this login already exists.",
    )

    def _compute_vibecoder_claude_oauth_set(self):
        for partner in self:
            partner.vibecoder_claude_oauth_set = (
                bool(partner.id) and partner._vibecoder_ai_is_authenticated())

    # ------------------------------------------------------------------
    # Password hashing (same pbkdf2_sha512 scheme res.users uses)
    # ------------------------------------------------------------------
    @api.model
    def _vibecoder_crypt_context(self):
        from passlib.context import CryptContext
        return CryptContext(schemes=["pbkdf2_sha512"])

    def _vibecoder_set_password(self, password):
        self.ensure_one()
        self.vibecoder_password_hash = self._vibecoder_crypt_context().hash(password)

    # ------------------------------------------------------------------
    # Signup / credential check — server-side validated
    # ------------------------------------------------------------------
    @api.model
    def _vibecoder_signup(self, login, password, name):
        login = (login or "").strip().lower()
        password = password or ""
        name = (name or "").strip()

        normalized = email_normalize(login)
        if not normalized:
            raise UserError(_("Please enter a valid email address."))
        login = normalized
        if len(password) < MIN_PASSWORD_LEN:
            raise UserError(_(
                "Password must be at least %s characters long.") % MIN_PASSWORD_LEN)
        if not name:
            name = login.split("@")[0]

        existing = self.sudo().search([("vibecoder_login", "=", login)], limit=1)
        if existing:
            raise UserError(_("An account with this email already exists."))

        partner = self.sudo().create({
            "name": name,
            "email": login,
            "vibecoder_login": login,
            "vibecoder_active": True,
        })
        partner._vibecoder_set_password(password)
        return partner

    @api.model
    def _vibecoder_check_credentials(self, login, password):
        """Return the (sudo) partner if login/password match, else False."""
        login = email_normalize((login or "").strip().lower()) or ""
        if not login or not password:
            return False
        partner = self.sudo().search([("vibecoder_login", "=", login)], limit=1)
        if not partner or not partner.vibecoder_password_hash:
            return False
        ctx = self._vibecoder_crypt_context()
        try:
            ok, new_hash = ctx.verify_and_update(password, partner.vibecoder_password_hash)
        except (ValueError, TypeError):
            return False
        if not ok:
            return False
        if new_hash:
            partner.vibecoder_password_hash = new_hash
        if not partner.vibecoder_active:
            raise UserError(_("This account is disabled."))
        return partner

    # ------------------------------------------------------------------
    # Per-partner Claude config dir (CLAUDE_CONFIG_DIR) and credentials file
    # ------------------------------------------------------------------
    def _vibecoder_ai_home_root(self):
        root = self.env["ir.config_parameter"].sudo().get_param(
            "vibecoder.home_root") or "/var/lib/odoo/vibecoder_home"
        return root

    def _vibecoder_ai_home_dir(self):
        self.ensure_one()
        return os.path.join(self._vibecoder_ai_home_root(), str(self.id))

    def _vibecoder_ai_config_dir(self, create=False):
        self.ensure_one()
        path = os.path.join(self._vibecoder_ai_home_dir(), ".claude")
        if create:
            try:
                os.makedirs(path, mode=0o700, exist_ok=True)
            except OSError as e:
                raise UserError(_("Cannot create Claude config dir %s: %s") % (path, e))
        return path

    def _vibecoder_ai_credentials_path(self):
        self.ensure_one()
        return os.path.join(self._vibecoder_ai_config_dir(), ".credentials.json")

    def _vibecoder_ai_is_authenticated(self):
        self.ensure_one()
        try:
            with open(self._vibecoder_ai_credentials_path(), "r") as f:
                data = json.load(f)
            return bool((data.get("claudeAiOauth") or {}).get("accessToken"))
        except (OSError, ValueError):
            return False

    def _vibecoder_ai_logout(self):
        self.ensure_one()
        try:
            os.remove(self._vibecoder_ai_credentials_path())
        except OSError:
            pass
        return True

    # ------------------------------------------------------------------
    # OAuth (PKCE) login flow — identical protocol to claudoo, keyed by partner
    # ------------------------------------------------------------------
    def _vibecoder_ai_oauth_start(self):
        self.ensure_one()
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)

        self.env["ir.config_parameter"].sudo().set_param(
            _PKCE_PARAM % self.id,
            json.dumps({"verifier": verifier, "state": state}))

        from urllib.parse import urlencode
        params = {
            "code": "true",
            "client_id": OAUTH_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": OAUTH_SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        return "%s?%s" % (OAUTH_AUTHORIZE_URL, urlencode(params))

    def _vibecoder_ai_oauth_complete(self, pasted_code):
        self.ensure_one()
        pasted_code = (pasted_code or "").strip()
        if not pasted_code:
            raise UserError(_("Paste the authorization code from Claude."))

        ICP = self.env["ir.config_parameter"].sudo()
        raw = ICP.get_param(_PKCE_PARAM % self.id)
        if not raw:
            raise UserError(_("No login in progress. Click “Connect Claude” first."))
        pkce = json.loads(raw)

        code, _sep, state = pasted_code.partition("#")
        if state and pkce.get("state") and state != pkce["state"]:
            raise UserError(_("Authorization state mismatch. Please try connecting again."))

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "state": state or pkce.get("state"),
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "code_verifier": pkce["verifier"],
        }
        try:
            resp = requests.post(
                OAUTH_TOKEN_URL, json=payload,
                headers={"Content-Type": "application/json"}, timeout=30)
        except requests.RequestException as e:
            raise UserError(_("Could not reach Claude to exchange the code: %s") % e)
        if resp.status_code != 200:
            _logger.warning("Claude OAuth exchange failed (%s): %s",
                             resp.status_code, resp.text[:500])
            raise UserError(_(
                "Claude rejected the authorization code (HTTP %s). The code may "
                "have expired — please try connecting again.") % resp.status_code)

        data = resp.json()
        access = data.get("access_token")
        if not access:
            raise UserError(_("Claude did not return an access token."))
        expires_in = int(data.get("expires_in") or 0)
        scopes = (data.get("scope") or OAUTH_SCOPES).split()

        creds = {
            "claudeAiOauth": {
                "accessToken": access,
                "refreshToken": data.get("refresh_token") or "",
                "expiresAt": int((time.time() + expires_in) * 1000),
                "scopes": scopes,
                "subscriptionType": data.get("subscription_type") or "",
            }
        }
        self._vibecoder_ai_write_credentials(creds)
        ICP.set_param(_PKCE_PARAM % self.id, "")
        return True

    def _vibecoder_ai_write_credentials(self, creds):
        self.ensure_one()
        self._vibecoder_ai_config_dir(create=True)
        path = self._vibecoder_ai_credentials_path()
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(creds, f)
        os.replace(tmp, path)
