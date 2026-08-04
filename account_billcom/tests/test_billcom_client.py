# -*- coding: utf-8 -*-
import unittest
from unittest.mock import Mock, patch

from odoo.addons.account_billcom.lib.billcom_client import BillComClient, BillComError


class TestBillComClient(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.client = BillComClient('dev-key', 'sandbox')

    def _mock_response(self, status_code=200, json_data=None):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = json_data or {}
        response.text = ''
        return response

    @patch('odoo.addons.account_billcom.lib.billcom_client.requests.post')
    def test_login_success(self, mock_post):
        mock_post.return_value = self._mock_response(200, {'sessionId': 'sess-123'})

        session_id = self.client.login('user', 'pass', 'org-1')

        self.assertEqual(session_id, 'sess-123')
        self.assertEqual(self.client.session_id, 'sess-123')
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json'], {
            'devKey': 'dev-key',
            'username': 'user',
            'password': 'pass',
            'organizationId': 'org-1',
        })

    @patch('odoo.addons.account_billcom.lib.billcom_client.requests.post')
    def test_login_missing_session_id_raises(self, mock_post):
        mock_post.return_value = self._mock_response(200, {})

        with self.assertRaises(BillComError):
            self.client.login('user', 'pass', 'org-1')

    @patch('odoo.addons.account_billcom.lib.billcom_client.requests.post')
    def test_login_error_status_raises(self, mock_post):
        mock_post.return_value = self._mock_response(401, {'error': {'message': 'Invalid credentials'}})

        with self.assertRaises(BillComError) as cm:
            self.client.login('user', 'wrong-pass', 'org-1')
        self.assertIn('Invalid credentials', str(cm.exception))

    def test_request_without_login_raises(self):
        with self.assertRaises(BillComError):
            self.client.create_vendor({'name': 'Acme'})

    @patch('odoo.addons.account_billcom.lib.billcom_client.requests.request')
    @patch('odoo.addons.account_billcom.lib.billcom_client.requests.post')
    def test_create_vendor_uses_session_headers(self, mock_post, mock_request):
        mock_post.return_value = self._mock_response(200, {'sessionId': 'sess-123'})
        self.client.login('user', 'pass', 'org-1')

        mock_request.return_value = self._mock_response(200, {'id': 'vend-1'})
        result = self.client.create_vendor({'name': 'Acme'})

        self.assertEqual(result, {'id': 'vend-1'})
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs['headers']['sessionId'], 'sess-123')
        self.assertEqual(kwargs['headers']['devKey'], 'dev-key')

    @patch('odoo.addons.account_billcom.lib.billcom_client.requests.request')
    @patch('odoo.addons.account_billcom.lib.billcom_client.requests.post')
    def test_create_bill_error_payload_raises(self, mock_post, mock_request):
        mock_post.return_value = self._mock_response(200, {'sessionId': 'sess-123'})
        self.client.login('user', 'pass', 'org-1')

        mock_request.return_value = self._mock_response(200, {'error': {'message': 'Invalid vendorId'}})
        with self.assertRaises(BillComError) as cm:
            self.client.create_bill({'vendorId': 'bad-id'})
        self.assertIn('Invalid vendorId', str(cm.exception))

    def test_invalid_environment_raises(self):
        with self.assertRaises(ValueError):
            BillComClient('dev-key', 'not-an-environment')
