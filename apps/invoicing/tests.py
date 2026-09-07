"""
Tests for the ``invoicing`` app -- Supplier Invoices (CPMAS-32) and
Client Invoices (CPMAS-35) slices.

Organized into:
- Service tests: compute_item_amounts (both the quantity*price derivation
  path and the flat-charge path), recalculate_invoice_totals, and
  transition_status -- for both SupplierInvoice and (the CPMAS-35
  additions) ClientInvoice.
- API tests: the same behaviors through the real DRF endpoints --
  status-change actions, DRAFT-lock enforcement, and validation rules.
"""
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import User as DjangoUser
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from clients.testing import WithClientsTableMixin
from contractors.models import Contractor
from inventory.models import Material, MaterialCategory
from projects.testing import WithProjectsTableMixin
from suppliers.models import Supplier
from taxes.models import TaxRate

from .models import (
    ClientInvoice,
    ClientInvoiceItem,
    ContractorInvoice,
    ContractorInvoiceItem,
    SupplierInvoice,
    SupplierInvoiceItem,
)
from .services import (
    compute_client_invoice_item_amounts,
    compute_contractor_item_amounts,
    compute_item_amounts,
    recalculate_client_invoice_totals,
    recalculate_contractor_invoice_totals,
    recalculate_invoice_totals,
    sync_overdue_statuses,
    transition_client_invoice_status,
    transition_contractor_invoice_status,
    transition_status,
)


class InvoicingTestBase(TestCase):
    """Shared fixtures: a supplier, a material (for line items), a tax rate."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name="ACME Building Supplies")
        category = MaterialCategory.objects.create(name="Cement")
        self.material = Material.objects.create(category=category, name="Portland Cement", sku="CEM-SI-1", unit="bag")
        self.tax = TaxRate.objects.create(name="VAT 15%", rate=Decimal("15.0000"), tax_type="VAT", effective_date="2026-01-01")

    def make_invoice(self, **kwargs):
        defaults = dict(supplier=self.supplier, invoice_number="INV-0001", invoice_date="2026-08-31")
        defaults.update(kwargs)
        return SupplierInvoice.objects.create(**defaults)


class ComputeItemAmountsTests(InvoicingTestBase):
    def test_quantity_and_price_path_derives_amounts(self):
        invoice = self.make_invoice()
        item = SupplierInvoiceItem(supplier_invoice=invoice, description="Cement", quantity=Decimal("10"), unit_price=Decimal("5.00"), tax_rate=self.tax)
        compute_item_amounts(item)
        self.assertEqual(item.tax_amount, Decimal("7.50"))
        self.assertEqual(item.total_amount, Decimal("57.50"))

    def test_flat_charge_line_keeps_caller_supplied_total(self):
        invoice = self.make_invoice()
        item = SupplierInvoiceItem(supplier_invoice=invoice, description="Delivery fee", total_amount=Decimal("25.00"), tax_amount=Decimal("2.50"))
        compute_item_amounts(item)
        # No quantity/unit_price to derive from -- caller-supplied values pass through untouched.
        self.assertEqual(item.tax_amount, Decimal("2.50"))
        self.assertEqual(item.total_amount, Decimal("25.00"))

    def test_quantity_and_price_path_overrides_a_supplied_total(self):
        # tax_amount/total_amount are writable on the serializer (needed
        # for the flat-charge path) -- prove the derivation path still
        # wins and a caller can't smuggle a bogus total past it by
        # supplying quantity/unit_price AND a mismatched total_amount.
        invoice = self.make_invoice()
        item = SupplierInvoiceItem(
            supplier_invoice=invoice, description="Cement", quantity=Decimal("10"),
            unit_price=Decimal("5.00"), tax_rate=self.tax, total_amount=Decimal("999999.00"),
        )
        compute_item_amounts(item)
        self.assertEqual(item.total_amount, Decimal("57.50"))

    def test_flat_charge_line_defaults_to_zero_if_not_supplied(self):
        invoice = self.make_invoice()
        item = SupplierInvoiceItem(supplier_invoice=invoice, description="Placeholder line")
        compute_item_amounts(item)
        self.assertEqual(item.tax_amount, Decimal("0.00"))
        self.assertEqual(item.total_amount, Decimal("0.00"))


class RecalculateInvoiceTotalsTests(InvoicingTestBase):
    def test_totals_sum_across_mixed_line_types(self):
        invoice = self.make_invoice()

        priced_item = SupplierInvoiceItem(supplier_invoice=invoice, description="Cement", quantity=Decimal("10"), unit_price=Decimal("5.00"), tax_rate=self.tax)
        compute_item_amounts(priced_item)
        priced_item.save()

        flat_item = SupplierInvoiceItem(supplier_invoice=invoice, description="Delivery fee", total_amount=Decimal("20.00"), tax_amount=Decimal("0.00"))
        compute_item_amounts(flat_item)
        flat_item.save()

        recalculate_invoice_totals(invoice)
        invoice.refresh_from_db()
        # priced: subtotal 50.00 + tax 7.50 = 57.50; flat: 20.00 + 0 = 20.00
        self.assertEqual(invoice.subtotal, Decimal("70.00"))
        self.assertEqual(invoice.tax_amount, Decimal("7.50"))
        self.assertEqual(invoice.total_amount, Decimal("77.50"))


class TransitionStatusTests(InvoicingTestBase):
    def test_draft_to_sent(self):
        invoice = self.make_invoice()
        transition_status(invoice, SupplierInvoice.Status.SENT)
        self.assertEqual(invoice.status, SupplierInvoice.Status.SENT)

    def test_cannot_skip_to_paid(self):
        invoice = self.make_invoice()
        with self.assertRaises(ValidationError):
            transition_status(invoice, SupplierInvoice.Status.PAID)

    def test_can_cancel_from_sent(self):
        invoice = self.make_invoice()
        transition_status(invoice, SupplierInvoice.Status.SENT)
        transition_status(invoice, SupplierInvoice.Status.CANCELLED)
        self.assertEqual(invoice.status, SupplierInvoice.Status.CANCELLED)

    def test_cannot_leave_cancelled(self):
        invoice = self.make_invoice()
        transition_status(invoice, SupplierInvoice.Status.CANCELLED)
        with self.assertRaises(ValidationError):
            transition_status(invoice, SupplierInvoice.Status.DRAFT)


class SupplierInvoiceAPITests(InvoicingTestBase):
    def setUp(self):
        super().setUp()
        django_user = DjangoUser.objects.create_user(username="apitester", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=django_user)

    def test_create_invoice_and_priced_item_computes_totals(self):
        create_response = self.client.post("/api/invoicing/supplier-invoices/", {
            "supplier": str(self.supplier.id), "invoice_number": "INV-API-1", "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(create_response.status_code, 201)
        invoice_id = create_response.json()["id"]

        item_response = self.client.post("/api/invoicing/supplier-invoice-items/", {
            "supplier_invoice": invoice_id, "description": "Cement", "material": str(self.material.id),
            "quantity": "4", "unit_price": "25.00",
        }, format="json")
        self.assertEqual(item_response.status_code, 201)

        invoice_response = self.client.get(f"/api/invoicing/supplier-invoices/{invoice_id}/")
        self.assertEqual(invoice_response.json()["total_amount"], "100.00")

    def test_next_number_returns_sequence_without_creating_a_row(self):
        response = self.client.get("/api/invoicing/supplier-invoices/next-number/")
        self.assertEqual(response.status_code, 200)
        number = response.json()["invoice_number"]
        self.assertRegex(number, r"^INV-\d{4}-\d{4}$")
        self.assertEqual(SupplierInvoice.objects.filter(invoice_number=number).count(), 0)

    def test_flat_charge_item_via_api(self):
        invoice = self.make_invoice(invoice_number="INV-API-2")
        response = self.client.post("/api/invoicing/supplier-invoice-items/", {
            "supplier_invoice": str(invoice.id), "description": "Delivery fee", "total_amount": "15.00",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["total_amount"], "15.00")

    def test_quantity_without_unit_price_is_rejected(self):
        invoice = self.make_invoice(invoice_number="INV-API-3")
        response = self.client.post("/api/invoicing/supplier-invoice-items/", {
            "supplier_invoice": str(invoice.id), "description": "Bad line", "quantity": "5",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_status_cannot_be_set_directly_via_patch(self):
        invoice = self.make_invoice(invoice_number="INV-API-4")
        response = self.client.patch(f"/api/invoicing/supplier-invoices/{invoice.id}/", {"status": "PAID"}, format="json")
        self.assertEqual(response.json()["status"], "DRAFT")

    def test_mark_sent_and_cancel_workflow(self):
        invoice = self.make_invoice(invoice_number="INV-API-5")
        sent = self.client.post(f"/api/invoicing/supplier-invoices/{invoice.id}/mark_sent/")
        self.assertEqual(sent.json()["status"], "SENT")
        cancelled = self.client.post(f"/api/invoicing/supplier-invoices/{invoice.id}/cancel/")
        self.assertEqual(cancelled.json()["status"], "CANCELLED")

    def test_items_locked_once_invoice_leaves_draft(self):
        invoice = self.make_invoice(invoice_number="INV-API-6")
        self.client.post(f"/api/invoicing/supplier-invoices/{invoice.id}/mark_sent/")
        response = self.client.post("/api/invoicing/supplier-invoice-items/", {
            "supplier_invoice": str(invoice.id), "description": "Too late",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_filter_by_invoice_date_range(self):
        in_range = self.make_invoice(invoice_number="INV-API-7", invoice_date="2026-08-15")
        self.make_invoice(invoice_number="INV-API-8", invoice_date="2026-01-01")

        response = self.client.get("/api/invoicing/supplier-invoices/?date_from=2026-08-01&date_to=2026-08-31")
        numbers = [i["invoice_number"] for i in response.json()["results"]]
        self.assertEqual(numbers, [in_range.invoice_number])

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/invoicing/supplier-invoices/")
        # 401 (not 403): with the auth ticket in place, unauthenticated
        # requests are challenged to authenticate before access is denied.
        self.assertEqual(response.status_code, 401)

    def test_invoice_number_is_autogenerated_when_blank(self):
        response = self.client.post("/api/invoicing/supplier-invoices/", {
            "supplier": str(self.supplier.id), "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        number = response.json()["invoice_number"]
        self.assertRegex(number, r"^INV-2026-\d{4}$")
        # A second blank creation gets the next sequence value.
        second = self.client.post("/api/invoicing/supplier-invoices/", {
            "supplier": str(self.supplier.id), "invoice_date": "2026-08-31",
        }, format="json")
        self.assertNotEqual(second.json()["invoice_number"], number)


class ClientInvoicingTestBase(WithClientsTableMixin, WithProjectsTableMixin, TestCase):
    """Shared fixtures for the ClientInvoice (CPMAS-35) test classes: a client, a tax rate."""

    def setUp(self):
        self.client_obj = Client.objects.create(name="Jane Homeowner")
        self.tax = TaxRate.objects.create(name="VAT 15%", rate=Decimal("15.0000"), tax_type="VAT", effective_date="2026-01-01")

    def make_client_invoice(self, **kwargs):
        defaults = dict(client=self.client_obj, invoice_number="CINV-0001", invoice_date="2026-08-31")
        defaults.update(kwargs)
        return ClientInvoice.objects.create(**defaults)


class ComputeClientInvoiceItemAmountsTests(ClientInvoicingTestBase):
    def test_derives_tax_and_total_from_quantity_and_price(self):
        invoice = self.make_client_invoice()
        item = ClientInvoiceItem(client_invoice=invoice, description="Tile installation", quantity=Decimal("10"), unit_price=Decimal("20.00"), tax_rate=self.tax)
        compute_client_invoice_item_amounts(item)
        # gross 200.00, tax 15% of 200.00 = 30.00
        self.assertEqual(item.tax_amount, Decimal("30.00"))
        self.assertEqual(item.total_amount, Decimal("230.00"))

    def test_discount_is_subtracted_before_tax(self):
        invoice = self.make_client_invoice()
        item = ClientInvoiceItem(client_invoice=invoice, description="Tile installation", quantity=Decimal("10"), unit_price=Decimal("20.00"), discount_amount=Decimal("50.00"), tax_rate=self.tax)
        compute_client_invoice_item_amounts(item)
        # gross 200.00 - discount 50.00 = 150.00; tax 15% of 150.00 = 22.50
        self.assertEqual(item.tax_amount, Decimal("22.50"))
        self.assertEqual(item.total_amount, Decimal("172.50"))

    def test_no_tax_rate_means_zero_tax(self):
        invoice = self.make_client_invoice()
        item = ClientInvoiceItem(client_invoice=invoice, description="Labor", quantity=Decimal("5"), unit_price=Decimal("10.00"))
        compute_client_invoice_item_amounts(item)
        self.assertEqual(item.tax_amount, Decimal("0.00"))
        self.assertEqual(item.total_amount, Decimal("50.00"))


class RecalculateClientInvoiceTotalsTests(ClientInvoicingTestBase):
    def test_totals_sum_across_lines(self):
        invoice = self.make_client_invoice()

        item_a = ClientInvoiceItem(client_invoice=invoice, description="Tiles", quantity=Decimal("10"), unit_price=Decimal("20.00"), tax_rate=self.tax)
        compute_client_invoice_item_amounts(item_a)
        item_a.save()

        item_b = ClientInvoiceItem(client_invoice=invoice, description="Labor", quantity=Decimal("5"), unit_price=Decimal("10.00"), discount_amount=Decimal("5.00"))
        compute_client_invoice_item_amounts(item_b)
        item_b.save()

        recalculate_client_invoice_totals(invoice)
        invoice.refresh_from_db()
        # item_a: gross 200.00, tax 30.00, total 230.00
        # item_b: gross 50.00, discount 5.00, no tax, total 45.00
        self.assertEqual(invoice.subtotal, Decimal("250.00"))
        self.assertEqual(invoice.discount_amount, Decimal("5.00"))
        self.assertEqual(invoice.tax_amount, Decimal("30.00"))
        self.assertEqual(invoice.total_amount, Decimal("275.00"))


class TransitionClientInvoiceStatusTests(ClientInvoicingTestBase):
    def test_draft_to_sent(self):
        invoice = self.make_client_invoice()
        transition_client_invoice_status(invoice, ClientInvoice.Status.SENT)
        self.assertEqual(invoice.status, ClientInvoice.Status.SENT)

    def test_cannot_skip_to_paid(self):
        invoice = self.make_client_invoice()
        with self.assertRaises(ValidationError):
            transition_client_invoice_status(invoice, ClientInvoice.Status.PAID)

    def test_cannot_leave_cancelled(self):
        invoice = self.make_client_invoice()
        transition_client_invoice_status(invoice, ClientInvoice.Status.CANCELLED)
        with self.assertRaises(ValidationError):
            transition_client_invoice_status(invoice, ClientInvoice.Status.DRAFT)


class ClientInvoiceAPITests(ClientInvoicingTestBase):
    def setUp(self):
        super().setUp()
        django_user = DjangoUser.objects.create_user(username="apitester2", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=django_user)

    def test_create_invoice_and_item_computes_totals(self):
        create_response = self.client.post("/api/invoicing/client-invoices/", {
            "client": str(self.client_obj.id), "invoice_number": "CINV-API-1", "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(create_response.status_code, 201)
        invoice_id = create_response.json()["id"]

        item_response = self.client.post("/api/invoicing/client-invoice-items/", {
            "client_invoice": invoice_id, "description": "Tiles", "quantity": "4", "unit_price": "25.00",
        }, format="json")
        self.assertEqual(item_response.status_code, 201)

        invoice_response = self.client.get(f"/api/invoicing/client-invoices/{invoice_id}/")
        self.assertEqual(invoice_response.json()["total_amount"], "100.00")

    def test_next_number_returns_sequence(self):
        response = self.client.get("/api/invoicing/client-invoices/next-number/")
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.json()["invoice_number"], r"^INV-\d{4}-\d{4}$")

    def test_status_cannot_be_set_directly_via_patch(self):
        invoice = self.make_client_invoice(invoice_number="CINV-API-2")
        response = self.client.patch(f"/api/invoicing/client-invoices/{invoice.id}/", {"status": "PAID"}, format="json")
        self.assertEqual(response.json()["status"], "DRAFT")

    def test_mark_sent_and_cancel_workflow(self):
        invoice = self.make_client_invoice(invoice_number="CINV-API-3")
        sent = self.client.post(f"/api/invoicing/client-invoices/{invoice.id}/mark_sent/")
        self.assertEqual(sent.json()["status"], "SENT")
        cancelled = self.client.post(f"/api/invoicing/client-invoices/{invoice.id}/cancel/")
        self.assertEqual(cancelled.json()["status"], "CANCELLED")

    def test_items_locked_once_invoice_leaves_draft(self):
        invoice = self.make_client_invoice(invoice_number="CINV-API-4")
        self.client.post(f"/api/invoicing/client-invoices/{invoice.id}/mark_sent/")
        response = self.client.post("/api/invoicing/client-invoice-items/", {
            "client_invoice": str(invoice.id), "description": "Too late", "quantity": "1", "unit_price": "1.00",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_outstanding_balance_equals_total_once_sent(self):
        invoice = self.make_client_invoice(invoice_number="CINV-API-5", total_amount=Decimal("500.00"))
        self.client.post(f"/api/invoicing/client-invoices/{invoice.id}/mark_sent/")
        response = self.client.get(f"/api/invoicing/client-invoices/{invoice.id}/")
        self.assertEqual(response.json()["outstanding_balance"], "500.00")

    def test_filter_by_invoice_date_range(self):
        in_range = self.make_client_invoice(invoice_number="CINV-API-6", invoice_date="2026-08-15")
        self.make_client_invoice(invoice_number="CINV-API-7", invoice_date="2026-01-01")

        response = self.client.get("/api/invoicing/client-invoices/?date_from=2026-08-01&date_to=2026-08-31")
        numbers = [i["invoice_number"] for i in response.json()["results"]]
        self.assertEqual(numbers, [in_range.invoice_number])

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/invoicing/client-invoices/")
        self.assertEqual(response.status_code, 401)

    def test_invoice_number_is_autogenerated_when_blank(self):
        response = self.client.post("/api/invoicing/client-invoices/", {
            "client": str(self.client_obj.id), "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertRegex(response.json()["invoice_number"], r"^INV-2026-\d{4}$")


class ContractorInvoiceServiceTests(TestCase):
    """Service-level tests for ContractorInvoice -- no contractors table
    needed because contractor_id is a plain UUID column."""

    def setUp(self):
        self.contractor_id = uuid4()
        self.tax = TaxRate.objects.create(name="VAT 15%", rate=Decimal("15.0000"), tax_type="VAT", effective_date="2026-01-01")

    def make_contractor_invoice(self, **kwargs):
        defaults = dict(contractor_id=self.contractor_id, invoice_number="COINV-0001", invoice_date="2026-08-31")
        defaults.update(kwargs)
        return ContractorInvoice.objects.create(**defaults)

    def test_quantity_price_path_derives_amounts(self):
        invoice = self.make_contractor_invoice()
        item = ContractorInvoiceItem(contractor_invoice=invoice, description="Concrete pour", quantity=Decimal("3"), unit_price=Decimal("1000.00"), tax_rate=self.tax)
        compute_contractor_item_amounts(item)
        # gross 3000.00, tax 15% = 450.00
        self.assertEqual(item.tax_amount, Decimal("450.00"))
        self.assertEqual(item.total_amount, Decimal("3450.00"))

    def test_flat_charge_line_keeps_caller_supplied_total(self):
        invoice = self.make_contractor_invoice()
        item = ContractorInvoiceItem(contractor_invoice=invoice, description="Site cleanup", total_amount=Decimal("250.00"), tax_amount=Decimal("0.00"))
        compute_contractor_item_amounts(item)
        self.assertEqual(item.total_amount, Decimal("250.00"))
        self.assertEqual(item.tax_amount, Decimal("0.00"))

    def test_recalculate_totals_sum_across_mixed_lines(self):
        invoice = self.make_contractor_invoice()
        priced = ContractorInvoiceItem(contractor_invoice=invoice, description="Concrete pour", quantity=Decimal("3"), unit_price=Decimal("1000.00"), tax_rate=self.tax)
        compute_contractor_item_amounts(priced)
        priced.save()
        flat = ContractorInvoiceItem(contractor_invoice=invoice, description="Site cleanup", total_amount=Decimal("250.00"))
        compute_contractor_item_amounts(flat)
        flat.save()

        recalculate_contractor_invoice_totals(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.subtotal, Decimal("3250.00"))
        self.assertEqual(invoice.tax_amount, Decimal("450.00"))
        self.assertEqual(invoice.total_amount, Decimal("3700.00"))

    def test_draft_to_sent(self):
        invoice = self.make_contractor_invoice()
        transition_contractor_invoice_status(invoice, ContractorInvoice.Status.SENT)
        self.assertEqual(invoice.status, ContractorInvoice.Status.SENT)

    def test_cannot_skip_to_paid(self):
        invoice = self.make_contractor_invoice()
        with self.assertRaises(ValidationError):
            transition_contractor_invoice_status(invoice, ContractorInvoice.Status.PAID)

    def test_cannot_leave_cancelled(self):
        invoice = self.make_contractor_invoice()
        transition_contractor_invoice_status(invoice, ContractorInvoice.Status.CANCELLED)
        with self.assertRaises(ValidationError):
            transition_contractor_invoice_status(invoice, ContractorInvoice.Status.DRAFT)

    def test_sync_overdue_flips_only_billed_past_due_invoices(self):
        past_due = self.make_contractor_invoice(invoice_number="COINV-OD-1", status=ContractorInvoice.Status.SENT, due_date="2026-01-01")
        partially_paid = self.make_contractor_invoice(invoice_number="COINV-OD-2", status=ContractorInvoice.Status.PARTIALLY_PAID, due_date="2026-01-01")
        future = self.make_contractor_invoice(invoice_number="COINV-OD-3", status=ContractorInvoice.Status.SENT, due_date="2999-01-01")
        draft = self.make_contractor_invoice(invoice_number="COINV-OD-4", status=ContractorInvoice.Status.DRAFT, due_date="2026-01-01")

        sync_overdue_statuses()

        past_due.refresh_from_db()
        partially_paid.refresh_from_db()
        future.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(past_due.status, ContractorInvoice.Status.OVERDUE)
        self.assertEqual(partially_paid.status, ContractorInvoice.Status.OVERDUE)
        self.assertEqual(future.status, ContractorInvoice.Status.SENT)
        self.assertEqual(draft.status, ContractorInvoice.Status.DRAFT)


class SyncOverdueStatusesTests(WithClientsTableMixin, InvoicingTestBase):
    """sync_overdue_statuses is invoked from every invoice list/detail GET
    -- prove the supplier and client invoices get the same treatment."""

    def test_supplier_and_client_past_due_billed_invoices_flip_to_overdue(self):
        supplier_overdue = self.make_invoice(invoice_number="INV-OD-5", status=SupplierInvoice.Status.SENT, due_date="2026-01-01")
        supplier_future = self.make_invoice(invoice_number="INV-OD-6", status=SupplierInvoice.Status.SENT, due_date="2999-01-01")

        client_obj = Client.objects.create(name="Jane Homeowner")
        client_overdue = ClientInvoice.objects.create(client=client_obj, invoice_number="CINV-OD-1", status=ClientInvoice.Status.SENT, invoice_date="2026-08-31", due_date="2026-01-01")

        sync_overdue_statuses()

        supplier_overdue.refresh_from_db()
        supplier_future.refresh_from_db()
        client_overdue.refresh_from_db()
        self.assertEqual(supplier_overdue.status, SupplierInvoice.Status.OVERDUE)
        self.assertEqual(supplier_future.status, SupplierInvoice.Status.SENT)
        self.assertEqual(client_overdue.status, ClientInvoice.Status.OVERDUE)


class ContractorInvoiceAPITests(TestCase):
    """API tests for contractor invoices. The serializer validates
    contractor_id against the (unmanaged) contractors view, so the table
    is created in the test DB just like the employee/contractor payment
    tests do."""

    @classmethod
    def setUpClass(cls):
        existing = connection.introspection.table_names()
        with connection.schema_editor() as editor:
            if Contractor._meta.db_table not in existing:
                editor.create_model(Contractor)
        super().setUpClass()

    def setUp(self):
        self.contractor = Contractor.objects.create(name="Atlas Concrete", status=Contractor.Status.ACTIVE, rate=Decimal("300.00"))
        self.tax = TaxRate.objects.create(name="VAT 15%", rate=Decimal("15.0000"), tax_type="VAT", effective_date="2026-01-01")
        django_user = DjangoUser.objects.create_user(username="apitester3", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=django_user)

    def test_create_invoice_and_item_computes_totals(self):
        create_response = self.client.post("/api/invoicing/contractor-invoices/", {
            "contractor_id": str(self.contractor.id), "invoice_number": "COINV-API-1", "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(create_response.status_code, 201, create_response.data)
        invoice_id = create_response.json()["id"]
        self.assertEqual(create_response.json()["contractor_name"], "Atlas Concrete")

        item_response = self.client.post("/api/invoicing/contractor-invoice-items/", {
            "contractor_invoice": invoice_id, "description": "Concrete pour", "quantity": "3", "unit_price": "1000.00",
        }, format="json")
        self.assertEqual(item_response.status_code, 201, item_response.data)

        invoice_response = self.client.get(f"/api/invoicing/contractor-invoices/{invoice_id}/")
        self.assertEqual(invoice_response.json()["total_amount"], "3000.00")
        self.assertEqual(invoice_response.json()["outstanding_balance"], "0.00")  # still DRAFT

    def test_next_number_returns_sequence(self):
        response = self.client.get("/api/invoicing/contractor-invoices/next-number/")
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.json()["invoice_number"], r"^INV-\d{4}-\d{4}$")

    def test_flat_charge_item_via_api(self):
        create_response = self.client.post("/api/invoicing/contractor-invoices/", {
            "contractor_id": str(self.contractor.id), "invoice_number": "COINV-API-2", "invoice_date": "2026-08-31",
        }, format="json")
        response = self.client.post("/api/invoicing/contractor-invoice-items/", {
            "contractor_invoice": create_response.json()["id"], "description": "Site cleanup", "total_amount": "250.00",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["total_amount"], "250.00")

    def test_contractor_must_exist(self):
        response = self.client.post("/api/invoicing/contractor-invoices/", {
            "contractor_id": str(uuid4()), "invoice_number": "COINV-API-3", "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_mark_sent_and_cancel_workflow(self):
        create_response = self.client.post("/api/invoicing/contractor-invoices/", {
            "contractor_id": str(self.contractor.id), "invoice_number": "COINV-API-4", "invoice_date": "2026-08-31",
        }, format="json")
        invoice_id = create_response.json()["id"]
        sent = self.client.post(f"/api/invoicing/contractor-invoices/{invoice_id}/mark_sent/")
        self.assertEqual(sent.json()["status"], "SENT")
        cancelled = self.client.post(f"/api/invoicing/contractor-invoices/{invoice_id}/cancel/")
        self.assertEqual(cancelled.json()["status"], "CANCELLED")

    def test_items_locked_once_invoice_leaves_draft(self):
        create_response = self.client.post("/api/invoicing/contractor-invoices/", {
            "contractor_id": str(self.contractor.id), "invoice_number": "COINV-API-5", "invoice_date": "2026-08-31",
        }, format="json")
        invoice_id = create_response.json()["id"]
        self.client.post(f"/api/invoicing/contractor-invoices/{invoice_id}/mark_sent/")
        response = self.client.post("/api/invoicing/contractor-invoice-items/", {
            "contractor_invoice": invoice_id, "description": "Too late",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_outstanding_balance_equals_total_once_sent(self):
        # total_amount is read-only through the API, so the invoices is
        # created via the model and the amount accepted at create time.
        invoice = ContractorInvoice.objects.create(
            contractor_id=self.contractor.id, invoice_number="COINV-API-6",
            invoice_date="2026-08-31", total_amount=Decimal("4000.00"),
        )
        self.client.post(f"/api/invoicing/contractor-invoices/{invoice.id}/mark_sent/")
        response = self.client.get(f"/api/invoicing/contractor-invoices/{invoice.id}/")
        self.assertEqual(response.json()["outstanding_balance"], "4000.00")

    def test_filter_by_contractor(self):
        self.client.post("/api/invoicing/contractor-invoices/", {
            "contractor_id": str(self.contractor.id), "invoice_number": "COINV-API-7", "invoice_date": "2026-08-31",
        }, format="json")
        response = self.client.get(f"/api/invoicing/contractor-invoices/?contractor={self.contractor.id}")
        self.assertEqual(len(response.json()["results"]), 1)

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/invoicing/contractor-invoices/")
        self.assertEqual(response.status_code, 401)

    def test_invoice_number_is_autogenerated_when_blank(self):
        response = self.client.post("/api/invoicing/contractor-invoices/", {
            "contractor_id": str(self.contractor.id), "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertRegex(response.json()["invoice_number"], r"^INV-2026-\d{4}$")

    def test_contractor_is_required_to_save(self):
        response = self.client.post("/api/invoicing/contractor-invoices/", {
            "invoice_date": "2026-08-31",
        }, format="json")
        self.assertEqual(response.status_code, 400)
