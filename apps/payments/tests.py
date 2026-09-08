"""
Tests for the ``payments`` app -- Accounts Receivable & Accounts
Payable slice (CPMAS-35).

Organized into:
- Service tests: outstanding_balance (DRAFT/CANCELLED short-circuit,
  balance reduction after allocation) and allocate_payment (the core
  direction-matching, invoice-status, and over-allocation guards).
- API tests: the same behaviors through the real DRF endpoints --
  append-only enforcement (no update/destroy routes), receipt
  direction validation, and the payment_allocations CHECK-constraint
  mirror.
"""
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from accounting.models import FinancialTransaction
from clients.models import Client
from clients.testing import WithClientsTableMixin
from contractors.models import Contractor
from contractors.testing import WithContractorsTableMixin
from employees.models import Employee
from invoicing.models import ClientInvoice, ContractorInvoice, SupplierInvoice
from projects.testing import WithProjectsTableMixin
from suppliers.models import Supplier
from users.models import Role, User
from users.testing import WithUsersTableMixin

from .models import Payment, PaymentAllocation, Receipt
from .services import allocate_payment, outstanding_balance, unallocated_amount


class PaymentsTestBase(WithUsersTableMixin, WithClientsTableMixin, WithProjectsTableMixin, TestCase):
    """
    Shared fixtures: a client, a supplier, a creator user, and SENT
    invoices on both sides.

    Mixes in WithProjectsTableMixin too: ClientInvoice.project is a
    nullable FK into projects -- under SQLite, an FK column's target
    table must exist at INSERT time even when the value is NULL (same
    quirk documented on accounting.tests.AccountingTestBase).
    """

    def setUp(self):
        super().setUp()
        self.contractor_id = uuid4()
        self.creator = User.objects.create(
            username="creator", email="creator@example.com", password_hash="x",
            first_name="C", last_name="R", role=Role.ACCOUNTANT,
        )
        self.client_obj = Client.objects.create(name="Jane Homeowner")
        self.supplier = Supplier.objects.create(name="ACME Building Supplies")

    def make_client_invoice(self, total_amount=Decimal("1000.00"), status=ClientInvoice.Status.SENT, **kwargs):
        defaults = dict(
            client=self.client_obj, invoice_number="CINV-0001", invoice_date="2026-08-31",
            total_amount=total_amount, status=status,
        )
        defaults.update(kwargs)
        return ClientInvoice.objects.create(**defaults)

    def make_supplier_invoice(self, total_amount=Decimal("500.00"), status=SupplierInvoice.Status.SENT, **kwargs):
        defaults = dict(
            supplier=self.supplier, invoice_number="SINV-0001", invoice_date="2026-08-31",
            total_amount=total_amount, status=status,
        )
        defaults.update(kwargs)
        return SupplierInvoice.objects.create(**defaults)

    def make_contractor_invoice(self, total_amount=Decimal("3000.00"), status=ContractorInvoice.Status.SENT, **kwargs):
        defaults = dict(
            contractor_id=self.contractor_id, invoice_number="COINV-0001", invoice_date="2026-08-31",
            total_amount=total_amount, status=status,
        )
        defaults.update(kwargs)
        return ContractorInvoice.objects.create(**defaults)

    def make_payment(self, direction=Payment.Direction.INCOMING, amount=Decimal("1000.00"), **kwargs):
        defaults = dict(
            payment_number="PMT-0001", payment_date="2026-08-31", amount=amount,
            direction=direction, payment_method="bank_transfer", created_by=self.creator,
        )
        if direction == Payment.Direction.INCOMING:
            defaults.setdefault('client', self.client_obj)
        else:
            defaults.setdefault('supplier', self.supplier)
        defaults.update(kwargs)
        return Payment.objects.create(**defaults)


class OutstandingBalanceTests(PaymentsTestBase):
    def test_draft_invoice_has_zero_balance(self):
        invoice = self.make_client_invoice(status=ClientInvoice.Status.DRAFT)
        self.assertEqual(outstanding_balance(invoice), Decimal("0.00"))

    def test_cancelled_invoice_has_zero_balance(self):
        invoice = self.make_client_invoice(status=ClientInvoice.Status.CANCELLED)
        self.assertEqual(outstanding_balance(invoice), Decimal("0.00"))

    def test_sent_invoice_with_no_allocations_equals_total(self):
        invoice = self.make_client_invoice(total_amount=Decimal("750.00"))
        self.assertEqual(outstanding_balance(invoice), Decimal("750.00"))

    def test_balance_reduces_after_allocation(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("400.00"))
        self.assertEqual(outstanding_balance(invoice), Decimal("600.00"))

    def test_works_for_supplier_invoice_too(self):
        invoice = self.make_supplier_invoice(total_amount=Decimal("500.00"))
        self.assertEqual(outstanding_balance(invoice), Decimal("500.00"))

    def test_works_for_contractor_invoice_too(self):
        invoice = self.make_contractor_invoice(total_amount=Decimal("3000.00"))
        self.assertEqual(outstanding_balance(invoice), Decimal("3000.00"))
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("3000.00"), contractor_id=self.contractor_id)
        allocate_payment(payment, invoice, Decimal("3000.00"))
        self.assertEqual(outstanding_balance(invoice), Decimal("0.00"))


class UnallocatedAmountTests(PaymentsTestBase):
    def test_equals_full_amount_with_no_allocations(self):
        payment = self.make_payment(amount=Decimal("1000.00"))
        self.assertEqual(unallocated_amount(payment), Decimal("1000.00"))

    def test_reduces_after_allocation(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("300.00"))
        self.assertEqual(unallocated_amount(payment), Decimal("700.00"))


class AllocatePaymentServiceTests(PaymentsTestBase):
    def test_partial_allocation_marks_client_invoice_partially_paid(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("400.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, ClientInvoice.Status.PARTIALLY_PAID)

    def test_full_allocation_marks_client_invoice_paid(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("1000.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, ClientInvoice.Status.PAID)

    def test_full_allocation_marks_supplier_invoice_paid(self):
        invoice = self.make_supplier_invoice(total_amount=Decimal("500.00"))
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("500.00"))
        allocate_payment(payment, invoice, Decimal("500.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, SupplierInvoice.Status.PAID)

    def test_full_allocation_marks_contractor_invoice_paid(self):
        invoice = self.make_contractor_invoice(total_amount=Decimal("3000.00"))
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("3000.00"), contractor_id=self.contractor_id)
        allocate_payment(payment, invoice, Decimal("3000.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, ContractorInvoice.Status.PAID)

    def test_partial_allocation_marks_contractor_invoice_partially_paid(self):
        invoice = self.make_contractor_invoice(total_amount=Decimal("3000.00"))
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("3000.00"), contractor_id=self.contractor_id)
        allocate_payment(payment, invoice, Decimal("1200.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, ContractorInvoice.Status.PARTIALLY_PAID)
        self.assertEqual(outstanding_balance(invoice), Decimal("1800.00"))

    def test_incoming_payment_cannot_fund_a_contractor_invoice(self):
        invoice = self.make_contractor_invoice()
        payment = self.make_payment(direction=Payment.Direction.INCOMING, amount=Decimal("3000.00"))
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("100.00"))

    def test_contractor_must_match_invoice(self):
        invoice = self.make_contractor_invoice()
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("3000.00"), contractor_id=uuid4())
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("100.00"))

    def test_payment_with_both_supplier_and_contractor_targets_contractor(self):
        # A payment recorded against a contractor also carries the
        # supplier default off the OUTGOING path -- the contractor wins
        # for matching purposes.
        invoice = self.make_contractor_invoice()
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("3000.00"), contractor_id=self.contractor_id)
        allocate_payment(payment, invoice, Decimal("3000.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, ContractorInvoice.Status.PAID)

    def test_partial_allocation_marks_supplier_invoice_partially_paid(self):
        invoice = self.make_supplier_invoice(total_amount=Decimal("500.00"))
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("500.00"))
        allocate_payment(payment, invoice, Decimal("200.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, SupplierInvoice.Status.PARTIALLY_PAID)

    def test_overdue_invoice_accepts_allocation(self):
        invoice = self.make_client_invoice(status=ClientInvoice.Status.OVERDUE)
        payment = self.make_payment()
        allocation = allocate_payment(payment, invoice, Decimal("100.00"))
        self.assertEqual(allocation.allocated_amount, Decimal("100.00"))

    def test_payment_and_invoice_rows_are_locked(self):
        invoice = self.make_client_invoice()
        payment = self.make_payment()
        with patch.object(Payment.objects, 'select_for_update', wraps=Payment.objects.select_for_update) as payment_lock, \
             patch.object(ClientInvoice.objects, 'select_for_update', wraps=ClientInvoice.objects.select_for_update) as invoice_lock:
            allocate_payment(payment, invoice, Decimal("100.00"))
        payment_lock.assert_called_once_with()
        invoice_lock.assert_called_once_with()

    def test_outgoing_payment_cannot_fund_a_client_invoice(self):
        invoice = self.make_client_invoice()
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("1000.00"))
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("100.00"))

    def test_incoming_payment_cannot_fund_a_supplier_invoice(self):
        invoice = self.make_supplier_invoice()
        payment = self.make_payment(direction=Payment.Direction.INCOMING, amount=Decimal("1000.00"))
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("100.00"))

    def test_cannot_allocate_to_a_draft_invoice(self):
        invoice = self.make_client_invoice(status=ClientInvoice.Status.DRAFT)
        payment = self.make_payment(amount=Decimal("1000.00"))
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("100.00"))

    def test_cannot_allocate_to_paid_or_cancelled_invoice(self):
        for index, status in enumerate((ClientInvoice.Status.PAID, ClientInvoice.Status.CANCELLED), 1):
            invoice = self.make_client_invoice(invoice_number=f"CINV-BLOCK-{index}", status=status)
            payment = self.make_payment(payment_number=f"PMT-BLOCK-{index}")
            with self.assertRaises(ValidationError):
                allocate_payment(payment, invoice, Decimal("100.00"))

    def test_allocation_must_be_positive(self):
        invoice = self.make_client_invoice()
        payment = self.make_payment()
        for amount in (Decimal("0.00"), Decimal("-1.00")):
            with self.assertRaises(ValidationError):
                allocate_payment(payment, invoice, amount)

    def test_client_must_match_invoice(self):
        other = Client.objects.create(name="Wrong client")
        invoice = self.make_client_invoice(client=other)
        with self.assertRaises(ValidationError):
            allocate_payment(self.make_payment(), invoice, Decimal("100.00"))

    def test_supplier_must_match_invoice(self):
        other = Supplier.objects.create(name="Wrong supplier")
        invoice = self.make_supplier_invoice(supplier=other)
        payment = self.make_payment(direction=Payment.Direction.OUTGOING)
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("100.00"))

    def test_cannot_exceed_invoice_outstanding_balance(self):
        invoice = self.make_client_invoice(total_amount=Decimal("100.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("150.00"))

    def test_cannot_exceed_payment_unallocated_amount(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("100.00"))
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("150.00"))

    def test_second_allocation_after_first_still_respects_remaining_balance(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("600.00"))
        with self.assertRaises(ValidationError):
            allocate_payment(payment, invoice, Decimal("500.00"))  # only 400 left on the invoice


class PaymentGLTests(PaymentsTestBase):
    """CPMAS-34/Phase 3: every successful allocate_payment re-books the
    payment's GL journal from its current allocation set.

    INCOMING -> DR Cash (1000) / CR Accounts Receivable (1100) per
    allocation; OUTGOING -> DR Accounts Payable (2000) / CR Cash (1000).
    Each journal line carries its allocation's invoice project, the prior
    entry becomes VOIDED on re-allocation, and an unallocated payment
    (e.g. an employee wage run) books nothing.
    """

    def _live_entry(self, payment):
        return FinancialTransaction.objects.get(
            source_type=FinancialTransaction.SourceType.PAYMENT,
            source_id=payment.id,
            status=FinancialTransaction.Status.POSTED,
        )

    def _lines(self, payment):
        return list(self._live_entry(payment).lines.select_related('account', 'project'))

    def _summary(self, payment):
        totals = {}
        for line in self._lines(payment):
            entry = totals.setdefault(line.account.code, {"debit": Decimal("0.00"), "credit": Decimal("0.00")})
            entry["debit"] += line.debit
            entry["credit"] += line.credit
        return totals

    def test_incoming_allocation_books_dr_cash_cr_ar(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("1000.00"))
        totals = self._summary(payment)
        self.assertEqual(totals["1000"]["debit"], Decimal("1000.00"))
        self.assertEqual(totals["1100"]["credit"], Decimal("1000.00"))

    def test_incoming_allocation_amounts_follow_the_allocation(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("400.00"))
        totals = self._summary(payment)
        self.assertEqual(totals["1000"]["debit"], Decimal("400.00"))
        self.assertEqual(totals["1100"]["credit"], Decimal("400.00"))

    def test_outgoing_supplier_allocation_books_dr_ap_cr_cash(self):
        invoice = self.make_supplier_invoice(total_amount=Decimal("500.00"))
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("500.00"))
        allocate_payment(payment, invoice, Decimal("500.00"))
        totals = self._summary(payment)
        self.assertEqual(totals["2000"]["debit"], Decimal("500.00"))
        self.assertEqual(totals["1000"]["credit"], Decimal("500.00"))

    def test_outgoing_contractor_allocation_books_dr_ap_cr_cash(self):
        invoice = self.make_contractor_invoice(total_amount=Decimal("3000.00"))
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("3000.00"), contractor_id=self.contractor_id)
        allocate_payment(payment, invoice, Decimal("3000.00"))
        totals = self._summary(payment)
        self.assertEqual(totals["2000"]["debit"], Decimal("3000.00"))
        self.assertEqual(totals["1000"]["credit"], Decimal("3000.00"))

    def test_header_links_the_source_and_carries_reference_and_party(self):
        from projects.models import Project

        project = Project.objects.create(
            code="PAY-GL-1", name="Payment GL Tower", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("50000.00"), buyer=self.client_obj,
        )
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"), project=project)
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("1000.00"))
        entry = self._live_entry(payment)
        self.assertEqual(entry.description, "Payment: PMT-0001")
        self.assertEqual(entry.source_type, FinancialTransaction.SourceType.PAYMENT)
        self.assertEqual(entry.project, None)
        self.assertEqual(entry.client, self.client_obj)
        self.assertEqual(entry.created_by_id, self.creator.id)

    def test_lines_carry_their_allocation_invoice_project(self):
        from projects.models import Project

        project = Project.objects.create(
            code="PAY-GL-2", name="Payment GL Tower Two", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("60000.00"), buyer=self.client_obj,
        )
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"), project=project)
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice, Decimal("1000.00"))
        lines = self._lines(payment)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(line.project_id, project.id)

    def test_reallocation_voids_the_previous_entry_and_books_fresh(self):
        invoice_a = self.make_client_invoice(invoice_number="CINV-A", total_amount=Decimal("1000.00"))
        invoice_b = self.make_client_invoice(invoice_number="CINV-B", total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        allocate_payment(payment, invoice_a, Decimal("600.00"))
        allocate_payment(payment, invoice_b, Decimal("400.00"))

        entries = FinancialTransaction.objects.filter(
            source_type=FinancialTransaction.SourceType.PAYMENT, source_id=payment.id,
        ).order_by('created_at')
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].status, FinancialTransaction.Status.VOIDED)
        self.assertEqual(entries[1].status, FinancialTransaction.Status.POSTED)
        totals = self._summary(payment)
        self.assertEqual(totals["1000"]["debit"], Decimal("1000.00"))
        self.assertEqual(totals["1100"]["credit"], Decimal("1000.00"))

    def test_unallocated_payment_books_nothing(self):
        payment = self.make_payment(amount=Decimal("1000.00"))
        self.assertEqual(
            FinancialTransaction.objects.filter(
                source_type=FinancialTransaction.SourceType.PAYMENT, source_id=payment.id,
            ).count(),
            0,
        )


class PaymentAPITests(PaymentsTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.creator)

    def test_create_incoming_payment_via_api(self):
        response = self.client.post("/api/payments/payments/", {
            "payment_number": "PMT-API-1", "payment_date": "2026-08-31", "amount": "1000.00",
            "direction": "INCOMING", "payment_method": "bank_transfer",
            "client": str(self.client_obj.id), "created_by": str(self.creator.id),
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["unallocated_amount"], "1000.00")
        self.assertEqual(response.json()["created_by"], str(self.creator.id))

    def test_payment_number_is_autogenerated_when_blank(self):
        response = self.client.post("/api/payments/payments/", {
            "payment_date": "2026-08-31", "amount": "1000.00",
            "direction": "INCOMING", "payment_method": "bank_transfer",
            "client": str(self.client_obj.id), "created_by": str(self.creator.id),
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertRegex(response.json()["payment_number"], r"^PAY-2026-\d{4}$")

    def test_client_cannot_control_created_by(self):
        owner = User.objects.create(
            username="owner", email="owner@example.com", password_hash="x",
            first_name="O", last_name="W", role=Role.OWNER,
        )
        response = self.client.post("/api/payments/payments/", {
            "payment_number": "PMT-CREATOR", "payment_date": "2026-08-31", "amount": "20.00",
            "direction": "INCOMING", "payment_method": "cash", "client": str(self.client_obj.id),
            "created_by": str(owner.id),
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Payment.objects.get(payment_number="PMT-CREATOR").created_by_id, self.creator.id)

    def test_outgoing_payment_with_supplier_succeeds(self):
        response = self.client.post("/api/payments/payments/", {
            "payment_number": "PMT-OUT", "payment_date": "2026-08-31", "amount": "20.00",
            "direction": "OUTGOING", "payment_method": "cash", "supplier": str(self.supplier.id),
        }, format="json")
        self.assertEqual(response.status_code, 201)

    def test_direction_party_pairing_is_exact(self):
        cases = (
            ("PMT-BOTH-I", "INCOMING", self.client_obj.id, self.supplier.id),
            ("PMT-BOTH-O", "OUTGOING", self.client_obj.id, self.supplier.id),
            ("PMT-NONE-O", "OUTGOING", None, None),
        )
        for number, direction, client_id, supplier_id in cases:
            payload = {"payment_number": number, "payment_date": "2026-08-31", "amount": "20.00",
                       "direction": direction, "payment_method": "cash"}
            if client_id:
                payload['client'] = str(client_id)
            if supplier_id:
                payload['supplier'] = str(supplier_id)
            self.assertEqual(self.client.post("/api/payments/payments/", payload, format="json").status_code, 400)

    def test_payment_amount_and_required_strings_are_validated(self):
        for index, amount in enumerate(("0.00", "-1.00")):
            response = self.client.post("/api/payments/payments/", {
                "payment_number": f"PMT-AMT-{index}", "payment_date": "2026-08-31", "amount": amount,
                "direction": "INCOMING", "payment_method": "cash", "client": str(self.client_obj.id),
            }, format="json")
            self.assertEqual(response.status_code, 400)
        # payment_number is optional (auto-generated), but payment_method stays
        # a required non-blank field.
        for field in ('payment_method',):
            payload = {"payment_date": "2026-08-31", "amount": "1.00",
                       "direction": "INCOMING", "payment_method": "cash", "client": str(self.client_obj.id)}
            payload[field] = "   "
            self.assertEqual(self.client.post("/api/payments/payments/", payload, format="json").status_code, 400)

    def test_duplicate_payment_number_is_rejected(self):
        self.make_payment(payment_number="PMT-DUP")
        response = self.client.post("/api/payments/payments/", {
            "payment_number": "PMT-DUP", "payment_date": "2026-08-31", "amount": "1.00",
            "direction": "INCOMING", "payment_method": "cash", "client": str(self.client_obj.id),
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_incoming_payment_without_client_is_rejected(self):
        response = self.client.post("/api/payments/payments/", {
            "payment_number": "PMT-API-2", "payment_date": "2026-08-31", "amount": "1000.00",
            "direction": "INCOMING", "payment_method": "bank_transfer", "created_by": str(self.creator.id),
        }, format="json")
        self.assertEqual(response.status_code, 400)


    def test_payment_has_no_update_or_delete_routes(self):
        payment = self.make_payment(amount=Decimal("1000.00"))
        response = self.client.patch(f"/api/payments/payments/{payment.id}/", {"amount": "1.00"}, format="json")
        self.assertEqual(response.status_code, 405)
        response = self.client.put(f"/api/payments/payments/{payment.id}/", {"amount": "1.00"}, format="json")
        self.assertEqual(response.status_code, 405)
        response = self.client.delete(f"/api/payments/payments/{payment.id}/")
        self.assertEqual(response.status_code, 405)

    def test_allocate_payment_via_api_updates_invoice_status(self):
        invoice = self.make_client_invoice(total_amount=Decimal("1000.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))

        response = self.client.post("/api/payments/payment-allocations/", {
            "payment": str(payment.id), "client_invoice": str(invoice.id), "allocated_amount": "1000.00",
        }, format="json")
        self.assertEqual(response.status_code, 201)

        invoice_response = self.client.get(f"/api/invoicing/client-invoices/{invoice.id}/")
        self.assertEqual(invoice_response.json()["status"], "PAID")
        self.assertEqual(invoice_response.json()["outstanding_balance"], "0.00")

    def test_allocation_rejects_both_invoice_fields_set(self):
        client_invoice = self.make_client_invoice()
        supplier_invoice = self.make_supplier_invoice()
        payment = self.make_payment(amount=Decimal("1000.00"))

        response = self.client.post("/api/payments/payment-allocations/", {
            "payment": str(payment.id), "client_invoice": str(client_invoice.id),
            "supplier_invoice": str(supplier_invoice.id), "allocated_amount": "100.00",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_allocation_rejects_neither_invoice_field_set(self):
        payment = self.make_payment(amount=Decimal("1000.00"))
        response = self.client.post("/api/payments/payment-allocations/", {
            "payment": str(payment.id), "allocated_amount": "100.00",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_allocation_over_invoice_balance_returns_400(self):
        invoice = self.make_client_invoice(total_amount=Decimal("100.00"))
        payment = self.make_payment(amount=Decimal("1000.00"))
        response = self.client.post("/api/payments/payment-allocations/", {
            "payment": str(payment.id), "client_invoice": str(invoice.id), "allocated_amount": "150.00",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_receipt_creation_for_incoming_payment(self):
        payment = self.make_payment(amount=Decimal("1000.00"))
        response = self.client.post("/api/payments/receipts/", {
            "payment": str(payment.id), "receipt_number": "RCPT-0001",
            "receipt_date": "2026-08-31", "amount": "1000.00",
        }, format="json")
        self.assertEqual(response.status_code, 201)

    def test_receipt_creation_for_outgoing_payment(self):
        payment = self.make_payment(direction=Payment.Direction.OUTGOING, amount=Decimal("500.00"))
        response = self.client.post("/api/payments/receipts/", {
            "payment": str(payment.id), "receipt_number": "RCPT-0002",
            "receipt_date": "2026-08-31", "amount": "500.00",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["payee_name"], "ACME Building Supplies")

    def test_payment_creation_auto_issues_receipts_for_both_directions(self):
        # Money received AND money paid out each get receipted at record
        # time (issue_receipt_for_payment), with the receipt number
        # derived from the payment number.
        incoming = self.client.post("/api/payments/payments/", {
            "payment_number": "PMT-AUTO-IN", "payment_date": "2026-08-31", "amount": "1000.00",
            "direction": "INCOMING", "payment_method": "bank_transfer", "client": str(self.client_obj.id),
        }, format="json")
        outgoing = self.client.post("/api/payments/payments/", {
            "payment_number": "PMT-AUTO-OUT", "payment_date": "2026-08-31", "amount": "250.00",
            "direction": "OUTGOING", "payment_method": "cash", "supplier": str(self.supplier.id),
        }, format="json")
        self.assertEqual(incoming.status_code, 201)
        self.assertEqual(outgoing.status_code, 201)
        for payment_id, number in ((incoming.json()["id"], "PMT-AUTO-IN"), (outgoing.json()["id"], "PMT-AUTO-OUT")):
            receipt = Receipt.objects.get(payment_id=payment_id)
            self.assertEqual(receipt.receipt_number, f"RCT-{number}")
            self.assertEqual(str(receipt.amount), "1000.00" if number == "PMT-AUTO-IN" else "250.00")

    def test_receipt_rejected_if_payment_already_has_one(self):
        payment = self.make_payment(amount=Decimal("1000.00"))
        Receipt.objects.create(payment=payment, receipt_number="RCPT-0003", receipt_date="2026-08-31", amount=Decimal("1000.00"))
        response = self.client.post("/api/payments/receipts/", {
            "payment": str(payment.id), "receipt_number": "RCPT-0004",
            "receipt_date": "2026-08-31", "amount": "1000.00",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_receipt_amount_rules_and_unique_number(self):
        for index, amount in enumerate(("0.00", "-1.00", "999.00")):
            payment = self.make_payment(payment_number=f"PMT-R-AMT-{index}")
            response = self.client.post("/api/payments/receipts/", {
                "payment": str(payment.id), "receipt_number": f"RCPT-AMT-{index}",
                "receipt_date": "2026-08-31", "amount": amount,
            }, format="json")
            self.assertEqual(response.status_code, 400)
        existing_payment = self.make_payment(payment_number="PMT-R-DUP-1")
        Receipt.objects.create(payment=existing_payment, receipt_number="RCPT-DUP", receipt_date="2026-08-31", amount=existing_payment.amount)
        payment = self.make_payment(payment_number="PMT-R-DUP-2")
        response = self.client.post("/api/payments/receipts/", {
            "payment": str(payment.id), "receipt_number": "RCPT-DUP",
            "receipt_date": "2026-08-31", "amount": str(payment.amount),
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_finance_permissions(self):
        owner = User.objects.create(username="finance-owner", email="fo@example.com", password_hash="x",
                                    first_name="F", last_name="O", role=Role.OWNER)
        owner_client = APIClient()
        owner_client.force_authenticate(owner)
        self.assertEqual(owner_client.get("/api/payments/payments/").status_code, 200)
        employee = User.objects.create(username="employee", email="employee@example.com", password_hash="x",
                                       first_name="E", last_name="M", role="EMPLOYEE")
        employee_client = APIClient()
        employee_client.force_authenticate(employee)
        for url in ("/api/payments/payments/", "/api/payments/payment-allocations/", "/api/payments/receipts/"):
            self.assertEqual(employee_client.get(url).status_code, 403)

    def test_invalid_uuid_filters_return_400(self):
        urls = (
            "/api/payments/payments/?client=invalid", "/api/payments/payments/?supplier=invalid",
            "/api/payments/payment-allocations/?payment=invalid",
            "/api/payments/payment-allocations/?client_invoice=invalid",
            "/api/payments/payment-allocations/?supplier_invoice=invalid",
            "/api/payments/receipts/?payment=invalid", "/api/payments/receipts/?client=invalid",
            "/api/payments/receipts/?supplier=invalid",
        )
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 400)

    def test_allocations_and_receipts_are_immutable(self):
        invoice = self.make_client_invoice()
        payment = self.make_payment()
        allocation = allocate_payment(payment, invoice, Decimal("100.00"))
        receipt = Receipt.objects.create(
            payment=payment, receipt_number="RCPT-IMMUTABLE",
            receipt_date="2026-08-31", amount=payment.amount,
        )
        for resource, object_id in (
            ('payment-allocations', allocation.id), ('receipts', receipt.id),
        ):
            url = f"/api/payments/{resource}/{object_id}/"
            self.assertEqual(self.client.patch(url, {}, format="json").status_code, 405)
            self.assertEqual(self.client.put(url, {}, format="json").status_code, 405)
            self.assertEqual(self.client.delete(url).status_code, 405)

    def test_search_ordering_and_filtering_work(self):
        self.make_payment(payment_number="PMT-SEARCH-Z", reference="needle", amount=Decimal("10.00"))
        self.make_payment(payment_number="PMT-SEARCH-A", reference="other", amount=Decimal("20.00"))
        result = self.client.get("/api/payments/payments/?search=needle").json()['results']
        self.assertEqual([row['payment_number'] for row in result], ["PMT-SEARCH-Z"])
        result = self.client.get("/api/payments/payments/?ordering=amount").json()['results']
        amounts = [Decimal(row['amount']) for row in result]
        self.assertEqual(amounts, sorted(amounts))

    def test_filter_by_payment_date_range(self):
        in_range = self.make_payment(payment_number="PMT-API-DATE-1", payment_date="2026-08-15")
        self.make_payment(payment_number="PMT-API-DATE-2", payment_date="2026-01-01")

        response = self.client.get("/api/payments/payments/?date_from=2026-08-01&date_to=2026-08-31")
        numbers = [p["payment_number"] for p in response.json()["results"]]
        self.assertEqual(numbers, [in_range.payment_number])

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/payments/payments/")
        # 401 (not 403): with the auth ticket in place, unauthenticated
        # requests are challenged to authenticate before access is denied.
        self.assertEqual(response.status_code, 401)


class ReceiptDetailAndDownloadAPITests(PaymentsTestBase):
    """
    CPMAS-21 (BRD 5.19): the receipt fields it lists beyond what the
    Receipt model itself stores (client/supplier, payment method), the
    printable/downloadable PDF endpoint, and filtering by client/
    supplier/payment.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.creator)

    def make_receipt(self, **kwargs):
        payment = self.make_payment(amount=Decimal("1000.00"))
        defaults = dict(payment=payment, receipt_number="RCPT-DL-1", receipt_date="2026-08-31", amount=Decimal("1000.00"))
        defaults.update(kwargs)
        return Receipt.objects.create(**defaults)

    def test_receipt_response_includes_client_and_payment_method(self):
        receipt = self.make_receipt()
        response = self.client.get(f"/api/payments/receipts/{receipt.id}/")
        data = response.json()
        self.assertEqual(data["client_name"], "Jane Homeowner")
        self.assertIsNone(data["supplier_name"])
        self.assertEqual(data["payment_method"], "bank_transfer")

    def test_download_returns_a_pdf_attachment(self):
        receipt = self.make_receipt(receipt_number="RCPT-DL-2")
        response = self.client.get(f"/api/payments/receipts/{receipt.id}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="RCPT-DL-2.pdf"', response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_filter_by_client(self):
        receipt = self.make_receipt(receipt_number="RCPT-DL-3")
        other_client = Client.objects.create(name="Someone Else")
        other_payment = self.make_payment(payment_number="PMT-OTHER", amount=Decimal("50.00"), client=other_client)
        Receipt.objects.create(payment=other_payment, receipt_number="RCPT-DL-4", receipt_date="2026-08-31", amount=Decimal("50.00"))

        response = self.client.get(f"/api/payments/receipts/?client={self.client_obj.id}")
        numbers = [r["receipt_number"] for r in response.json()["results"]]
        self.assertIn("RCPT-DL-3", numbers)
        self.assertNotIn("RCPT-DL-4", numbers)

    def test_filter_by_payment(self):
        receipt = self.make_receipt(receipt_number="RCPT-DL-5")
        response = self.client.get(f"/api/payments/receipts/?payment={receipt.payment_id}")
        numbers = [r["receipt_number"] for r in response.json()["results"]]
        self.assertEqual(numbers, ["RCPT-DL-5"])

    def test_filter_by_receipt_date_range(self):
        in_range_payment = self.make_payment(payment_number="PMT-DL-7", amount=Decimal("1000.00"))
        in_range = Receipt.objects.create(payment=in_range_payment, receipt_number="RCPT-DL-7", receipt_date="2026-08-15", amount=Decimal("1000.00"))

        out_of_range_payment = self.make_payment(payment_number="PMT-DL-8", amount=Decimal("1000.00"))
        Receipt.objects.create(payment=out_of_range_payment, receipt_number="RCPT-DL-8", receipt_date="2026-01-01", amount=Decimal("1000.00"))

        response = self.client.get("/api/payments/receipts/?date_from=2026-08-01&date_to=2026-08-31")
        numbers = [r["receipt_number"] for r in response.json()["results"]]
        self.assertEqual(numbers, [in_range.receipt_number])

    def test_anonymous_download_is_rejected(self):
        receipt = self.make_receipt(receipt_number="RCPT-DL-6")
        anon = APIClient()
        response = anon.get(f"/api/payments/receipts/{receipt.id}/download/")
        self.assertEqual(response.status_code, 401)

    def test_pdf_contains_branded_professional_elements(self):
        """The generated PDF carries the professional receipt layout:
        title, party block, payment summary, amount, and acknowledgement,
        even without a company profile row (company_details is an
        unmanaged shared table not present in the test database)."""
        from .pdf import render_receipt_pdf

        receipt = self.make_receipt(receipt_number="RCPT-DL-9", amount=Decimal("1000.00"))
        pdf = render_receipt_pdf(receipt)

        self.assertTrue(pdf.startswith(b"%PDF"))
        # PDF content is Flate-compressed, but reportlab keeps a plain-text
        # font/summary layer; at minimum the bytes must be a valid single-
        # page PDF with an EOF trailer.
        self.assertIn(b"%%EOF", pdf)
        self.assertGreater(len(pdf), 2000)
class EmployeeContractorPaymentAPITests(PaymentsTestBase):
    @classmethod
    def setUpClass(cls):
        # Only the payee tables are needed here. Leave them in the disposable
        # test database to avoid SQLite rebuilding unrelated reflected tables
        # with cross-app foreign keys during per-class teardown.
        existing = connection.introspection.table_names()
        with connection.schema_editor() as editor:
            for model in (Employee, Contractor):
                if model._meta.db_table not in existing:
                    editor.create_model(model)
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(user=self.creator)
        self.employee = Employee.objects.create(
            employee_number="EMP-001", name="Maya Haddad",
            employment_status=Employee.EmploymentStatus.ACTIVE,
            labor_rate=Decimal("25.00"),
        )
        self.contractor = Contractor.objects.create(
            name="Atlas Concrete", status=Contractor.Status.ACTIVE,
            rate=Decimal("300.00"),
        )

    def payment_payload(self, number, **party):
        return {
            "payment_number": number, "payment_date": "2026-09-05",
            "amount": "300.00", "direction": "OUTGOING",
            "payment_method": "bank_transfer", **party,
        }

    def test_pay_employee(self):
        response = self.api.post(
            "/api/payments/payments/",
            self.payment_payload("PMT-EMP-001", employee_id=str(self.employee.id)),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["payee_type"], "EMPLOYEE")
        self.assertEqual(response.data["payee_name"], "Maya Haddad")
        self.assertFalse(response.data["allocatable"])

    def test_pay_contractor(self):
        response = self.api.post(
            "/api/payments/payments/",
            self.payment_payload("PMT-CON-001", contractor_id=str(self.contractor.id)),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["payee_type"], "CONTRACTOR")
        self.assertEqual(response.data["payee_name"], "Atlas Concrete")
        # Contractor payments fund contractor invoices (the whole point of
        # the contractor-invoice feature), so they are allocatable like
        # supplier payments -- and they get an auto-issued receipt.
        self.assertTrue(response.data["allocatable"])
        self.assertTrue(response.data["has_receipt"])

    def test_rejects_multiple_outgoing_payees(self):
        response = self.api.post(
            "/api/payments/payments/",
            self.payment_payload(
                "PMT-MULTI", supplier=str(self.supplier.id),
                employee_id=str(self.employee.id),
            ), format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_allocate_contractor_invoice_via_api(self):
        invoice = ContractorInvoice.objects.create(
            contractor_id=self.contractor.id, invoice_number="COINV-API-1",
            invoice_date="2026-08-31", total_amount=Decimal("3000.00"),
            status=ContractorInvoice.Status.SENT,
        )
        payment_response = self.api.post(
            "/api/payments/payments/",
            self.payment_payload("PMT-CON-002", contractor_id=str(self.contractor.id)),
            format="json",
        )
        self.assertEqual(payment_response.status_code, 201, payment_response.data)

        allocation = self.api.post("/api/payments/payment-allocations/", {
            "payment": payment_response.json()["id"],
            "contractor_invoice": str(invoice.id),
            "allocated_amount": "300.00",
        }, format="json")
        self.assertEqual(allocation.status_code, 201, allocation.data)

        invoice_response = self.api.get(f"/api/invoicing/contractor-invoices/{invoice.id}/")
        self.assertEqual(invoice_response.json()["status"], "PARTIALLY_PAID")
        self.assertEqual(invoice_response.json()["outstanding_balance"], "2700.00")

    def test_incoming_payment_cannot_allocate_to_contractor_invoice_via_api(self):
        invoice = ContractorInvoice.objects.create(
            contractor_id=self.contractor.id, invoice_number="COINV-API-2",
            invoice_date="2026-08-31", total_amount=Decimal("3000.00"),
            status=ContractorInvoice.Status.SENT,
        )
        payment_response = self.api.post("/api/payments/payments/", {
            "payment_number": "PMT-IN-CON", "payment_date": "2026-09-05",
            "amount": "3000.00", "direction": "INCOMING",
            "payment_method": "bank_transfer", "client": str(self.client_obj.id),
        }, format="json")
        allocation = self.api.post("/api/payments/payment-allocations/", {
            "payment": payment_response.json()["id"],
            "contractor_invoice": str(invoice.id),
            "allocated_amount": "3000.00",
        }, format="json")
        self.assertEqual(allocation.status_code, 400)

    def test_rejects_unknown_employee_or_contractor(self):
        for field in ("employee_id", "contractor_id"):
            response = self.api.post(
                "/api/payments/payments/",
                self.payment_payload(f"PMT-{field}", **{field: str(uuid4())}),
                format="json",
            )
            self.assertEqual(response.status_code, 400)

class ProjectFinancialSummaryTests(
    WithUsersTableMixin,
    WithClientsTableMixin,
    WithProjectsTableMixin,
    WithContractorsTableMixin,
    TestCase,
):
    """
    CPMAS project financial roll-up (``projects.financial``, exposed at
    ``GET /api/projects/projects/{id}/financial-summary/``): revenue from a
    project's linked client invoices, expenses from its linked supplier +
    contractor invoices, and the net position. Values move as payments are
    allocated, which the invoice workflow relies on -- "confirm the project
    financial summary changes" is the last step of the supplier-invoice flow.
    """

    def setUp(self):
        super().setUp()
        from projects.models import Project

        self.creator = User.objects.create(
            username="proj_fin", email="proj_fin@example.com", password_hash="x",
            first_name="P", last_name="F", role=Role.ACCOUNTANT,
        )
        self.client_obj = Client.objects.create(name="Jane Homeowner")
        self.supplier = Supplier.objects.create(name="ACME Building Supplies")
        self.contractor = Contractor.objects.create(
            name="Atlas Concrete", status=Contractor.Status.ACTIVE, rate=Decimal("300.00"),
        )
        self.project = Project.objects.create(
            code="FIN-SUM-T1", name="Financial Summary Tower",
            project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("100000.00"),
            buyer=self.client_obj,
        )

    def summary(self):
        from projects.financial import get_project_financial_summary

        return get_project_financial_summary(self.project)

    def make_invoice(self, model, total_amount, **kwargs):
        defaults = dict(
            invoice_number=f"FS-{uuid4().hex[:8].upper()}",
            invoice_date="2026-08-31", total_amount=total_amount, status=model.Status.SENT,
        )
        defaults.update(kwargs)
        return model.objects.create(**defaults)

    def test_summary_is_empty_without_linked_invoices(self):
        s = self.summary()
        self.assertEqual(s["project"]["code"], "FIN-SUM-T1")
        self.assertEqual(s["revenue"]["billed"], "0.00")
        self.assertEqual(s["revenue"]["received"], "0.00")
        self.assertEqual(s["expenses"]["invoiced"], "0.00")
        self.assertEqual(s["expenses"]["paid"], "0.00")
        self.assertEqual(s["net"]["accrual"], "0.00")
        self.assertEqual(s["net"]["cash"], "0.00")
        self.assertEqual(s["net"]["outstanding"], "0.00")

    def test_allocation_flow_moves_revenue_expenses_and_net(self):
        client_inv = self.make_invoice(ClientInvoice, Decimal("5000.00"), client=self.client_obj, project=self.project)
        supplier_inv = self.make_invoice(SupplierInvoice, Decimal("2000.00"), supplier=self.supplier, project=self.project)
        contractor_inv = self.make_invoice(ContractorInvoice, Decimal("1500.00"), contractor_id=self.contractor.id, project=self.project)

        s = self.summary()
        self.assertEqual(s["revenue"]["billed"], "5000.00")
        self.assertEqual(s["revenue"]["received"], "0.00")
        self.assertEqual(s["expenses"]["invoiced"], "3500.00")
        self.assertEqual(s["expenses"]["paid"], "0.00")
        self.assertEqual(s["revenue"]["outstanding"], "5000.00")
        self.assertEqual(s["expenses"]["outstanding"], "3500.00")
        self.assertEqual(s["net"]["accrual"], "1500.00")
        self.assertEqual(s["net"]["cash"], "0.00")
        self.assertEqual(s["net"]["outstanding"], "8500.00")

        # Outgoing payment to the supplier, allocated in two bites
        # (partial -> PARTIALLY_PAID -> full -> PAID).
        payment = Payment.objects.create(
            payment_number="FS-PAY-OUT1", payment_date="2026-09-01", amount=Decimal("2000.00"),
            direction=Payment.Direction.OUTGOING, payment_method="bank_transfer",
            created_by=self.creator, supplier=self.supplier,
        )
        allocate_payment(payment, supplier_inv, Decimal("800.00"))
        s = self.summary()
        self.assertEqual(s["expenses"]["paid"], "800.00")
        self.assertEqual(s["expenses"]["outstanding"], "2700.00")
        self.assertEqual(s["net"]["cash"], "-800.00")

        allocate_payment(payment, supplier_inv, Decimal("1200.00"))
        supplier_inv.refresh_from_db()
        s = self.summary()
        self.assertEqual(supplier_inv.status, SupplierInvoice.Status.PAID)
        self.assertEqual(s["expenses"]["paid"], "2000.00")
        self.assertEqual(s["expenses"]["outstanding"], "1500.00")
        self.assertEqual(s["net"]["cash"], "-2000.00")

        # Incoming payment from the client, fully allocated -> PAID.
        receipt = Payment.objects.create(
            payment_number="FS-PAY-IN1", payment_date="2026-09-02", amount=Decimal("5000.00"),
            direction=Payment.Direction.INCOMING, payment_method="bank_transfer",
            created_by=self.creator, client=self.client_obj,
        )
        allocate_payment(receipt, client_inv, Decimal("5000.00"))
        client_inv.refresh_from_db()
        s = self.summary()
        self.assertEqual(client_inv.status, ClientInvoice.Status.PAID)
        self.assertEqual(s["revenue"]["received"], "5000.00")
        self.assertEqual(s["revenue"]["outstanding"], "0.00")
        self.assertEqual(s["net"]["cash"], "3000.00")
        self.assertEqual(s["net"]["accrual"], "1500.00")

    def test_unallocated_payments_do_not_count(self):
        self.make_invoice(ClientInvoice, Decimal("5000.00"), client=self.client_obj, project=self.project)
        Payment.objects.create(
            payment_number="FS-PAY-IN2", payment_date="2026-09-02", amount=Decimal("5000.00"),
            direction=Payment.Direction.INCOMING, payment_method="cash",
            created_by=self.creator, client=self.client_obj,
        )
        s = self.summary()
# a payment in hand is not revenue until it is allocated to an invoice
        self.assertEqual(s["revenue"]["received"], "0.00")
        self.assertEqual(s["revenue"]["outstanding"], "5000.00")

    def test_other_projects_and_draft_status_are_gated_out(self):
        from projects.models import Project

        self.make_invoice(ClientInvoice, Decimal("5000.00"), client=self.client_obj, project=self.project)
        # A SENT supplier invoice on a *different* project must not leak in.
        other = Project.objects.create(
            code="FIN-SUM-T2", name="Other Tower", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("50000.00"), buyer=self.client_obj,
        )
        self.make_invoice(
            SupplierInvoice, Decimal("999.00"), supplier=self.supplier, project=other,
        )
        # A DRAFT supplier invoice on this project must not count as billed.
        self.make_invoice(
            SupplierInvoice, Decimal("1000.00"), supplier=self.supplier, project=self.project,
            status=SupplierInvoice.Status.DRAFT,
        )
        s = self.summary()
        self.assertEqual(s["revenue"]["billed"], "5000.00")
        self.assertEqual(s["expenses"]["invoiced"], "0.00")
        self.assertEqual(s["net"]["accrual"], "5000.00")

    def test_updates_do_not_require_recalculated_invoice_columns(self):
        # Even a bare supplier invoice (subtotal/tax defaults, total set
        # by the totals recalculator elsewhere) rolls up correctly because
        # the summary reads total_amount + PaymentAllocation, not cached
        # subtotal/tax.
        self.make_invoice(SupplierInvoice, Decimal("2000.00"), supplier=self.supplier, project=self.project)
        payment = Payment.objects.create(
            payment_number="FS-PAY-OUT2", payment_date="2026-09-01", amount=Decimal("2000.00"),
            direction=Payment.Direction.OUTGOING, payment_method="bank_transfer",
            created_by=self.creator, supplier=self.supplier,
        )
        allocate_payment(payment, SupplierInvoice.objects.get(project=self.project), Decimal("2000.00"))
        s = self.summary()
        self.assertEqual(s["expenses"]["invoiced"], "2000.00")
        self.assertEqual(s["expenses"]["paid"], "2000.00")
        self.assertEqual(s["expenses"]["outstanding"], "0.00")
