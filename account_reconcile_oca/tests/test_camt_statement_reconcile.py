# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A statement imported from the CAMT.053 sample of account_statement_import_camt
is reconciled on the reconcile screen's model: the matched line is closed against
its invoice, the others stay open."""

import unittest

from odoo.tests import Form, tagged
from odoo.tools import BinaryBytes
from odoo.tools.misc import file_path

from .test_bank_account_reconcile import TestAccountReconciliationCommon

SAMPLE = "account_statement_import_camt/tests/samples/test-camt053"
IBAN = "NL77ABNA0574908765"
VIEW = "account_reconcile_oca.bank_statement_line_form_reconcile_view"


@tagged("post_install", "-at_install")
class TestCamtStatementReconcile(TestAccountReconciliationCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        camt = cls.env["ir.module.module"].search(
            [("name", "=", "account_statement_import_camt"), ("state", "=", "installed")]
        )
        if not camt:
            raise unittest.SkipTest("account_statement_import_camt is not installed")
        eur = cls.env.ref("base.EUR")
        eur.active = True
        bank = cls.env["res.partner.bank"].create(
            {
                "account_number": IBAN,
                "partner_id": cls.company.partner_id.id,
                "company_id": cls.company.id,
            }
        )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "CAMT reconcile",
                "code": "CAMTR",
                "type": "bank",
                "bank_account_id": bank.id,
                "currency_id": eur.id,
                "company_id": cls.company.id,
                "suspense_account_id": cls.company.account_journal_suspense_account_id.id,
            }
        )
        with open(file_path(SAMPLE), "rb") as datafile:
            content = BinaryBytes(datafile.read())
        cls.env["account.statement.import"].create(
            {"statement_filename": "test-camt053", "statement_file": content}
        ).import_file_button()
        cls.statement = cls.env["account.bank.statement"].search(
            [("name", "=", "1234Test/1"), ("journal_id", "=", cls.journal.id)]
        )
        cls.lines = cls.statement.line_ids

    def _line(self, amount):
        line = self.lines.filtered(lambda ln: ln.amount == amount)
        self.assertEqual(len(line), 1)
        return line

    def _suspense(self, line):
        return line.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.journal.suspense_account_id
        )

    def test_imported_lines_start_unreconciled(self):
        self.assertEqual(len(self.lines), 4)
        for line in self.lines:
            self.assertFalse(line.is_reconciled)
            self.assertTrue(self._suspense(line))

    def test_line_is_closed_against_its_invoice_and_others_stay_open(self):
        invoice = self.create_invoice(
            currency_id=self.currency_euro_id, invoice_amount=1405.31
        )
        line = self._line(1405.31)
        with Form(line, view=VIEW) as f:
            self.assertFalse(f.can_reconcile)
            f.add_account_move_line_id = invoice.line_ids.filtered(
                lambda ml: ml.account_id.account_type == "asset_receivable"
            )
            self.assertTrue(f.can_reconcile)
        line.reconcile_bank_line()
        self.assertTrue(line.is_reconciled)
        self.assertFalse(self._suspense(line))
        self.assertEqual(invoice.amount_residual, 0.0)
        self.assertIn(invoice.payment_state, ("paid", "in_payment"))
        others = self.lines - line
        self.assertEqual(len(others), 3)
        for other in others:
            self.assertFalse(other.is_reconciled)
            self.assertTrue(self._suspense(other))

    def test_line_without_a_counterpart_cannot_be_reconciled(self):
        invoice = self.create_invoice(
            currency_id=self.currency_euro_id, invoice_amount=999.99
        )
        line = self._line(1405.31)
        with Form(line, view=VIEW) as f:
            self.assertFalse(f.can_reconcile)
        self.assertFalse(line.is_reconciled)
        self.assertTrue(self._suspense(line))
        self.assertGreater(invoice.amount_residual, 0.0)
