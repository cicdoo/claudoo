# -*- coding: utf-8 -*-
import json
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..lib.billcom_client import BillComError

_logger = logging.getLogger(__name__)

BILL_MOVE_TYPES = ('in_invoice', 'in_refund')


class AccountMove(models.Model):
    _inherit = 'account.move'

    billcom_bill_id = fields.Char(string="Bill.com Bill ID", readonly=True, copy=False, tracking=True)
    billcom_sync_state = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced'),
        ('error', 'Error'),
    ], default='not_synced', readonly=True, copy=False, tracking=True)
    billcom_sync_error = fields.Text(readonly=True, copy=False)
    billcom_payment_status = fields.Char(string="Bill.com Payment Status", readonly=True, copy=False)

    def _billcom_prepare_bill_payload(self):
        self.ensure_one()
        if self.move_type not in BILL_MOVE_TYPES:
            raise UserError(_("Only vendor bills and vendor credit notes can be sent to Bill.com."))
        if self.state != 'posted':
            raise UserError(_("Only posted vendor bills can be sent to Bill.com."))

        vendor_id = self.partner_id.billcom_vendor_id
        if not vendor_id:
            vendor_id = self.partner_id._billcom_sync_vendor()

        return {
            'vendorId': vendor_id,
            'invoiceNumber': self.ref or self.payment_reference or self.name,
            'invoiceDate': fields.Date.to_string(self.invoice_date),
            'dueDate': fields.Date.to_string(self.invoice_date_due),
            'billLineItems': [
                {
                    'amount': line.price_subtotal,
                    'description': line.name or '',
                }
                for line in self.invoice_line_ids
                if not line.display_type
            ],
        }

    def action_billcom_send_bill(self):
        for move in self:
            move._billcom_send_bill()

    def _billcom_send_bill(self):
        self.ensure_one()
        payload = self._billcom_prepare_bill_payload()
        log = self.env['account.billcom.log']
        try:
            client = self.company_id._billcom_get_client()
            response = client.create_bill(payload)
        except (BillComError, UserError) as error:
            self.write({
                'billcom_sync_state': 'error',
                'billcom_sync_error': str(error),
            })
            log._log(self, 'push', 'error', request_payload=json.dumps(payload), error_message=str(error))
            raise UserError(_("Bill.com bill sync failed: %s", error))

        self.write({
            'billcom_bill_id': response.get('id'),
            'billcom_sync_state': 'synced',
            'billcom_sync_error': False,
        })
        log._log(self, 'push', 'success', request_payload=json.dumps(payload), response_payload=json.dumps(response))

    def _cron_billcom_pull_payment_status(self):
        moves = self.search([
            ('billcom_bill_id', '!=', False),
            ('billcom_payment_status', '!=', 'PAID'),
        ])
        log = self.env['account.billcom.log']
        for company in moves.company_id:
            if not company.billcom_enabled:
                continue
            company_moves = moves.filtered(lambda m: m.company_id == company)
            try:
                client = company._billcom_get_client()
            except (BillComError, UserError) as error:
                _logger.warning(
                    "Bill.com: could not pull payment status for company %s: %s",
                    company.display_name, error,
                )
                continue

            for move in company_moves:
                try:
                    response = client.get_bill(move.billcom_bill_id)
                except BillComError as error:
                    log._log(move, 'pull', 'error', error_message=str(error))
                    continue

                payment_status = response.get('paymentStatus')
                if payment_status and payment_status != move.billcom_payment_status:
                    move.billcom_payment_status = payment_status
                    move.message_post(body=_("Bill.com payment status: %s", payment_status))
                log._log(move, 'pull', 'success', response_payload=json.dumps(response))
