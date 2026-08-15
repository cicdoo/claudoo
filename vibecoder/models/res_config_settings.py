# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    vibecoder_github_client_id = fields.Char(
        string="GitHub OAuth Client ID",
        config_parameter="vibecoder.github_client_id",
        help="From a GitHub OAuth App registered at github.com/settings/developers, "
             "with callback URL https://<this-instance-domain>/vibecoder/github/callback.")
    vibecoder_github_client_secret = fields.Char(
        string="GitHub OAuth Client Secret",
        config_parameter="vibecoder.github_client_secret")
    vibecoder_cli_path = fields.Char(
        string="Vibecoder Claude CLI Path", config_parameter="vibecoder.cli_path",
        default="/opt/odoo/.local/bin/claude")
    vibecoder_model = fields.Char(
        string="Model", config_parameter="vibecoder.model",
        default="claude-sonnet-4-5")
    vibecoder_max_turns = fields.Integer(
        string="Max Turns per Message", config_parameter="vibecoder.max_turns",
        default=40)
    vibecoder_timeout_s = fields.Integer(
        string="Vibecoder Run Timeout (s)", config_parameter="vibecoder.timeout_s",
        default=900)
    vibecoder_max_concurrent_claude_runs = fields.Integer(
        string="Max Concurrent Claude Runs",
        config_parameter="vibecoder.max_concurrent_claude_runs", default=2)
    vibecoder_max_concurrent_previews = fields.Integer(
        string="Max Concurrent Previews",
        config_parameter="vibecoder.max_concurrent_previews", default=4)
    vibecoder_preview_port_range = fields.Char(
        string="Preview Port Range", config_parameter="vibecoder.preview_port_range",
        default="17000-17199")
    vibecoder_workspace_root = fields.Char(
        string="Project Workspace Root", config_parameter="vibecoder.workspace_root",
        default="/var/lib/odoo/vibecoder_workspaces")
    vibecoder_home_root = fields.Char(
        string="Per-Partner Claude Home Root", config_parameter="vibecoder.home_root",
        default="/var/lib/odoo/vibecoder_home")
    vibecoder_max_upload_mb = fields.Integer(
        string="Vibecoder Max Upload Size (MB)", config_parameter="vibecoder.max_upload_mb",
        default=50)
    vibecoder_upload_chunk_mb = fields.Integer(
        string="Upload Chunk Size (MB)", config_parameter="vibecoder.upload_chunk_mb",
        default=4)
