# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestAccountMoveBillcom(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_data['company'].write({
            'billcom_enabled': True,
            'billcom_dev_key': 'dev-key',
            'billcom_username': 'user',
            'billcom_password': 'pass',
            'billcom_organization_id': 'org-1',
        })
        cls.partner_a.write({'supplier_rank': 1, 'billcom_vendor_id': 'vend-123'})
        cls.bill = cls._create_invoice(move_type='in_invoice', partner_id=cls.partner_a.id, post=True)

    def test_prepare_bill_payload(self):
        payload = self.bill._billcom_prepare_bill_payload()
        self.assertEqual(payload['vendorId'], 'vend-123')
        billable_lines = self.bill.invoice_line_ids.filtered(lambda line: not line.display_type)
        self.assertEqual(len(payload['billLineItems']), len(billable_lines))

    def test_prepare_bill_payload_not_posted_raises(self):
        draft_bill = self._create_invoice(move_type='in_invoice', partner_id=self.partner_a.id, post=False)
        with self.assertRaises(UserError):
            draft_bill._billcom_prepare_bill_payload()

    def test_send_bill_success_writes_state_and_log(self):
        mock_client = Mock()
        mock_client.create_bill.return_value = {'id': 'bill-999'}
        with patch.object(type(self.bill.company_id), '_billcom_get_client', return_value=mock_client):
            self.bill.action_billcom_send_bill()

        self.assertEqual(self.bill.billcom_bill_id, 'bill-999')
        self.assertEqual(self.bill.billcom_sync_state, 'synced')
        log = self.env['account.billcom.log'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.bill.id),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.status, 'success')

    def test_cron_pull_payment_status_updates_move(self):
        self.bill.billcom_bill_id = 'bill-999'
        mock_client = Mock()
        mock_client.get_bill.return_value = {'paymentStatus': 'PAID'}
        with patch.object(type(self.bill.company_id), '_billcom_get_client', return_value=mock_client):
            self.env['account.move']._cron_billcom_pull_payment_status()

        self.assertEqual(self.bill.billcom_payment_status, 'PAID')
