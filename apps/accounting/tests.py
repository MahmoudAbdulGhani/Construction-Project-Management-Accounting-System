"""
Tests for the ``accounting`` app -- Accounting / Financial Transactions
slice (CPMAS-34).

Organized into:
- Model tests: Account hierarchy/PROTECT, TransactionLine's mirrored
  CHECK-constraint validation.
- Service tests: post_transaction (the core BR 12.7 balance check) and
  void_transaction.
- API tests: the same behaviors through the real DRF endpoints --
  status-change actions, DRAFT-lock enforcement, and validation.
"""
from decimal import Decimal

from django.contrib.auth.models import User as DjangoUser
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from clients.testing import WithClientsTableMixin
from projects.testing import WithProjectsTableMixin
from users.models import User
from users.testing import WithUsersTableMixin

from .models import Account, FinancialTransaction, TransactionLine
from .services import post_transaction, transaction_totals, void_transaction


class AccountingTestBase(WithProjectsTableMixin, WithClientsTableMixin, WithUsersTableMixin, TestCase):
    """
    Shared fixtures: two GL accounts (cash, revenue) and a creator user.

    Mixes in all three managed=False table mixins: FinancialTransaction/
    TransactionLine have nullable FKs into projects and clients, and
    FinancialTransaction.created_by is a required FK into users -- under
    SQLite, an FK column's target table must exist at INSERT time even
    when the column's value is NULL, so all three tables have to exist
    even though most tests here never set project/client explicitly.
    """

    def setUp(self):
        self.cash_account = Account.objects.create(code="1000", name="Cash", account_type="Asset")
        self.revenue_account = Account.objects.create(code="4000", name="Construction Revenue", account_type="Revenue")
        self.creator = User.objects.create(
            username="creator", email="creator@example.com", password_hash="x",
            first_name="C", last_name="R", role="accountant",
        )

    def make_transaction(self, **kwargs):
        defaults = dict(
            transaction_number="TXN-0001", transaction_date="2026-08-31",
            description="Client payment received", created_by=self.creator,
        )
        defaults.update(kwargs)
        return FinancialTransaction.objects.create(**defaults)

    def add_line(self, txn, account, debit=Decimal("0"), credit=Decimal("0")):
        return TransactionLine.objects.create(transaction=txn, account=account, debit=debit, credit=credit)


class AccountModelTests(TestCase):
    def test_code_must_be_unique(self):
        Account.objects.create(code="1000", name="Cash", account_type="Asset")
        with self.assertRaises(Exception):
            Account.objects.create(code="1000", name="Duplicate", account_type="Asset")

    def test_parent_deletion_is_protected_while_children_exist(self):
        parent = Account.objects.create(code="1000", name="Assets", account_type="Asset")
        Account.objects.create(code="1010", name="Cash", account_type="Asset", parent_account=parent)
        with self.assertRaises(ProtectedError):
            parent.delete()


class TransactionTotalsTests(AccountingTestBase):
    def test_totals_sum_across_lines(self):
        txn = self.make_transaction()
        self.add_line(txn, self.cash_account, debit=Decimal("1000.00"))
        self.add_line(txn, self.revenue_account, credit=Decimal("1000.00"))
        total_debit, total_credit = transaction_totals(txn)
        self.assertEqual(total_debit, Decimal("1000.00"))
        self.assertEqual(total_credit, Decimal("1000.00"))

    def test_totals_are_zero_with_no_lines(self):
        txn = self.make_transaction()
        self.assertEqual(transaction_totals(txn), (Decimal("0.00"), Decimal("0.00")))


class PostTransactionServiceTests(AccountingTestBase):
    def test_balanced_transaction_posts_successfully(self):
        txn = self.make_transaction()
        self.add_line(txn, self.cash_account, debit=Decimal("1000.00"))
        self.add_line(txn, self.revenue_account, credit=Decimal("1000.00"))

        post_transaction(txn)
        txn.refresh_from_db()
        self.assertEqual(txn.status, FinancialTransaction.Status.POSTED)
        self.assertIsNotNone(txn.posted_at)

    def test_unbalanced_transaction_cannot_post(self):
        txn = self.make_transaction()
        self.add_line(txn, self.cash_account, debit=Decimal("1000.00"))
        self.add_line(txn, self.revenue_account, credit=Decimal("500.00"))

        with self.assertRaises(ValidationError):
            post_transaction(txn)
        txn.refresh_from_db()
        self.assertEqual(txn.status, FinancialTransaction.Status.DRAFT)

    def test_transaction_with_no_lines_cannot_post(self):
        txn = self.make_transaction()
        with self.assertRaises(ValidationError):
            post_transaction(txn)

    def test_already_posted_transaction_cannot_post_again(self):
        txn = self.make_transaction()
        self.add_line(txn, self.cash_account, debit=Decimal("100.00"))
        self.add_line(txn, self.revenue_account, credit=Decimal("100.00"))
        post_transaction(txn)

        with self.assertRaises(ValidationError):
            post_transaction(txn)


class VoidTransactionServiceTests(AccountingTestBase):
    def test_can_void_a_draft(self):
        txn = self.make_transaction()
        void_transaction(txn)
        self.assertEqual(txn.status, FinancialTransaction.Status.VOIDED)

    def test_can_void_a_posted_transaction(self):
        txn = self.make_transaction()
        self.add_line(txn, self.cash_account, debit=Decimal("100.00"))
        self.add_line(txn, self.revenue_account, credit=Decimal("100.00"))
        post_transaction(txn)

        void_transaction(txn)
        self.assertEqual(txn.status, FinancialTransaction.Status.VOIDED)

    def test_cannot_void_an_already_voided_transaction(self):
        txn = self.make_transaction()
        void_transaction(txn)
        with self.assertRaises(ValidationError):
            void_transaction(txn)


class TransactionLineModelTests(AccountingTestBase):
    def test_account_deletion_is_protected_while_lines_reference_it(self):
        txn = self.make_transaction()
        self.add_line(txn, self.cash_account, debit=Decimal("100.00"))
        with self.assertRaises(ProtectedError):
            self.cash_account.delete()

    def test_deleting_transaction_cascades_to_lines(self):
        txn = self.make_transaction()
        line = self.add_line(txn, self.cash_account, debit=Decimal("100.00"))
        txn.delete()
        self.assertFalse(TransactionLine.objects.filter(pk=line.pk).exists())


class AccountingAPITests(AccountingTestBase):
    def setUp(self):
        super().setUp()
        django_user = DjangoUser.objects.create_user(username="apitester", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=django_user)

    def test_create_account_via_api(self):
        response = self.client.post("/api/accounting/accounts/", {
            "code": "2000", "name": "Accounts Payable", "account_type": "Liability",
        }, format="json")
        self.assertEqual(response.status_code, 201)

    def test_create_transaction_and_lines_then_post(self):
        txn_response = self.client.post("/api/accounting/financial-transactions/", {
            "transaction_number": "TXN-API-1", "transaction_date": "2026-08-31",
            "description": "Client payment", "created_by": str(self.creator.id),
        }, format="json")
        self.assertEqual(txn_response.status_code, 201)
        txn_id = txn_response.json()["id"]

        self.client.post("/api/accounting/transaction-lines/", {
            "transaction": txn_id, "account": str(self.cash_account.id), "debit": "1000.00",
        }, format="json")
        self.client.post("/api/accounting/transaction-lines/", {
            "transaction": txn_id, "account": str(self.revenue_account.id), "credit": "1000.00",
        }, format="json")

        post_response = self.client.post(f"/api/accounting/financial-transactions/{txn_id}/post_entry/")
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.json()["status"], "POSTED")

    def test_posting_unbalanced_transaction_returns_400(self):
        txn = self.make_transaction(transaction_number="TXN-API-2")
        self.add_line(txn, self.cash_account, debit=Decimal("1000.00"))
        self.add_line(txn, self.revenue_account, credit=Decimal("500.00"))

        response = self.client.post(f"/api/accounting/financial-transactions/{txn.id}/post_entry/")
        self.assertEqual(response.status_code, 400)

    def test_line_with_both_debit_and_credit_rejected(self):
        txn = self.make_transaction(transaction_number="TXN-API-3")
        response = self.client.post("/api/accounting/transaction-lines/", {
            "transaction": str(txn.id), "account": str(self.cash_account.id),
            "debit": "100.00", "credit": "50.00",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_status_cannot_be_set_directly_via_patch(self):
        txn = self.make_transaction(transaction_number="TXN-API-4")
        response = self.client.patch(f"/api/accounting/financial-transactions/{txn.id}/", {"status": "POSTED"}, format="json")
        self.assertEqual(response.json()["status"], "DRAFT")

    def test_lines_locked_once_transaction_is_posted(self):
        txn = self.make_transaction(transaction_number="TXN-API-5")
        self.add_line(txn, self.cash_account, debit=Decimal("100.00"))
        self.add_line(txn, self.revenue_account, credit=Decimal("100.00"))
        self.client.post(f"/api/accounting/financial-transactions/{txn.id}/post_entry/")

        response = self.client.post("/api/accounting/transaction-lines/", {
            "transaction": str(txn.id), "account": str(self.cash_account.id), "debit": "1.00",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_void_action(self):
        txn = self.make_transaction(transaction_number="TXN-API-6")
        response = self.client.post(f"/api/accounting/financial-transactions/{txn.id}/void/")
        self.assertEqual(response.json()["status"], "VOIDED")

    def test_filter_by_transaction_date_range(self):
        in_range = self.make_transaction(transaction_number="TXN-API-7", transaction_date="2026-08-15")
        self.make_transaction(transaction_number="TXN-API-8", transaction_date="2026-01-01")

        response = self.client.get("/api/accounting/financial-transactions/?date_from=2026-08-01&date_to=2026-08-31")
        numbers = [t["transaction_number"] for t in response.json()["results"]]
        self.assertEqual(numbers, [in_range.transaction_number])

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/accounting/financial-transactions/")
        # 401 (not 403): with the auth ticket in place, unauthenticated
        # requests are challenged to authenticate before access is denied.
        self.assertEqual(response.status_code, 401)


class ReportServiceTests(AccountingTestBase):
    """Profit & Loss / revenue-expense trend calculations (server-side)."""

    def setUp(self):
        super().setUp()
        self.expense_account = Account.objects.create(
            code="5000", name="Operating Expense", account_type="Expense"
        )
        # accounts_payable is a standard expense-related balance account
        # used as the credit counter for expense lines
        self.payable_account = Account.objects.create(
            code="2000", name="Accounts Payable", account_type="Liability"
        )

    def test_profit_loss_sums_revenue_minus_expense(self):
        from .reports import profit_loss

        # Revenue entry: cash (debit 1000) / revenue (credit 1000)
        rev_txn = self.make_transaction(transaction_number="REV-1", transaction_date="2026-08-15")
        TransactionLine.objects.create(transaction=rev_txn, account=self.cash_account, debit=Decimal("1000.00"))
        TransactionLine.objects.create(transaction=rev_txn, account=self.revenue_account, credit=Decimal("1000.00"))
        post_transaction(rev_txn)

        # Expense entry: expense (debit 400) / payable (credit 400)
        exp_txn = self.make_transaction(transaction_number="EXP-1", transaction_date="2026-08-20")
        TransactionLine.objects.create(transaction=exp_txn, account=self.expense_account, debit=Decimal("400.00"))
        TransactionLine.objects.create(transaction=exp_txn, account=self.payable_account, credit=Decimal("400.00"))
        post_transaction(exp_txn)

        result = profit_loss({})
        self.assertEqual(result["revenue"]["total"], "1000.00")
        self.assertEqual(result["expenses"]["total"], "400.00")
        self.assertEqual(result["net_profit"], "600.00")

    def test_profit_loss_only_counts_posted(self):
        from .reports import profit_loss

        # Posted revenue
        rev_txn = self.make_transaction(transaction_number="REV-2", transaction_date="2026-08-15")
        TransactionLine.objects.create(transaction=rev_txn, account=self.cash_account, debit=Decimal("1000.00"))
        TransactionLine.objects.create(transaction=rev_txn, account=self.revenue_account, credit=Decimal("1000.00"))
        post_transaction(rev_txn)

        # Draft revenue (must NOT be counted)
        draft_txn = self.make_transaction(transaction_number="REV-DRAFT", transaction_date="2026-09-01")
        TransactionLine.objects.create(transaction=draft_txn, account=self.cash_account, debit=Decimal("9999.00"))
        TransactionLine.objects.create(transaction=draft_txn, account=self.revenue_account, credit=Decimal("9999.00"))
        # deliberately not posted

        # Voided revenue (must NOT be counted)
        void_txn = self.make_transaction(transaction_number="REV-VOID", transaction_date="2026-08-30")
        TransactionLine.objects.create(transaction=void_txn, account=self.cash_account, debit=Decimal("9999.00"))
        TransactionLine.objects.create(transaction=void_txn, account=self.revenue_account, credit=Decimal("9999.00"))
        void_transaction(void_txn)

        result = profit_loss({})
        self.assertEqual(result["revenue"]["total"], "1000.00")

    def test_profit_loss_date_range(self):
        from .reports import profit_loss

        in_range = self.make_transaction(transaction_number="REV-3", transaction_date="2026-08-15")
        TransactionLine.objects.create(transaction=in_range, account=self.cash_account, debit=Decimal("1000.00"))
        TransactionLine.objects.create(transaction=in_range, account=self.revenue_account, credit=Decimal("1000.00"))
        post_transaction(in_range)

        out_range = self.make_transaction(transaction_number="REV-4", transaction_date="2026-01-01")
        TransactionLine.objects.create(transaction=out_range, account=self.cash_account, debit=Decimal("500.00"))
        TransactionLine.objects.create(transaction=out_range, account=self.revenue_account, credit=Decimal("500.00"))
        post_transaction(out_range)

        result = profit_loss({"date_from": "2026-08-01", "date_to": "2026-08-31"})
        self.assertEqual(result["revenue"]["total"], "1000.00")

    def test_trend_groups_by_month(self):
        from .reports import revenue_expense_trend

        rev_txn = self.make_transaction(transaction_number="REV-5", transaction_date="2026-08-15")
        TransactionLine.objects.create(transaction=rev_txn, account=self.cash_account, debit=Decimal("1000.00"))
        TransactionLine.objects.create(transaction=rev_txn, account=self.revenue_account, credit=Decimal("1000.00"))
        post_transaction(rev_txn)

        aug_exp = self.make_transaction(transaction_number="EXP-2", transaction_date="2026-08-20")
        TransactionLine.objects.create(transaction=aug_exp, account=self.expense_account, debit=Decimal("400.00"))
        TransactionLine.objects.create(transaction=aug_exp, account=self.payable_account, credit=Decimal("400.00"))
        post_transaction(aug_exp)

        sep_exp = self.make_transaction(transaction_number="EXP-3", transaction_date="2026-09-05")
        TransactionLine.objects.create(transaction=sep_exp, account=self.expense_account, debit=Decimal("100.00"))
        TransactionLine.objects.create(transaction=sep_exp, account=self.payable_account, credit=Decimal("100.00"))
        post_transaction(sep_exp)

        series = revenue_expense_trend({})
        by_month = {row["month"]: row for row in series}
        self.assertEqual(by_month["2026-08"]["revenue"], "1000.00")
        self.assertEqual(by_month["2026-08"]["expense"], "400.00")
        self.assertEqual(by_month["2026-09"]["expense"], "100.00")


class ReportAPITests(AccountingTestBase):
    def setUp(self):
        super().setUp()
        django_user = DjangoUser.objects.create_user(username="reporter", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=django_user)
        self.expense_account = Account.objects.create(
            code="5000", name="Operating Expense", account_type="Expense"
        )
        self.payable_account = Account.objects.create(
            code="2000", name="Accounts Payable", account_type="Liability"
        )

    def _post_revenue_and_expense(self):
        rev = self.make_transaction(transaction_number="REV-API", transaction_date="2026-08-15")
        TransactionLine.objects.create(transaction=rev, account=self.cash_account, debit=Decimal("1000.00"))
        TransactionLine.objects.create(transaction=rev, account=self.revenue_account, credit=Decimal("1000.00"))
        post_transaction(rev)
        exp = self.make_transaction(transaction_number="EXP-API", transaction_date="2026-08-20")
        TransactionLine.objects.create(transaction=exp, account=self.expense_account, debit=Decimal("400.00"))
        TransactionLine.objects.create(transaction=exp, account=self.payable_account, credit=Decimal("400.00"))
        post_transaction(exp)

    def test_profit_loss_endpoint(self):
        self._post_revenue_and_expense()
        response = self.client.get("/api/accounting/reports/profit-loss/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["revenue"]["total"], "1000.00")
        self.assertEqual(data["expenses"]["total"], "400.00")
        self.assertEqual(data["net_profit"], "600.00")

    def test_trend_endpoint(self):
        self._post_revenue_and_expense()
        response = self.client.get("/api/accounting/reports/trend/")
        self.assertEqual(response.status_code, 200)
        by_month = {row["month"]: row for row in response.json()}
        self.assertEqual(by_month["2026-08"]["revenue"], "1000.00")
        self.assertEqual(by_month["2026-08"]["expense"], "400.00")

    def test_report_endpoints_require_auth(self):
        anon = APIClient()
        self.assertEqual(anon.get("/api/accounting/reports/profit-loss/").status_code, 401)
        self.assertEqual(anon.get("/api/accounting/reports/trend/").status_code, 401)


class ChartOfAccountsApiTests(AccountingTestBase):
    """Pin the ``/api/accounting/accounts/`` contract the Company settings
    "Financial settings" tab is built against: flat listing with parent
    info for the hierarchy display, search/filter, create, and status
    toggle through the existing AccountViewSet (no backend changes made
    for the tab -- the CRUD API already exists)."""

    def setUp(self):
        super().setUp()
        api_user = DjangoUser.objects.create_user(username="finsettings", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=api_user)
        self.assets = Account.objects.create(code="1001", name="Assets", account_type="Asset")
        self.cash = Account.objects.create(
            code="1010", name="Cash & Bank", account_type="Asset", parent_account=self.assets
        )

    def test_list_exposes_the_fields_the_settings_tab_needs(self):
        response = self.client.get("/api/accounting/accounts/")
        self.assertEqual(response.status_code, 200)
        rows = response.data["results"]
        row = next(r for r in rows if r["id"] == str(self.cash.id))
        self.assertEqual(row["code"], "1010")
        self.assertEqual(row["name"], "Cash & Bank")
        self.assertEqual(row["account_type"], "Asset")
        self.assertEqual(row["parent_account"], self.assets.id)
        self.assertEqual(row["parent_account_code"], "1001")
        self.assertTrue(row["is_active"])

    def test_create_account_via_api(self):
        response = self.client.post("/api/accounting/accounts/", {
            "code": "2000", "name": "Accounts Payable", "account_type": "Liability",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        created = Account.objects.get(pk=response.data["id"])
        self.assertEqual(created.account_type, "Liability")
        self.assertTrue(created.is_active)

    def test_duplicate_code_is_rejected(self):
        response = self.client.post("/api/accounting/accounts/", {
            "code": "1001", "name": "Duplicate", "account_type": "Asset",
        })
        self.assertEqual(response.status_code, 400)

    def test_missing_required_fields_are_rejected(self):
        response = self.client.post("/api/accounting/accounts/", {"code": "3000"})
        self.assertEqual(response.status_code, 400)

    def test_status_toggle_via_patch(self):
        response = self.client.patch(
            f"/api/accounting/accounts/{self.cash.id}/", {"is_active": False}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.cash.refresh_from_db()
        self.assertFalse(self.cash.is_active)

    def test_is_active_filter(self):
        self.cash.is_active = False
        self.cash.save(update_fields=["is_active"])
        response = self.client.get("/api/accounting/accounts/?is_active=false")
        self.assertEqual(response.status_code, 200)
        ids = [r["id"] for r in response.data["results"]]
        self.assertIn(str(self.cash.id), ids)

    def test_search_by_code_or_name(self):
        response = self.client.get("/api/accounting/accounts/?search=cash")
        self.assertEqual(response.status_code, 200)
        rows = response.data["results"]
        self.assertTrue(any(str(r["id"]) == str(self.cash.id) for r in rows))
        self.assertTrue(all(str(r["id"]) != str(self.assets.id) for r in rows))
