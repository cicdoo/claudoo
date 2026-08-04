# -*- coding: utf-8 -*-
from collections import OrderedDict

from odoo import models


class ReportPartnerLedgerSql(models.AbstractModel):
    _name = 'report.partner_ledger_report_sql.report_partner_ledger_sql'
    _description = "Partner Ledger (SQL) Report Parser"

    def _get_report_values(self, docids, data=None):
        wizards = self.env['partner.ledger.report.wizard'].browse(docids)
        lines_by_partner = {}
        for wizard in wizards:
            grouped = OrderedDict()
            # wizard.line_ids is already ordered wizard_id, partner_id, sequence, date, id
            for line in wizard.line_ids:
                grouped.setdefault(line.partner_id, self.env['partner.ledger.report.line'])
                grouped[line.partner_id] |= line
            lines_by_partner[wizard.id] = grouped
        return {
            'doc_ids': docids,
            'doc_model': 'partner.ledger.report.wizard',
            'docs': wizards,
            'lines_by_partner': lines_by_partner,
        }
