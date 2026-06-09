# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AiAssistantMessage(models.Model):
    _name = "claudoo.message"
    _description = "Claudoo AI Assistant Message"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one(
        "claudoo.session", required=True, ondelete="cascade", index=True)
    role = fields.Selection(
        [("user", "User"), ("assistant", "Assistant"),
         ("tool", "Tool"), ("error", "Error")],
        required=True, default="assistant")
    body = fields.Text()
    # The Anthropic message id (msg_...) used to upsert streamed assistant text.
    claude_msg_id = fields.Char(index=True, copy=False)
    # List of {id, name, input, result, status} dicts for tool_use chips.
    tool_calls = fields.Json()
    # List of {id, name, mimetype} dicts for files the user attached to the turn.
    attachments = fields.Json()

    def _to_frontend(self):
        """Serialize for the OWL chat (matches the bus payload shape)."""
        return [{
            "id": m.id,
            "role": m.role,
            "body": m.body or "",
            "tool_calls": m.tool_calls or [],
            "attachments": m.attachments or [],
            "create_date": fields.Datetime.to_string(m.create_date),
        } for m in self]
