"""
Tests for the ``notifications`` app -- System Notifications slice
(CPMAS-22).

Organized into:
- Service tests: one class per BRD 9 alert generator, plus the
  deduplication rule shared by all of them (_notify).
- API tests: list/retrieve/create, filtering, and the mark_read/
  mark_all_read actions through the real DRF endpoints.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from clients.testing import WithClientsTableMixin
from expenses.models import Expense, ExpenseCategory
from inventory.models import Material, MaterialCategory, Stock, Warehouse
from invoicing.models import ClientInvoice, SupplierInvoice
from projects.models import Budget, BudgetItem, Project
from projects.testing import WithProjectsTableMixin
from purchasing.models import PurchaseOrder
from suppliers.models import Supplier
from users.models import Role, User
from users.testing import WithUsersTableMixin

from .models import Notification, NotificationPreference, NotificationType
from .services import (
    budget_overrun_alerts,
    deadline_approaching_alerts,
    generate_all_notifications,
    low_inventory_alerts,
    overdue_invoice_alerts,
    payment_due_alerts,
    po_awaiting_approval_alerts,
)


class NotificationsTestBase(WithUsersTableMixin, WithProjectsTableMixin, WithClientsTableMixin, TestCase):
    """Shared fixtures: an Owner and an Accountant, a client, a supplier."""

    def setUp(self):
        self.owner = User.objects.create(
            username="owner", email="owner@example.com", password_hash="x",
            first_name="O", last_name="W", role=Role.OWNER,
        )
        self.accountant = User.objects.create(
            username="accountant", email="accountant@example.com", password_hash="x",
            first_name="A", last_name="C", role=Role.ACCOUNTANT,
        )
        self.client_obj = Client.objects.create(name="Jane Homeowner")
        self.supplier = Supplier.objects.create(name="ACME Building Supplies")

    def make_project(self, **kwargs):
        defaults = dict(
            name="Tower A", code="TWR-A", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("100000.00"), status=Project.STATUS_ACTIVE,
        )
        defaults.update(kwargs)
        return Project.objects.create(**defaults)


class OverdueAndPaymentDueAlertTests(NotificationsTestBase):
    def make_client_invoice(self, **kwargs):
        defaults = dict(client=self.client_obj, invoice_number="CINV-1", invoice_date="2026-08-01", total_amount=Decimal("500.00"), status=ClientInvoice.Status.SENT)
        defaults.update(kwargs)
        return ClientInvoice.objects.create(**defaults)

    def test_overdue_invoice_notifies_accountants(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today - timedelta(days=2))
        created = overdue_invoice_alerts(today=today)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].user, self.accountant)
        self.assertEqual(created[0].notification_type, NotificationType.OVERDUE_INVOICE)

    def test_draft_invoice_is_not_overdue(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today - timedelta(days=2), status=ClientInvoice.Status.DRAFT)
        self.assertEqual(overdue_invoice_alerts(today=today), [])

    def test_paid_invoice_is_not_overdue(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today - timedelta(days=2), status=ClientInvoice.Status.PAID)
        self.assertEqual(overdue_invoice_alerts(today=today), [])

    def test_future_due_date_is_not_overdue(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today + timedelta(days=5))
        self.assertEqual(overdue_invoice_alerts(today=today), [])

    def test_payment_due_soon_notifies_accountants(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today + timedelta(days=2))
        created = payment_due_alerts(today=today, window_days=3)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].notification_type, NotificationType.PAYMENT_DUE)

    def test_payment_due_outside_window_is_not_flagged(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today + timedelta(days=10))
        self.assertEqual(payment_due_alerts(today=today, window_days=3), [])

    def test_rerunning_does_not_duplicate_unread_notification(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today - timedelta(days=2))
        overdue_invoice_alerts(today=today)
        second_run = overdue_invoice_alerts(today=today)
        self.assertEqual(second_run, [])
        self.assertEqual(Notification.objects.count(), 1)

    def test_re_flags_after_the_first_notification_is_read(self):
        today = timezone.now().date()
        self.make_client_invoice(due_date=today - timedelta(days=2))
        first = overdue_invoice_alerts(today=today)[0]
        first.is_read = True
        first.save(update_fields=['is_read'])
        second_run = overdue_invoice_alerts(today=today)
        self.assertEqual(len(second_run), 1)

    def test_covers_supplier_invoices_too(self):
        today = timezone.now().date()
        SupplierInvoice.objects.create(
            supplier=self.supplier, invoice_number="SINV-1", invoice_date="2026-08-01",
            due_date=today - timedelta(days=1), total_amount=Decimal("200.00"), status=SupplierInvoice.Status.SENT,
        )
        created = overdue_invoice_alerts(today=today)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].entity_type, 'supplier_invoice')


class LowInventoryAlertTests(NotificationsTestBase):
    def test_stock_below_minimum_notifies_owners(self):
        category = MaterialCategory.objects.create(name="Cement")
        material = Material.objects.create(category=category, name="Portland Cement", sku="CEM-1", unit="bag", minimum_stock_level=Decimal("50.000"))
        warehouse = Warehouse.objects.create(name="Main Yard")
        Stock.objects.create(warehouse=warehouse, material=material, quantity=Decimal("10.000"))

        created = low_inventory_alerts()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].user, self.owner)
        self.assertEqual(created[0].notification_type, NotificationType.LOW_INVENTORY)

    def test_stock_above_minimum_is_not_flagged(self):
        category = MaterialCategory.objects.create(name="Cement")
        material = Material.objects.create(category=category, name="Portland Cement", sku="CEM-2", unit="bag", minimum_stock_level=Decimal("50.000"))
        warehouse = Warehouse.objects.create(name="Main Yard")
        Stock.objects.create(warehouse=warehouse, material=material, quantity=Decimal("100.000"))

        self.assertEqual(low_inventory_alerts(), [])


class PurchaseOrderAlertTests(NotificationsTestBase):
    def test_submitted_po_notifies_owners(self):
        PurchaseOrder.objects.create(
            supplier=self.supplier, po_number="PO-1", order_date="2026-08-01",
            status=PurchaseOrder.Status.SUBMITTED, created_by=self.accountant,
        )
        created = po_awaiting_approval_alerts()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].user, self.owner)
        self.assertEqual(created[0].notification_type, NotificationType.PO_AWAITING_APPROVAL)

    def test_draft_po_is_not_flagged(self):
        PurchaseOrder.objects.create(
            supplier=self.supplier, po_number="PO-2", order_date="2026-08-01",
            status=PurchaseOrder.Status.DRAFT, created_by=self.accountant,
        )
        self.assertEqual(po_awaiting_approval_alerts(), [])


class BudgetOverrunAlertTests(NotificationsTestBase):
    def test_over_budget_project_notifies_owners(self):
        project = self.make_project()
        budget = Budget.objects.create(project=project, name="Baseline", total_budget=Decimal("1000.00"), status=Budget.STATUS_APPROVED)
        BudgetItem.objects.create(budget=budget, category=BudgetItem.CATEGORY_MATERIALS, budgeted_amount=Decimal("1000.00"))

        category = ExpenseCategory.objects.create(name="Materials")
        Expense.objects.create(
            project=project, category=category, expense_date="2026-08-01", description="Cement delivery",
            amount=Decimal("1500.00"), status=Expense.Status.APPROVED,
        )

        created = budget_overrun_alerts()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].user, self.owner)
        self.assertEqual(created[0].notification_type, NotificationType.BUDGET_OVERRUN)

    def test_within_budget_project_is_not_flagged(self):
        project = self.make_project()
        budget = Budget.objects.create(project=project, name="Baseline", total_budget=Decimal("1000.00"), status=Budget.STATUS_APPROVED)
        BudgetItem.objects.create(budget=budget, category=BudgetItem.CATEGORY_MATERIALS, budgeted_amount=Decimal("1000.00"))

        category = ExpenseCategory.objects.create(name="Materials")
        Expense.objects.create(
            project=project, category=category, expense_date="2026-08-01", description="Cement delivery",
            amount=Decimal("200.00"), status=Expense.Status.APPROVED,
        )

        self.assertEqual(budget_overrun_alerts(), [])

    def test_project_with_no_budget_is_skipped(self):
        self.make_project(code="TWR-NOBUDGET")
        self.assertEqual(budget_overrun_alerts(), [])


class DeadlineApproachingAlertTests(NotificationsTestBase):
    def test_deadline_within_window_notifies_owners(self):
        today = timezone.now().date()
        self.make_project(expected_completion_date=today + timedelta(days=3))
        created = deadline_approaching_alerts(today=today, window_days=7)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].notification_type, NotificationType.DEADLINE_APPROACHING)

    def test_deadline_outside_window_is_not_flagged(self):
        today = timezone.now().date()
        self.make_project(code="TWR-FAR", expected_completion_date=today + timedelta(days=30))
        self.assertEqual(deadline_approaching_alerts(today=today, window_days=7), [])

    def test_non_active_project_is_not_flagged(self):
        today = timezone.now().date()
        self.make_project(code="TWR-HOLD", status=Project.STATUS_ON_HOLD, expected_completion_date=today + timedelta(days=3))
        self.assertEqual(deadline_approaching_alerts(today=today, window_days=7), [])


class GenerateAllNotificationsTests(NotificationsTestBase):
    def test_runs_every_generator_without_error(self):
        # Smoke test: an empty database shouldn't raise, and should produce no alerts.
        self.assertEqual(generate_all_notifications(), [])


class NotificationAPITests(NotificationsTestBase):
    def setUp(self):
        super().setUp()
        django_user = DjangoUser.objects.create_user(username="apitester5", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=django_user)

    def test_create_and_list_notification(self):
        response = self.client.post("/api/notifications/notifications/", {
            "user": str(self.owner.id), "notification_type": "LOW_INVENTORY",
            "title": "Low stock", "message": "Cement is low.",
        }, format="json")
        self.assertEqual(response.status_code, 201)

        list_response = self.client.get(f"/api/notifications/notifications/?user={self.owner.id}")
        self.assertEqual(list_response.json()["count"], 1)

    def test_mark_read(self):
        notification = Notification.objects.create(user=self.owner, notification_type="LOW_INVENTORY", title="t", message="m")
        response = self.client.post(f"/api/notifications/notifications/{notification.id}/mark_read/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_read"])
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_is_read_cannot_be_set_directly_via_create(self):
        response = self.client.post("/api/notifications/notifications/", {
            "user": str(self.owner.id), "notification_type": "LOW_INVENTORY",
            "title": "t", "message": "m", "is_read": True,
        }, format="json")
        self.assertFalse(response.json()["is_read"])

    def test_mark_all_read_scoped_to_filtered_queryset(self):
        Notification.objects.create(user=self.owner, notification_type="LOW_INVENTORY", title="t1", message="m1")
        Notification.objects.create(user=self.accountant, notification_type="OVERDUE_INVOICE", title="t2", message="m2")

        response = self.client.post(f"/api/notifications/notifications/mark_all_read/?user={self.owner.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["marked_read"], 1)

        self.assertTrue(Notification.objects.get(user=self.owner).is_read)
        self.assertFalse(Notification.objects.get(user=self.accountant).is_read)

    def test_filter_by_is_read(self):
        n1 = Notification.objects.create(user=self.owner, notification_type="LOW_INVENTORY", title="t1", message="m1")
        Notification.objects.create(user=self.owner, notification_type="LOW_INVENTORY", title="t2", message="m2", is_read=True)

        response = self.client.get("/api/notifications/notifications/?is_read=false")
        ids = [r["id"] for r in response.json()["results"]]
        self.assertEqual(ids, [str(n1.id)])

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/notifications/notifications/")
        self.assertEqual(response.status_code, 401)


class NotificationPreferenceAPITests(NotificationsTestBase):
    """Owner-only GET/PATCH of the Notifications-settings preferences."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def _accountant_client(self):
        client = APIClient()
        client.force_authenticate(user=self.accountant)
        return client

    def test_get_returns_all_six_types_with_metadata(self):
        response = self.client.get("/api/notifications/preferences/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data.keys()), {
            "OVERDUE_INVOICE", "PAYMENT_DUE", "LOW_INVENTORY",
            "PO_AWAITING_APPROVAL", "BUDGET_OVERRUN", "DEADLINE_APPROACHING",
        })
        line = data["PAYMENT_DUE"]
        self.assertTrue(line["is_enabled"])
        self.assertEqual(line["role"], "ACCOUNTANT")
        self.assertEqual(line["label"], "Payment Due")

    def test_get_creates_rows_lazily(self):
        self.assertEqual(NotificationPreference.objects.count(), 0)
        self.client.get("/api/notifications/preferences/")
        self.assertEqual(NotificationPreference.objects.count(), 6)

    def test_patch_updates_only_provided_type(self):
        response = self.client.patch(
            "/api/notifications/preferences/",
            {"LOW_INVENTORY": {"is_enabled": False}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["LOW_INVENTORY"]["is_enabled"])
        # Other preferences untouched.
        self.assertTrue(response.json()["PAYMENT_DUE"]["is_enabled"])

    def test_patch_sets_window_days(self):
        response = self.client.patch(
            "/api/notifications/preferences/",
            {"DEADLINE_APPROACHING": {"is_enabled": True, "window_days": 14}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["DEADLINE_APPROACHING"]["window_days"], 14)

    def test_owner_only(self):
        response = self._accountant_client().get("/api/notifications/preferences/")
        self.assertEqual(response.status_code, 403)

    def test_anonymous_request_is_rejected(self):
        response = APIClient().get("/api/notifications/preferences/")
        self.assertEqual(response.status_code, 401)


class NotificationPreferenceServiceTests(NotificationsTestBase):
    """The alert generators honour the stored preferences."""

    def make_client_invoice(self, **kwargs):
        defaults = dict(client=self.client_obj, invoice_number="CINV-1", invoice_date="2026-08-01", total_amount=Decimal("500.00"), status=ClientInvoice.Status.SENT)
        defaults.update(kwargs)
        return ClientInvoice.objects.create(**defaults)

    def test_disabled_type_produces_no_alerts(self):
        NotificationPreference.objects.create(
            notification_type=NotificationType.LOW_INVENTORY,
            is_enabled=False,
        )
        self.assertEqual(low_inventory_alerts(), [])

    def test_enabled_type_still_generates(self):
        # Default (no row) already works; ensure an explicit enabled row does too.
        NotificationPreference.objects.create(
            notification_type=NotificationType.LOW_INVENTORY,
            is_enabled=True,
        )
        category = MaterialCategory.objects.create(name="Cement")
        material = Material.objects.create(category=category, name="Portland Cement", sku="CEM-1", unit="bag", minimum_stock_level=Decimal("50.000"))
        warehouse = Warehouse.objects.create(name="Main Yard")
        Stock.objects.create(warehouse=warehouse, material=material, quantity=Decimal("10.000"))
        created = low_inventory_alerts()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].notification_type, NotificationType.LOW_INVENTORY)

    def test_window_override_expands_payment_due_horizon(self):
        today = timezone.now().date()
        NotificationPreference.objects.create(
            notification_type=NotificationType.PAYMENT_DUE,
            is_enabled=True,
            window_days=10,
        )
        # Invoice due in 8 days: inside the configured window, outside the default 3.
        self.make_client_invoice(due_date=today + timedelta(days=8))
        created = payment_due_alerts(today=today)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].notification_type, NotificationType.PAYMENT_DUE)

    def test_generate_all_respects_disabled(self):
        NotificationPreference.objects.create(
            notification_type=NotificationType.PAYMENT_DUE,
            is_enabled=False,
        )
        created = generate_all_notifications()
        self.assertFalse(
            any(n.notification_type == NotificationType.PAYMENT_DUE for n in created)
        )
