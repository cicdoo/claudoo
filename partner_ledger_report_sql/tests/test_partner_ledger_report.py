# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPartnerLedgerReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.receivable_account = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', cls.company.id)], limit=1)
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', cls.company.id)], limit=1)
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', cls.company.id)], limit=1)

    def _post_move(self, partner, date, debit, credit):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': date,
            'line_ids': [
                (0, 0, {
                    'account_id': self.receivable_account.id,
                    'partner_id': partner.id,
                    'debit': debit,
                    'credit': credit,
                }),
                (0, 0, {
                    'account_id': self.income_account.id,
                    'debit': credit,
                    'credit': debit,
                }),
            ],
        })
        move.action_post()
        return move

    def _generate_wizard(self, partner, date_from, date_to):
        wizard = self.env['partner.ledger.report.wizard'].create({
            'company_id': self.company.id,
            'date_from': date_from,
            'date_to': date_to,
            'partner_ids': [(6, 0, partner.ids)],
        })
        wizard._generate_lines()
        return wizard

    def test_opening_period_closing_balances(self):
        partner = self.env['res.partner'].create({'name': "Partner With History"})
        self._post_move(partner, '2025-06-01', 100.0, 0.0)
        self._post_move(partner, '2026-01-15', 0.0, 40.0)
        self._post_move(partner, '2026-02-01', 25.0, 0.0)

        wizard = self._generate_wizard(partner, '2026-01-01', '2026-12-31')

        opening = wizard.line_ids.filtered(lambda l: l.line_type == 'opening')
        detail = wizard.line_ids.filtered(lambda l: l.line_type == 'line').sorted('date')
        closing = wizard.line_ids.filtered(lambda l: l.line_type == 'closing')

        self.assertEqual(len(opening), 1)
        self.assertEqual(opening.balance, 100.0)

        self.assertEqual(len(detail), 2)
        self.assertEqual(detail.mapped('balance'), [60.0, 85.0])

        self.assertEqual(len(closing), 1)
        self.assertEqual(closing.debit, 25.0)
        self.assertEqual(closing.credit, 40.0)
        self.assertEqual(closing.balance, 85.0)

    def test_partner_without_prior_activity_gets_zero_opening_line(self):
        partner = self.env['res.partner'].create({'name': "Partner Without History"})
        self._post_move(partner, '2026-03-01', 30.0, 0.0)

        wizard = self._generate_wizard(partner, '2026-01-01', '2026-12-31')

        opening = wizard.line_ids.filtered(lambda l: l.line_type == 'opening')
        closing = wizard.line_ids.filtered(lambda l: l.line_type == 'closing')

        self.assertEqual(len(opening), 1)
        self.assertEqual(opening.debit, 0.0)
        self.assertEqual(opening.credit, 0.0)
        self.assertEqual(opening.balance, 0.0)

        self.assertEqual(len(closing), 1)
        self.assertEqual(closing.balance, 30.0)
