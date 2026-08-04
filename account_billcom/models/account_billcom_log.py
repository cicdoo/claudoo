# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountBillcomLog(models.Model):
    _name = 'account.billcom.log'
    _description = "Bill.com Sync Log"
    _order = 'create_date desc, id desc'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    direction = fields.Selection([
        ('push', 'Push to Bill.com'),
        ('pull', 'Pull from Bill.com'),
    ], required=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], required=True)
    request_payload = fields.Text()
    response_payload = fields.Text()
    error_message = fields.Text()

    def _log(self, record, direction, status, request_payload=None, response_payload=None, error_message=None):
        company = record.company_id if 'company_id' in record._fields and record.company_id else self.env.company
        return self.sudo().create({
            'company_id': company.id,
            'res_model': record._name,
            'res_id': record.id,
            'direction': direction,
            'status': status,
            'request_payload': request_payload,
            'response_payload': response_payload,
            'error_message': error_message,
        })
