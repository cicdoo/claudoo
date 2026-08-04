# -*- coding: utf-8 -*-
{
    'name': "Bill.com Connector",
    'summary': "Sync vendor bills and payment status with Bill.com",
    'description': """
Bill.com Connector
==================
Push vendor bills from Odoo to Bill.com and pull back their payment status.

* Sync vendors (res.partner) to Bill.com as Bill.com vendors.
* Send posted vendor bills to Bill.com.
* Periodically pull payment status back onto the vendor bill.
* Every call to the Bill.com API is written to an audit log.
""",
    'author': "CICDoo",
    'website': "https://cicdoo.com",
    'category': 'Accounting/Accounting',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['account_accountant'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/billcom_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/account_billcom_log_views.xml',
    ],
    'installable': True,
    'application': False,
}
