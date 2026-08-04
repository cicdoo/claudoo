# -*- coding: utf-8 -*-
from odoo import api, fields, models

ACCOUNT_TYPES_BY_FILTER = {
    'receivable': ('asset_receivable',),
    'payable': ('liability_payable',),
    'both': ('asset_receivable', 'liability_payable'),
}


class PartnerLedgerReportWizard(models.TransientModel):
    _name = 'partner.ledger.report.wizard'
    _description = "Partner Ledger Report (SQL) Wizard"

    company_id = fields.Many2one(
        'res.company', string="Company", required=True,
        default=lambda self: self.env.company)
    date_from = fields.Date(string="Date From", required=True,
                             default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(string="Date To", required=True,
                           default=fields.Date.context_today)
    partner_ids = fields.Many2many('res.partner', string="Partners")
    account_type = fields.Selection([
        ('receivable', "Receivable"),
        ('payable', "Payable"),
        ('both', "Receivable & Payable"),
    ], string="Account Type", default='both', required=True)
    target_move = fields.Selection([
        ('posted', "All Posted Entries"),
        ('all', "All Entries"),
    ], string="Target Moves", default='posted', required=True)
    line_ids = fields.One2many('partner.ledger.report.line', 'wizard_id', string="Lines")

    def action_view_report(self):
        self._generate_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': "Partner Ledger (SQL)",
            'res_model': 'partner.ledger.report.line',
            'view_mode': 'list,pivot',
            'domain': [('wizard_id', '=', self.id)],
            'context': {
                'search_default_group_by_partner': 1,
                'default_wizard_id': self.id,
            },
        }

    def action_print_pdf(self):
        self._generate_lines()
        return self.env.ref(
            'partner_ledger_report_sql.action_report_partner_ledger_sql'
        ).report_action(self)

    def _generate_lines(self):
        """Compute opening balance, detail lines and closing balance entirely in SQL
        (single WITH CTE reused by three INSERT ... SELECT statements) rather than
        looping over recordsets in Python, so the report stays fast on large
        account_move_line tables.
        """
        self.ensure_one()
        cr = self.env.cr

        cr.execute("DELETE FROM partner_ledger_report_line WHERE wizard_id = %s", (self.id,))

        account_types = ACCOUNT_TYPES_BY_FILTER[self.account_type]
        state_clause = "am.state = 'posted'" if self.target_move == 'posted' else "am.state != 'cancel'"

        if self.partner_ids:
            partner_clause = "aml.partner_id = ANY(%(partner_ids)s)"
            partner_ids = self.partner_ids.ids
        else:
            partner_clause = "aml.partner_id IS NOT NULL"
            partner_ids = None

        params = {
            'wizard_id': self.id,
            'company_id': self.company_id.id,
            'account_types': list(account_types),
            'date_from': self.date_from,
            'date_to': self.date_to,
            'partner_ids': partner_ids,
        }

        base_where = """
            aml.company_id = %(company_id)s
            AND aa.account_type = ANY(%(account_types)s)
            AND {partner_clause}
            AND {state_clause}
            AND aml.display_type NOT IN ('line_section', 'line_subsection', 'line_note')
        """.format(partner_clause=partner_clause, state_clause=state_clause)

        cte = """
            WITH opening AS (
                SELECT
                    aml.partner_id AS partner_id,
                    SUM(aml.debit) AS debit,
                    SUM(aml.credit) AS credit,
                    SUM(aml.balance) AS balance
                FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                JOIN account_account aa ON aa.id = aml.account_id
                WHERE {base_where}
                AND aml.date < %(date_from)s
                GROUP BY aml.partner_id
            )
        """.format(base_where=base_where)

        period_cte = """
            , period AS (
                SELECT
                    aml.partner_id AS partner_id,
                    SUM(aml.debit) AS debit,
                    SUM(aml.credit) AS credit,
                    SUM(aml.balance) AS balance
                FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                JOIN account_account aa ON aa.id = aml.account_id
                WHERE {base_where}
                AND aml.date BETWEEN %(date_from)s AND %(date_to)s
                GROUP BY aml.partner_id
            )
        """.format(base_where=base_where)

        cte_with_period = cte + period_cte

        # 1. Opening balance line per partner, for every partner that appears
        # either in the opening balance or in the period (partners with no
        # prior activity get a 0 opening line instead of no line at all).
        cr.execute(cte_with_period + """
            INSERT INTO partner_ledger_report_line
                (wizard_id, partner_id, line_type, sequence, debit, credit, balance, create_date, create_uid)
            SELECT
                %(wizard_id)s, COALESCE(opening.partner_id, period.partner_id), 'opening', 0,
                COALESCE(opening.debit, 0), COALESCE(opening.credit, 0), COALESCE(opening.balance, 0),
                now(), %(uid)s
            FROM opening
            FULL OUTER JOIN period ON period.partner_id = opening.partner_id
        """, {**params, 'uid': self.env.uid})

        # 2. Detail lines within [date_from, date_to] with the running balance
        # (opening + cumulative SUM over the period) computed via a window function.
        cr.execute(cte + """
            INSERT INTO partner_ledger_report_line
                (wizard_id, partner_id, line_type, sequence, date, move_id, move_name,
                 journal_id, ref, debit, credit, balance, create_date, create_uid)
            SELECT
                %(wizard_id)s, aml.partner_id, 'line', 10, aml.date, aml.move_id, aml.move_name,
                aml.journal_id, aml.ref, aml.debit, aml.credit,
                COALESCE(opening.balance, 0) + SUM(aml.balance) OVER (
                    PARTITION BY aml.partner_id ORDER BY aml.date, aml.id
                ),
                now(), %(uid)s
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_account aa ON aa.id = aml.account_id
            LEFT JOIN opening ON opening.partner_id = aml.partner_id
            WHERE {base_where}
            AND aml.date BETWEEN %(date_from)s AND %(date_to)s
            ORDER BY aml.partner_id, aml.date, aml.id
        """.format(base_where=base_where), {**params, 'uid': self.env.uid})

        # 3. Closing balance line per partner = opening + period debit/credit,
        # for every partner that appears either in the opening balance or in the period.
        cr.execute(cte_with_period + """
            INSERT INTO partner_ledger_report_line
                (wizard_id, partner_id, line_type, sequence, debit, credit, balance, create_date, create_uid)
            SELECT
                %(wizard_id)s,
                COALESCE(opening.partner_id, period.partner_id),
                'closing', 20,
                COALESCE(period.debit, 0),
                COALESCE(period.credit, 0),
                COALESCE(opening.balance, 0) + COALESCE(period.balance, 0),
                now(), %(uid)s
            FROM opening
            FULL OUTER JOIN period ON period.partner_id = opening.partner_id
        """, {**params, 'uid': self.env.uid})

        self.invalidate_recordset(['line_ids'])


class PartnerLedgerReportLine(models.TransientModel):
    _name = 'partner.ledger.report.line'
    _description = "Partner Ledger Report (SQL) Line"
    _order = 'wizard_id, partner_id, sequence, date, id'

    wizard_id = fields.Many2one('partner.ledger.report.wizard', required=True,
                                 ondelete='cascade', readonly=True)
    partner_id = fields.Many2one('res.partner', string="Partner", readonly=True)
    line_type = fields.Selection([
        ('opening', "Opening Balance"),
        ('line', "Journal Item"),
        ('closing', "Closing Balance"),
    ], string="Type", readonly=True)
    sequence = fields.Integer(readonly=True)
    date = fields.Date(readonly=True)
    move_id = fields.Many2one('account.move', string="Journal Entry", readonly=True)
    move_name = fields.Char(string="Number", readonly=True)
    journal_id = fields.Many2one('account.journal', string="Journal", readonly=True)
    ref = fields.Char(string="Reference", readonly=True)
    debit = fields.Monetary(readonly=True)
    credit = fields.Monetary(readonly=True)
    balance = fields.Monetary(readonly=True)
    currency_id = fields.Many2one('res.currency', related='wizard_id.company_id.currency_id')
