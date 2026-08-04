# -*- coding: utf-8 -*-
"""Minimal Bill.com Connect (v3) REST client.

This is a plain-Python wrapper around the subset of the Bill.com v3 API that
this addon needs (login, vendors, bills). It has no Odoo imports so it can be
used and tested in isolation.

Reference: https://developer.bill.com/reference (Connect API v3).
"""
import logging

import requests

_logger = logging.getLogger(__name__)

BASE_URLS = {
    'sandbox': 'https://gateway.stage.bill.com/connect/v3',
    'production': 'https://gateway.bill.com/connect/v3',
}

TIMEOUT = 60


class BillComError(Exception):
    """Raised for any Bill.com login/transport/API-level error."""


class BillComClient:
    def __init__(self, dev_key, environment='sandbox'):
        if environment not in BASE_URLS:
            raise ValueError("environment must be 'sandbox' or 'production'")
        self.dev_key = dev_key
        self.environment = environment
        self.base_url = BASE_URLS[environment]
        self.session_id = None

    def login(self, username, password, organization_id):
        response = requests.post(
            f'{self.base_url}/login',
            json={
                'devKey': self.dev_key,
                'username': username,
                'password': password,
                'organizationId': organization_id,
            },
            headers={'Content-Type': 'application/json'},
            timeout=TIMEOUT,
        )
        payload = self._parse_response(response)
        session_id = payload.get('sessionId')
        if not session_id:
            raise BillComError("Bill.com login did not return a sessionId")
        self.session_id = session_id
        return session_id

    def _auth_headers(self):
        """Build the headers used on every authenticated call.

        This is the single place to adjust if Bill.com's exact header names
        for sessionId/devKey differ from what is assumed here.
        """
        if not self.session_id:
            raise BillComError("Not logged in: call login() before making requests")
        return {
            'Content-Type': 'application/json',
            'sessionId': self.session_id,
            'devKey': self.dev_key,
        }

    def _request(self, method, path, json=None, params=None):
        response = requests.request(
            method,
            f'{self.base_url}{path}',
            json=json,
            params=params,
            headers=self._auth_headers(),
            timeout=TIMEOUT,
        )
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response):
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get('error')):
            message = BillComClient._extract_error_message(payload) or response.text or (
                f"Bill.com request failed with status {response.status_code}"
            )
            raise BillComError(message)

        if payload is None:
            raise BillComError("Bill.com returned a non-JSON response")

        return payload

    @staticmethod
    def _extract_error_message(payload):
        if not isinstance(payload, dict):
            return None
        error = payload.get('error')
        if isinstance(error, dict):
            return error.get('message') or str(error)
        if isinstance(error, str):
            return error
        message = payload.get('message')
        if message:
            return message
        return None

    def create_vendor(self, payload):
        return self._request('POST', '/vendors', json=payload)

    def create_bill(self, payload):
        return self._request('POST', '/bills', json=payload)

    def get_bill(self, bill_id):
        return self._request('GET', f'/bills/{bill_id}')

    def list_bills(self, params=None):
        return self._request('GET', '/bills', params=params)
