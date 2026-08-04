# -*- coding: utf-8 -*-
{
    'name': "Partner Ledger Report (SQL)",
    'summary': "Partner ledger with opening/closing balance computed via raw SQL for performance",
    'description': """
Partner Ledger Report (SQL)
============================
A partner ledger report (opening balance, debit, credit, closing balance per
partner) computed with raw SQL window functions instead of ORM search/read_group,
for better performance on large account_move_line tables.
""",
    'author': "CICDoo",
    'website': "https://cicdoo.com",
    'category': 'Accounting/Accounting',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/partner_ledger_report_views.xml',
        'report/partner_ledger_report_templates.xml',
        'report/partner_ledger_report_reports.xml',
        'views/partner_ledger_report_menu.xml',
    ],
    'installable': True,
    'application': False,
}
