# -*- coding: utf-8 -*-
from odoo import fields, models


class VibecoderMessage(models.Model):
    _name = "vibecoder.message"
    _description = "Vibecoder Chat Message"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one(
        "vibecoder.session", required=True, ondelete="cascade", index=True)
    role = fields.Selection(
        [("user", "User"), ("assistant", "Assistant"), ("error", "Error")],
        required=True, default="assistant")
    body = fields.Text()
    claude_msg_id = fields.Char(index=True, copy=False)
    tool_calls = fields.Json()
    seq = fields.Integer(index=True, copy=False)

    def _to_frontend(self):
        return [{
            "id": m.id,
            "role": m.role,
            "body": m.body or "",
            "tool_calls": m.tool_calls or [],
            "create_date": fields.Datetime.to_string(m.create_date),
        } for m in self]
