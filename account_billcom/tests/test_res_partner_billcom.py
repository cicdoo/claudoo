# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestResPartnerBillcom(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'billcom_enabled': True,
            'billcom_dev_key': 'dev-key',
            'billcom_username': 'user',
            'billcom_password': 'pass',
            'billcom_organization_id': 'org-1',
        })
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Test Vendor',
            'supplier_rank': 1,
            'email': 'vendor@example.com',
        })

    def test_prepare_vendor_payload(self):
        payload = self.vendor._billcom_prepare_vendor_payload()
        self.assertEqual(payload['name'], 'Test Vendor')
        self.assertEqual(payload['email'], 'vendor@example.com')

    def test_sync_vendor_non_supplier_raises(self):
        customer = self.env['res.partner'].create({'name': 'Test Customer', 'supplier_rank': 0})
        with self.assertRaises(UserError):
            customer.action_billcom_sync_vendor()

    def test_sync_vendor_success_writes_state(self):
        mock_client = Mock()
        mock_client.create_vendor.return_value = {'id': 'vend-123'}
        with patch.object(type(self.company), '_billcom_get_client', return_value=mock_client):
            self.vendor.action_billcom_sync_vendor()

        self.assertEqual(self.vendor.billcom_vendor_id, 'vend-123')
        self.assertEqual(self.vendor.billcom_sync_state, 'synced')
        log = self.env['account.billcom.log'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.vendor.id),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.status, 'success')

    def test_sync_vendor_error_writes_state_and_log(self):
        from odoo.addons.account_billcom.lib.billcom_client import BillComError

        mock_client = Mock()
        mock_client.create_vendor.side_effect = BillComError('boom')
        with patch.object(type(self.company), '_billcom_get_client', return_value=mock_client):
            # Not using assertRaises: Odoo's TransactionCase.assertRaises wraps the
            # block in a savepoint that rolls back once the exception fires, which
            # would also undo the state/log writes this test needs to check.
            try:
                self.vendor.action_billcom_sync_vendor()
                self.fail("Expected a UserError")
            except UserError:
                pass

        self.assertEqual(self.vendor.billcom_sync_state, 'error')
        self.assertEqual(self.vendor.billcom_sync_error, 'boom')
        log = self.env['account.billcom.log'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.vendor.id),
        ])
        self.assertEqual(log.status, 'error')
