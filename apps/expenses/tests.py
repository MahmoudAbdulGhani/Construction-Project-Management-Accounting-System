"""
Tests for the ``expenses`` app -- Expense Management slice (CPMAS-33).

Organized into:
- Model tests: constraints and validation (positive amount, non-negative
  tax_amount).
- Service tests: transition_status (the status workflow).
- API tests: the same behaviors through the real DRF endpoints --
  status-change actions, read-only status enforcement, and filtering.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from accounting.models import Account, FinancialTransaction
from accounting.services import AccountingError
from clients.testing import WithClientsTableMixin
from projects.models import Project
from projects.testing import WithProjectsTableMixin
from suppliers.models import Supplier
from users.models import User
from users.testing import WithUsersTableMixin

from .models import Expense, ExpenseCategory
from .services import transition_status


class ExpensesTestBase(WithProjectsTableMixin, WithClientsTableMixin, WithUsersTableMixin, TestCase):
    """
    Expense.created_by FKs to users.User (managed=False, see
    users.testing) even though no test here sets it explicitly --
    SQLite validates an FK column's target table exists at INSERT time
    regardless of whether the value being inserted is NULL, so that
    table has to exist too, not just projects. Project also FKs to
    clients.Client (CPMAS-47), so the clients table is materialized here
    the same way the payments/accounting/invoicing suites do.

    Since CPMAS-34 (GL integration, Phase 1), the base also provisions a
    real users.User (auto-GL entries are attributed to the actor, and
    there's deliberately no anonymous fallback) and links the category to
    the seeded 5000 - Cost of Construction chart-of-accounts entry, so a
    PAID transition can actually be recognized in the ledger. "1000 -
    Cash" comes from the accounting seed migration, run in the test DB.
    """

    """Shared fixtures: a project (real, from CPMAS-47) and an expense category."""

    def setUp(self):
        self.project = Project.objects.create(
            name="DUMMY Test Project", code="DUMMY-PROJ-1", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("500000.00"),
        )
        self.user = User.objects.create(
            username="expensesgl", email="expensesgl@cedar.test", password_hash="x",
            first_name="G", last_name="L", role="ACCOUNTANT",
        )
        self.category = ExpenseCategory.objects.create(
            name="Materials", account=Account.objects.get(code="5000"),
        )

    def make_expense(self, **kwargs):
        defaults = dict(
            project=self.project, category=self.category, expense_date="2026-08-31",
            description="Cement delivery", amount=Decimal("250.00"), created_by=self.user,
        )
        defaults.update(kwargs)
        return Expense.objects.create(**defaults)


class ExpenseModelTests(ExpensesTestBase):
    def test_create_with_required_fields(self):
        expense = self.make_expense()
        self.assertEqual(expense.status, Expense.Status.PENDING)
        self.assertEqual(expense.tax_amount, Decimal("0.00"))

    def test_category_name_must_be_unique(self):
        with self.assertRaises(Exception):
            ExpenseCategory.objects.create(name="Materials")

    def test_supplier_deletion_sets_expense_supplier_to_null(self):
        supplier = Supplier.objects.create(name="ACME")
        expense = self.make_expense(supplier=supplier)
        supplier.delete()
        expense.refresh_from_db()
        self.assertIsNone(expense.supplier)


class TransitionStatusTests(ExpensesTestBase):
    def test_pending_to_approved_to_paid(self):
        expense = self.make_expense()
        transition_status(expense, Expense.Status.APPROVED)
        self.assertEqual(expense.status, Expense.Status.APPROVED)
        transition_status(expense, Expense.Status.PAID)
        self.assertEqual(expense.status, Expense.Status.PAID)

    def test_cannot_skip_to_paid(self):
        expense = self.make_expense()
        with self.assertRaises(ValidationError):
            transition_status(expense, Expense.Status.PAID)

    def test_can_reject_from_approved(self):
        expense = self.make_expense()
        transition_status(expense, Expense.Status.APPROVED)
        transition_status(expense, Expense.Status.REJECTED)
        self.assertEqual(expense.status, Expense.Status.REJECTED)

    def test_cannot_leave_rejected(self):
        expense = self.make_expense()
        transition_status(expense, Expense.Status.REJECTED)
        with self.assertRaises(ValidationError):
            transition_status(expense, Expense.Status.PENDING)


class ExpenseAPITests(ExpensesTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_expense_via_api(self):
        response = self.client.post("/api/expenses/expenses/", {
            "project": str(self.project.id), "category": str(self.category.id),
            "expense_date": "2026-08-31", "description": "Steel delivery", "amount": "1000.00",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "PENDING")

    def test_negative_amount_rejected(self):
        response = self.client.post("/api/expenses/expenses/", {
            "project": str(self.project.id), "category": str(self.category.id),
            "expense_date": "2026-08-31", "description": "Bad", "amount": "-5.00",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_status_cannot_be_set_directly_via_patch(self):
        expense = self.make_expense()
        response = self.client.patch(f"/api/expenses/expenses/{expense.id}/", {"status": "PAID"}, format="json")
        self.assertEqual(response.json()["status"], "PENDING")

    def test_approve_mark_paid_workflow(self):
        expense = self.make_expense()
        approve = self.client.post(f"/api/expenses/expenses/{expense.id}/approve/")
        self.assertEqual(approve.json()["status"], "APPROVED")
        paid = self.client.post(f"/api/expenses/expenses/{expense.id}/mark_paid/")
        self.assertEqual(paid.json()["status"], "PAID")

    def test_invalid_transition_via_api_returns_400(self):
        expense = self.make_expense()
        response = self.client.post(f"/api/expenses/expenses/{expense.id}/mark_paid/")
        self.assertEqual(response.status_code, 400)

    def test_filter_by_project(self):
        other_project = Project.objects.create(
            name="Other Project", code="DUMMY-PROJ-2", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("100000.00"),
        )
        self.make_expense()
        self.make_expense(project=other_project, description="Other project's expense")

        response = self.client.get(f"/api/expenses/expenses/?project={self.project.id}")
        self.assertEqual(response.json()["count"], 1)

    def test_filter_by_status(self):
        expense = self.make_expense()
        self.client.post(f"/api/expenses/expenses/{expense.id}/approve/")
        self.make_expense(description="Still pending")

        response = self.client.get("/api/expenses/expenses/?status=approved")
        self.assertEqual(response.json()["count"], 1)

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/expenses/expenses/")
        # 401 (not 403): with the auth ticket in place, unauthenticated
        # requests are challenged to authenticate before access is denied.
        self.assertEqual(response.status_code, 401)


class ExpenseUpdateDeleteApiTests(ExpensesTestBase):
    """
    PATCH update, reject transitions, supplier-optional creation, and
    DELETE -- the exact operations the Expenses page's create/edit dialog
    and row actions exercise (1A-2). Regresses the serializer read-only
    status, the amount/tax validators, and the viewset destroy default.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_update_expense_via_patch(self):
        expense = self.make_expense()
        response = self.client.patch(f"/api/expenses/expenses/{expense.id}/", {
            "description": "Revised cement delivery", "amount": "125.50",
            "notes": "Credit note applied", "status": "PAID",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["description"], "Revised cement delivery")
        self.assertEqual(body["amount"], "125.50")
        self.assertEqual(body["notes"], "Credit note applied")
        # status is read-only: the attempted PAID write is ignored.
        self.assertEqual(body["status"], "PENDING")

    def test_patch_rejects_non_positive_amount(self):
        expense = self.make_expense()
        response = self.client.patch(
            f"/api/expenses/expenses/{expense.id}/", {"amount": "0.00"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_patch_allows_zero_tax_amount(self):
        expense = self.make_expense()
        response = self.client.patch(
            f"/api/expenses/expenses/{expense.id}/", {"tax_amount": "0.00"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tax_amount"], "0.00")

    def test_patch_rejects_negative_tax_amount(self):
        expense = self.make_expense()
        response = self.client.patch(
            f"/api/expenses/expenses/{expense.id}/", {"tax_amount": "-1.00"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_reject_from_pending_via_api(self):
        expense = self.make_expense()
        response = self.client.post(f"/api/expenses/expenses/{expense.id}/reject/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "REJECTED")

    def test_reject_from_approved_via_api(self):
        expense = self.make_expense()
        self.client.post(f"/api/expenses/expenses/{expense.id}/approve/")
        response = self.client.post(f"/api/expenses/expenses/{expense.id}/reject/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "REJECTED")

    def test_reject_from_paid_is_invalid(self):
        expense = self.make_expense()
        self.client.post(f"/api/expenses/expenses/{expense.id}/approve/")
        self.client.post(f"/api/expenses/expenses/{expense.id}/mark_paid/")
        response = self.client.post(f"/api/expenses/expenses/{expense.id}/reject/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json())

    def test_create_without_supplier_is_allowed(self):
        response = self.client.post("/api/expenses/expenses/", {
            "project": str(self.project.id), "category": str(self.category.id),
            "expense_date": "2026-08-31", "description": "Cash purchase", "amount": "45.00",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["supplier"])
        self.assertIsNone(response.json()["supplier_name"])

    def test_delete_expense_via_api(self):
        expense = self.make_expense()
        response = self.client.delete(f"/api/expenses/expenses/{expense.id}/")
        self.assertEqual(response.status_code, 204)
        gone = self.client.get(f"/api/expenses/expenses/{expense.id}/")
        self.assertEqual(gone.status_code, 404)

    def _pay_expense(self, expense):
        """Drive an expense PENDING->APPROVED->PAID through the API actions
        (the only way status changes -- status is read-only on PATCH), so a
        GL entry is booked alongside the PAID flag."""
        self.assertEqual(self.client.post(f"/api/expenses/expenses/{expense.id}/approve/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/expenses/expenses/{expense.id}/mark_paid/").status_code, 200)

    def test_paid_expense_cannot_be_patched(self):
        expense = self.make_expense()
        self._pay_expense(expense)
        response = self.client.patch(
            f"/api/expenses/expenses/{expense.id}/",
            {"description": "Shouldn't stick", "amount": "999.00"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json())
        expense.refresh_from_db()
        self.assertNotEqual(expense.description, "Shouldn't stick")
        self.assertEqual(expense.amount, Decimal("250.00"))

    def test_paid_expense_cannot_be_deleted(self):
        expense = self.make_expense()
        self._pay_expense(expense)
        response = self.client.delete(f"/api/expenses/expenses/{expense.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Expense.objects.filter(id=expense.id).count(), 1)

    def test_unpaid_expense_can_still_be_patched_and_deleted(self):
        expense = self.make_expense()
        approved = self.client.post(f"/api/expenses/expenses/{expense.id}/approve/")
        self.assertEqual(approved.status_code, 200)
        patch = self.client.patch(
            f"/api/expenses/expenses/{expense.id}/", {"notes": "re-check"}, format="json"
        )
        self.assertEqual(patch.status_code, 200)
        delete = self.client.delete(f"/api/expenses/expenses/{expense.id}/")
        self.assertEqual(delete.status_code, 204)


class ExpenseFilterAndPaginationTests(ExpensesTestBase):
    """
    Query-construction tests for the GET /api/expenses/expenses/ list --
    the exact parameters the Expenses page (expenses.js) sends. Exercises
    date range, category, supplier, search, status casing, and the
    PageNumberPagination contract (count/next/results, 25 per page).
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def make_supplier(self, **kwargs):
        defaults = {"name": "Filtered Supply Co"}
        defaults.update(kwargs)
        return Supplier.objects.create(**defaults)

    def test_filter_by_date_range(self):
        self.make_expense(expense_date="2026-09-01", description="In range")
        self.make_expense(expense_date="2026-08-01", description="Before range")

        response = self.client.get(
            "/api/expenses/expenses/?date_from=2026-09-01&date_to=2026-09-30"
        )
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["description"], "In range")

    def test_filter_by_date_to_only(self):
        self.make_expense(expense_date="2026-08-15", description="On or before")
        self.make_expense(expense_date="2026-09-15", description="After")

        response = self.client.get("/api/expenses/expenses/?date_to=2026-08-31")
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["description"], "On or before")

    def test_filter_by_category(self):
        other = ExpenseCategory.objects.create(name="Equipment")
        self.make_expense(description="Materials spend")
        self.make_expense(category=other, description="Equipment spend")

        response = self.client.get(f"/api/expenses/expenses/?category={other.id}")
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["description"], "Equipment spend")
        self.assertEqual(body["results"][0]["category_name"], "Equipment")

    def test_filter_by_supplier(self):
        supplier = self.make_supplier(name="Atlas Crane")
        self.make_expense(supplier=supplier, description="Crane rental")
        self.make_expense(description="Cash expense, no supplier")

        response = self.client.get(f"/api/expenses/expenses/?supplier={supplier.id}")
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["description"], "Crane rental")
        self.assertEqual(body["results"][0]["supplier_name"], "Atlas Crane")

    def test_search_matches_description_project_name_and_code(self):
        self.make_expense(description="Cement delivery to site")
        self.make_expense(description="Formwork labour")
        harbor = Project.objects.create(
            name="Harbor Walls", code="HBR-77", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("100000.00"),
        )
        self.make_expense(project=harbor, description="Harbor wall stonework")

        self.assertEqual(self.client.get("/api/expenses/expenses/?search=Cement").json()["count"], 1)
        self.assertEqual(self.client.get("/api/expenses/expenses/?search=HBR-77").json()["count"], 1)
        self.assertEqual(self.client.get("/api/expenses/expenses/?search=Harbor").json()["count"], 1)

    def test_filter_by_status_mixed_case(self):
        approved = self.make_expense(description="Approved one")
        self.client.post(f"/api/expenses/expenses/{approved.id}/approve/")
        self.make_expense(description="Still pending")

        response = self.client.get("/api/expenses/expenses/?status=ApPrOvEd")
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["status"], "APPROVED")

    def test_pagination_contract_25_per_page(self):
        for i in range(26):
            self.make_expense(description=f"Bulk expense {i:02d}")

        first = self.client.get("/api/expenses/expenses/")
        body = first.json()
        self.assertEqual(body["count"], 26)
        self.assertEqual(len(body["results"]), 25)
        self.assertIsNotNone(body["next"])
        self.assertIsNone(body["previous"])
        self.assertIn("page=2", body["next"])

        second = self.client.get("/api/expenses/expenses/?page=2")
        body2 = second.json()
        self.assertEqual(len(body2["results"]), 1)
        self.assertIsNone(body2["next"])
        self.assertIsNotNone(body2["previous"])

    def test_combined_filters_and(self):
        supplier = self.make_supplier(name="Only Supplier")
        in_month = self.make_expense(
            supplier=supplier, expense_date="2026-09-10", description="September crane work",
        )

        response = self.client.get(
            f"/api/expenses/expenses/?supplier={supplier.id}"
            "&date_from=2026-09-01&date_to=2026-09-30"
        )
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["id"], str(in_month.id))


class ExpenseGLIntegrationTests(ExpensesTestBase):
    """
    Phase 1 (CPMAS-34): marking an expense PAID recognizes it in the GL --
    DR the category's chart-of-accounts entry / CR Cash (1000), for
    amount + tax_amount -- exactly once, atomically, and with a clear
    rollback when the category has no account configured.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def gl_entry_for(self, expense):
        return FinancialTransaction.objects.filter(
            source_type=FinancialTransaction.SourceType.EXPENSE, source_id=expense.id,
        ).first()

    def make_paid_expense(self, **kwargs):
        expense = self.make_expense(**kwargs)
        transition_status(expense, Expense.Status.APPROVED)
        transition_status(expense, Expense.Status.PAID)
        return expense

    def test_mark_paid_books_balanced_dr_category_cr_cash(self):
        expense = self.make_paid_expense(amount=Decimal("250.00"), tax_amount=Decimal("12.50"))

        entry = self.gl_entry_for(expense)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, FinancialTransaction.Status.POSTED)
        self.assertEqual(entry.transaction_number[:8], "GL-2026-")
        self.assertEqual(entry.source_type, FinancialTransaction.SourceType.EXPENSE)
        self.assertEqual(entry.source_id, expense.id)
        self.assertEqual(entry.project_id, expense.project_id)
        self.assertIn(expense.description, entry.description)

        total_debit = sum(line.debit for line in entry.lines.all())
        total_credit = sum(line.credit for line in entry.lines.all())
        self.assertEqual(total_debit, Decimal("262.50"))
        self.assertEqual(total_credit, Decimal("262.50"))

        debit = [line for line in entry.lines.all() if line.debit]
        credit = [line for line in entry.lines.all() if line.credit]
        self.assertEqual(len(debit), 1)
        self.assertEqual(len(credit), 1)
        self.assertEqual(debit[0].account_id, self.category.account_id)
        self.assertEqual(credit[0].account.code, "1000")

    def test_paid_expense_cannot_be_booked_twice(self):
        expense = self.make_paid_expense()
        with self.assertRaises(ValidationError):
            transition_status(expense, Expense.Status.PAID)
        self.assertEqual(
            FinancialTransaction.objects.filter(
                source_type=FinancialTransaction.SourceType.EXPENSE, source_id=expense.id,
            ).count(),
            1,
        )

    def test_rejected_expense_never_reaches_the_ledger(self):
        expense = self.make_expense()
        transition_status(expense, Expense.Status.APPROVED)
        transition_status(expense, Expense.Status.REJECTED)
        self.assertIsNone(self.gl_entry_for(expense))

    def test_category_without_account_blocks_paid_and_rolls_back(self):
        unlinked = ExpenseCategory.objects.create(name="Unlinked", account=None)
        expense = self.make_expense(category=unlinked)
        transition_status(expense, Expense.Status.APPROVED)

        with self.assertRaises(AccountingError):
            transition_status(expense, Expense.Status.PAID)

        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.APPROVED)
        self.assertIsNone(self.gl_entry_for(expense))

    def test_mark_paid_via_api_books_entry(self):
        expense = self.make_expense()
        self.assertEqual(self.client.post(f"/api/expenses/expenses/{expense.id}/approve/").status_code, 200)
        response = self.client.post(f"/api/expenses/expenses/{expense.id}/mark_paid/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PAID")
        self.assertIsNotNone(self.gl_entry_for(expense))

    def test_mark_paid_via_api_400_when_category_unlinked(self):
        unlinked = ExpenseCategory.objects.create(name="NoAccount", account=None)
        expense = self.make_expense(category=unlinked)
        self.assertEqual(self.client.post(f"/api/expenses/expenses/{expense.id}/approve/").status_code, 200)

        response = self.client.post(f"/api/expenses/expenses/{expense.id}/mark_paid/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json())
        self.assertIsNone(self.gl_entry_for(expense))
