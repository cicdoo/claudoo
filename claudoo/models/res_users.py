# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import base64
import hashlib
import json
import logging
import os
import secrets
import time

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools import str2bool

from .claudoo_session import READ_TOOLS, ALL_TOOLS, READONLY_TOOL_SET, WEB_TOOLS

_logger = logging.getLogger(__name__)

# --- Claude Code OAuth (subscription login) constants ------------------------
# These are the public Claude Code OAuth client parameters used by the
# `claude setup-token` / `/login` flow. The server has no browser, so we use the
# manual "copy code" redirect: the user authorizes in their own browser and
# pastes the returned `code#state` string back into Odoo.
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
OAUTH_SCOPES = "org:create_api_key user:profile user:inference"

# Transient PKCE state (verifier + state) stored per user while a login is in
# flight. Cleared once the code is exchanged.
_PKCE_PARAM = "claudoo.oauth_pkce.%s"


class ResUsers(models.Model):
    _inherit = "res.users"

    # Pure status indicator computed from the presence of valid per-user
    # credentials on disk. No token material is ever exposed on the record.
    claudoo_oauth_set = fields.Boolean(
        compute="_compute_claudoo_oauth_set", string="Personal Claude Linked")

    # --- Per-user AI tool permissions (manager-managed) ---
    claudoo_tool_ids = fields.Many2many(
        "claudoo.tool", "claudoo_user_tool_rel", "user_id", "tool_id",
        string="AI Tools Allowed",
        help="Tools this user may invoke through the AI Assistant. "
             "Leave empty to allow all read-only tools.")
    claudoo_zero_trust_mode = fields.Selection(
        [("inherit", "Inherit global default"),
         ("on", "Zero-trust (read-only)"),
         ("off", "Allow writes")],
        default="inherit", string="AI Zero-Trust Mode",
        help="When zero-trust is active, only read-only tools are available to "
             "this user — write tools are stripped regardless of the selection "
             "above. 'Inherit' follows the global default in Settings.")

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["claudoo_oauth_set"]

    def _compute_claudoo_oauth_set(self):
        for user in self:
            user.claudoo_oauth_set = bool(user.id) and user._ai_is_authenticated()

    # ------------------------------------------------------------------
    # Effective AI tool set (single source of truth, see claudoo.session)
    # ------------------------------------------------------------------
    def _ai_allowed_tool_names(self):
        """Per-user tool selection, independent of zero-trust.

        Empty selection falls back to all read tools (backward compatible:
        existing users keep today's read-only behavior; write tools require an
        explicit grant)."""
        self.ensure_one()
        sel = self.claudoo_tool_ids
        return set(sel.mapped("name")) if sel else set(READ_TOOLS)

    def _ai_zero_trust(self):
        """Whether zero-trust (read-only) mode is active for this user."""
        self.ensure_one()
        if self.claudoo_zero_trust_mode != "inherit":
            return self.claudoo_zero_trust_mode == "on"
        raw = self.env["claudoo.session"]._config("zero_trust_default")
        return str2bool(raw, False) if raw is not None else False

    def _ai_effective_tools(self):
        """THE source of truth: tool names this user may actually invoke."""
        self.ensure_one()
        names = self._ai_allowed_tool_names() & set(ALL_TOOLS)
        if self._ai_zero_trust():
            names = {n for n in names if n in READONLY_TOOL_SET}
        return names

    def _ai_account_email(self):
        """The email the assistant should treat as the user's."""
        self.ensure_one()
        return self.email or self.partner_id.email or self.login or ""

    def _ai_sync_cli_account(self):
        """Make the CLI's stored account identity match this Odoo user.

        Claude Code injects a '# userEmail' context line (and shows an account
        name) sourced from ``oauthAccount`` in ``<config_dir>/.claude.json``.
        Because each user runs with their *personal* Claude subscription, that
        email/name is their Claude account — not their Odoo identity — which made
        the assistant report the wrong person regardless of our system prompt.

        We overwrite only the display-only fields (emailAddress / displayName)
        with the Odoo user's, so the injected context agrees with the
        ODOO USER CONTEXT block. Authentication is untouched — it relies solely on
        the token in ``.credentials.json``. Re-run before every turn so a CLI
        server-side refresh can never leave a stale value in place.
        """
        self.ensure_one()
        path = os.path.join(self._ai_config_dir(create=True), ".claude.json")
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            # Not created yet (first ever run) — the CLI will write it; the next
            # turn patches it. Nothing we can safely do here.
            return False
        acct = data.get("oauthAccount")
        if not isinstance(acct, dict):
            return False
        email = self._ai_account_email()
        changed = False
        if email and acct.get("emailAddress") != email:
            acct["emailAddress"] = email
            changed = True
        if self.name and acct.get("displayName") != self.name:
            acct["displayName"] = self.name
            changed = True
        if not changed:
            return False
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        return True

    # ------------------------------------------------------------------
    # Identity / role context injected into the assistant's system prompt
    # ------------------------------------------------------------------
    def _ai_identity_prompt(self, effective_tools=None):
        """A concise, authoritative text block telling the model WHO the Odoo
        user is and what roles/permissions they hold.

        Called from the request env as the user (see claudoo.runner._launch),
        so it reflects exactly what this user can see. It carries no secrets — only
        identity, company, locale, privilege flags, application roles and the AI
        tool grant — so the model stops self-identifying as the Claude account and
        instead acts for, and within the rights of, this Odoo user."""
        self.ensure_one()
        if effective_tools is None:
            effective_tools = self._ai_effective_tools()

        email = self._ai_account_email() or "—"
        lines = [
            "--- ODOO USER CONTEXT (authoritative — this is who you are acting for) ---",
            "Name: %s" % (self.name or "—"),
            "Login: %s" % (self.login or "—"),
            "Email: %s" % email,
            "Odoo user id: %s" % self.id,
            "Company: %s" % (self.company_id.name or "—"),
        ]
        if len(self.company_ids) > 1:
            lines.append(
                "Allowed companies: %s"
                % ", ".join(self.company_ids.mapped("name")))
        lines.append("Language: %s" % (self.lang or "—"))
        lines.append("Timezone: %s" % (self.tz or "—"))

        # Privilege flags — stated plainly so the model never over-assumes rights.
        if self._is_admin():
            priv = "Administrator (full access)"
        elif self._is_system():
            priv = "Settings/System access"
        elif self.has_group("base.group_user"):
            priv = "Internal user (not an administrator)"
        else:
            priv = "Portal/public user (limited access)"
        lines.append("Privilege level: %s" % priv)

        # Curated roles: only groups that belong to an application category.
        roles = sorted(
            "%s / %s" % (g.category_id.name, g.name)
            for g in self.groups_id if g.category_id
        )
        if roles:
            lines.append("Roles:")
            lines.extend("  - %s" % r for r in roles)
        else:
            lines.append("Roles: (none beyond base access)")

        # What the assistant may actually do on this user's behalf.
        if not effective_tools:
            lines.append("AI tools available to you: none.")
        else:
            writeable = sorted(set(effective_tools) - READONLY_TOOL_SET)
            if writeable:
                lines.append(
                    "AI tool grant: read-only data access PLUS write/action tools "
                    "(%s). Use Odoo business actions when available." % ", ".join(writeable))
            else:
                lines.append(
                    "AI tool grant: READ-ONLY. You cannot create, modify or delete "
                    "data for this user — only query and report.")
        if set(effective_tools) & set(WEB_TOOLS):
            lines.append(
                "Web access: you may use WebFetch/WebSearch to retrieve and search "
                "public web content.")
        lines.append("--- END ODOO USER CONTEXT ---")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Per-user Claude config dir (CLAUDE_CONFIG_DIR) and credentials file
    # ------------------------------------------------------------------
    def _ai_home_root(self):
        """Root under which each user gets `<root>/<uid>/.claude`."""
        root = self.env["ir.config_parameter"].sudo().get_param(
            "claudoo.home_root") or "/var/lib/odoo/claudoo_home"
        return root

    def _ai_home_dir(self):
        """The HOME directory for this user's CLI runs."""
        self.ensure_one()
        return os.path.join(self._ai_home_root(), str(self.id))

    def _ai_config_dir(self, create=False):
        """This user's private CLAUDE_CONFIG_DIR (holds .credentials.json)."""
        self.ensure_one()
        path = os.path.join(self._ai_home_dir(), ".claude")
        if create:
            try:
                os.makedirs(path, mode=0o700, exist_ok=True)
            except OSError as e:
                raise UserError(_("Cannot create Claude config dir %s: %s") % (path, e))
        return path

    def _ai_credentials_path(self):
        self.ensure_one()
        return os.path.join(self._ai_config_dir(), ".credentials.json")

    def _ai_is_authenticated(self):
        """True if this user has stored, non-empty Claude OAuth credentials."""
        self.ensure_one()
        try:
            with open(self._ai_credentials_path(), "r") as f:
                data = json.load(f)
            return bool((data.get("claudeAiOauth") or {}).get("accessToken"))
        except (OSError, ValueError):
            return False

    def _ai_logout(self):
        """Remove this user's stored credentials (forces re-authentication)."""
        self.ensure_one()
        try:
            os.remove(self._ai_credentials_path())
        except OSError:
            pass
        return True

    def action_ai_claude_logout(self):
        """Button: disconnect this user's Claude account from preferences."""
        for user in self:
            user._ai_logout()
        return True

    # ------------------------------------------------------------------
    # OAuth (PKCE) login flow
    # ------------------------------------------------------------------
    def _ai_oauth_start(self):
        """Begin a login: mint PKCE pair, stash it, return the authorize URL."""
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

    def _ai_oauth_complete(self, pasted_code):
        """Exchange the pasted `code#state` for tokens and persist them."""
        self.ensure_one()
        pasted_code = (pasted_code or "").strip()
        if not pasted_code:
            raise UserError(_("Paste the authorization code from Claude."))

        ICP = self.env["ir.config_parameter"].sudo()
        raw = ICP.get_param(_PKCE_PARAM % self.id)
        if not raw:
            raise UserError(_("No login in progress. Click “Login with Claude” first."))
        pkce = json.loads(raw)

        # The console callback returns "<code>#<state>".
        code, _sep, state = pasted_code.partition("#")
        if state and pkce.get("state") and state != pkce["state"]:
            raise UserError(_("Authorization state mismatch. Please log in again."))

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
                "have expired — please log in again.") % resp.status_code)

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
                # Claude Code stores the expiry as a millisecond epoch.
                "expiresAt": int((time.time() + expires_in) * 1000),
                "scopes": scopes,
                "subscriptionType": data.get("subscription_type") or "",
            }
        }
        self._ai_write_credentials(creds)
        ICP.set_param(_PKCE_PARAM % self.id, "")  # consume the PKCE state
        return True

    def _ai_write_credentials(self, creds):
        """Atomically write `.credentials.json` (mode 0600) for this user."""
        self.ensure_one()
        self._ai_config_dir(create=True)
        path = self._ai_credentials_path()
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(creds, f)
        os.replace(tmp, path)
