# -*- coding: utf-8 -*-
from odoo import api, fields, models


class VibecoderGithubAccount(models.Model):
    _name = "vibecoder.github_account"
    _description = "Vibecoder Connected GitHub Account"
    _rec_name = "github_login"

    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="cascade", index=True)
    github_login = fields.Char(required=True)
    github_user_id = fields.Integer()
    access_token_encrypted = fields.Char(
        help="Fernet-encrypted GitHub OAuth access token. Never stored in "
             "plaintext; see vibecoder.token_encryption_key.")
    scopes = fields.Char()

    _vibecoder_github_partner_uniq = models.Constraint(
        "unique(partner_id)",
        "This Vibecoder account is already connected to a GitHub account.",
    )

    # ------------------------------------------------------------------
    # Token encryption (Fernet, key auto-generated on first use)
    # ------------------------------------------------------------------
    @api.model
    def _fernet(self):
        from cryptography.fernet import Fernet
        ICP = self.env["ir.config_parameter"].sudo()
        key = ICP.get_param("vibecoder.token_encryption_key")
        if not key:
            key = Fernet.generate_key().decode()
            ICP.set_param("vibecoder.token_encryption_key", key)
        return Fernet(key.encode())

    def set_token(self, raw_token):
        self.ensure_one()
        self.access_token_encrypted = self._fernet().encrypt(
            raw_token.encode()).decode()

    def get_token(self):
        self.ensure_one()
        if not self.access_token_encrypted:
            return ""
        return self._fernet().decrypt(
            self.access_token_encrypted.encode()).decode()
