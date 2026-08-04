# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.fields import Datetime

from ..lib.billcom_client import BillComClient, BillComError

_logger = logging.getLogger(__name__)

# Bill.com sessions go idle after ~35 minutes; reuse a bit under that so we
# never hand out a session that expires mid-call.
SESSION_LIFETIME = timedelta(minutes=30)


class ResCompany(models.Model):
    _inherit = 'res.company'

    billcom_enabled = fields.Boolean(string="Bill.com Sync Enabled")
    billcom_dev_key = fields.Char(string="Bill.com Developer Key", groups='base.group_system')
    billcom_username = fields.Char(string="Bill.com Username", groups='base.group_system')
    billcom_password = fields.Char(string="Bill.com Password", groups='base.group_system')
    billcom_organization_id = fields.Char(string="Bill.com Organization ID", groups='base.group_system')
    billcom_environment = fields.Selection(
        string="Bill.com Environment",
        selection=[
            ('sandbox', 'Sandbox'),
            ('production', 'Production'),
        ],
        required=True,
        default='sandbox',
    )

    # Internal session cache, not exposed on any view.
    billcom_session_id = fields.Char(string="Bill.com Session ID", groups='base.group_system', copy=False)
    billcom_session_expiry = fields.Datetime(string="Bill.com Session Expiry", groups='base.group_system', copy=False)

    def _billcom_get_client(self):
        """Return a logged-in BillComClient for this company.

        Reuses the cached session while it is still fresh, otherwise logs in
        again and persists the new session so concurrent calls don't each
        pay for their own login round-trip.
        """
        self.ensure_one()
        if not self.billcom_enabled:
            raise UserError("Bill.com sync is not enabled for this company.")
        if not (self.billcom_dev_key and self.billcom_username and self.billcom_password
                and self.billcom_organization_id):
            raise UserError("Bill.com credentials are incomplete. Please configure them in Settings.")

        client = BillComClient(self.billcom_dev_key, self.billcom_environment)
        now = Datetime.now()
        if self.billcom_session_id and self.billcom_session_expiry and self.billcom_session_expiry > now:
            client.session_id = self.billcom_session_id
            return client

        try:
            client.login(self.billcom_username, self.billcom_password, self.billcom_organization_id)
        except BillComError:
            self.sudo().write({'billcom_session_id': False, 'billcom_session_expiry': False})
            raise

        self.sudo().write({
            'billcom_session_id': client.session_id,
            'billcom_session_expiry': now + SESSION_LIFETIME,
        })
        return client
