# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_cli_path = fields.Char(
        string="Claude CLI Path",
        config_parameter="claudoo.cli_path",
        help="Absolute path to the claude binary. Leave empty to auto-detect.")
    ai_model = fields.Char(
        string="Model", config_parameter="claudoo.model",
        default="claude-sonnet-4-5")
    ai_max_turns = fields.Integer(
        string="Max Turns", config_parameter="claudoo.max_turns", default=30)
    ai_timeout_s = fields.Integer(
        string="Run Timeout (s)", config_parameter="claudoo.timeout_s",
        default=900)
    ai_scratch_root = fields.Char(
        string="Scratch Directory", config_parameter="claudoo.scratch_root",
        default="/var/lib/odoo/claudoo_scratch")
    ai_home_root = fields.Char(
        string="Per-User Claude Home Root", config_parameter="claudoo.home_root",
        default="/var/lib/odoo/claudoo_home",
        help="Root directory under which each user gets a private "
             "<root>/<uid>/.claude holding their own OAuth credentials.")
    ai_base_url = fields.Char(
        string="Odoo Host URL", config_parameter="claudoo.base_url",
        default="http://127.0.0.1:8069",
        help="Host URL the MCP bridge connects back to (loopback by default).")
    ai_db_name = fields.Char(
        string="Odoo Database", config_parameter="claudoo.db_name",
        help="Database the assistant connects to. Leave empty to use the current "
             "database. Set this in multi-database deployments so the bridge "
             "always reaches the right database.")
    ai_sql_enabled = fields.Boolean(
        string="Enable SQL Reporting Tool",
        config_parameter="claudoo.sql_enabled", default=True,
        help="Allow the read-only SQL tool (members of the AI SQL Analyst group).")
    ai_zero_trust_default = fields.Boolean(
        string="Zero-Trust by Default (read-only)",
        config_parameter="claudoo.zero_trust_default", default=False,
        help="Instance-wide default: when on, users left on 'Inherit' may only "
             "use read-only tools. A per-user override can still allow writes.")
    ai_action_method_patterns = fields.Char(
        string="AI Action Method Patterns",
        config_parameter="claudoo.action_methods",
        default="action_*,button_*",
        help="Comma-separated fnmatch patterns for methods orm_action/run_wizard "
             "may call (e.g. action_*,button_*). Private/dunder methods are "
             "always blocked.")
    # Non-stored: persisted as a CSV of technical names in the
    # claudoo.excluded_models system parameter (see get/set_values).
    ai_excluded_model_ids = fields.Many2many(
        "ir.model", string="Models Hidden from AI",
        help="The AI Assistant will refuse to introspect, read, or write these "
             "models for every user.")
    # Non-stored: persisted as a CSV of ids in the claudoo.server_action_ids
    # system parameter (see get/set_values). Only these may be run via
    # run_server_action; an allowlisted server action is trusted-by-admin.
    ai_allowed_server_action_ids = fields.Many2many(
        "ir.actions.server", string="AI-Runnable Server Actions",
        help="Only these server actions may be run via run_server_action. "
             "Empty = none. A 'code' server action runs arbitrary Python, so "
             "only allowlist actions you trust.")

    def get_values(self):
        res = super().get_values()
        names = self.env["claudoo.session"]._ai_excluded_models()
        models = self.env["ir.model"].search([("model", "in", list(names))])
        res["ai_excluded_model_ids"] = [(6, 0, models.ids)]
        sa_ids = self.env["claudoo.session"]._ai_allowed_server_action_ids()
        res["ai_allowed_server_action_ids"] = [(6, 0, list(sa_ids))]
        return res

    def set_values(self):
        super().set_values()
        names = ",".join(sorted(self.ai_excluded_model_ids.mapped("model")))
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("claudoo.excluded_models", names)
        ICP.set_param("claudoo.server_action_ids",
                      ",".join(map(str, sorted(self.ai_allowed_server_action_ids.ids))))
