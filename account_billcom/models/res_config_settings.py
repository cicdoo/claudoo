# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError

from ..lib.billcom_client import BillComError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    billcom_enabled = fields.Boolean(related='company_id.billcom_enabled', readonly=False)
    billcom_dev_key = fields.Char(related='company_id.billcom_dev_key', readonly=False)
    billcom_username = fields.Char(related='company_id.billcom_username', readonly=False)
    billcom_password = fields.Char(related='company_id.billcom_password', readonly=False)
    billcom_organization_id = fields.Char(related='company_id.billcom_organization_id', readonly=False)
    billcom_environment = fields.Selection(related='company_id.billcom_environment', readonly=False)

    def action_billcom_test_connection(self):
        self.ensure_one()
        try:
            client = self.company_id._billcom_get_client()
            client.list_bills(params={'max': 1})
        except (BillComError, UserError) as error:
            raise UserError(_("Bill.com connection failed: %s", error))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Bill.com"),
                'message': _("Connection successful."),
                'type': 'success',
            },
        }
