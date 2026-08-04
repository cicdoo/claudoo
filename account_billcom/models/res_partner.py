# -*- coding: utf-8 -*-
import json

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..lib.billcom_client import BillComError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    billcom_vendor_id = fields.Char(string="Bill.com Vendor ID", readonly=True, copy=False, tracking=True)
    billcom_sync_state = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced'),
        ('error', 'Error'),
    ], default='not_synced', readonly=True, copy=False, tracking=True)
    billcom_sync_error = fields.Text(readonly=True, copy=False)

    def _billcom_prepare_vendor_payload(self):
        self.ensure_one()
        return {
            'name': self.name,
            'nameOnCheck': self.name,
            'email': self.email or None,
            'phone': self.phone or None,
            'address1': self.street or None,
            'address2': self.street2 or None,
            'addressCity': self.city or None,
            'addressState': self.state_id.code or None,
            'addressZip': self.zip or None,
            'addressCountry': self.country_id.code or None,
            'taxId': self.vat or None,
        }

    def action_billcom_sync_vendor(self):
        for partner in self:
            partner._billcom_sync_vendor()

    def _billcom_sync_vendor(self):
        self.ensure_one()
        if self.supplier_rank <= 0:
            raise UserError(_("Only vendors (suppliers) can be synced to Bill.com."))

        payload = self._billcom_prepare_vendor_payload()
        log = self.env['account.billcom.log']
        try:
            client = self.company_id._billcom_get_client() if self.company_id else \
                self.env.company._billcom_get_client()
            response = client.create_vendor(payload)
        except (BillComError, UserError) as error:
            self.write({
                'billcom_sync_state': 'error',
                'billcom_sync_error': str(error),
            })
            log._log(self, 'push', 'error', request_payload=json.dumps(payload), error_message=str(error))
            raise UserError(_("Bill.com vendor sync failed: %s", error))

        vendor_id = response.get('id')
        self.write({
            'billcom_vendor_id': vendor_id,
            'billcom_sync_state': 'synced',
            'billcom_sync_error': False,
        })
        log._log(self, 'push', 'success', request_payload=json.dumps(payload), response_payload=json.dumps(response))
        return vendor_id
