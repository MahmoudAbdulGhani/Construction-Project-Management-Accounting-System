"""
Business logic for the ``payments`` app that must not live in a
serializer or viewset.

Two concerns are centralized here, for the same reason
``accounting.services``/``purchasing.services`` centralize theirs:

1. ``outstanding_balance`` -- BRD 5.23/5.24: an invoice's outstanding
   balance is always calculated from its total minus the sum of its
   payment allocations, never a stored/manually-editable value. Works
   for ClientInvoice, SupplierInvoice, or ContractorInvoice.
2. ``allocate_payment`` is the single place a PaymentAllocation gets
   created AND the single place an invoice's status advances to
   PARTIALLY_PAID/PAID as a result -- bypassing invoicing.services'
   ALLOWED_TRANSITIONS allow-lists entirely, same reasoning as
   purchasing.services._recalculate_po_receipt_status: this is a
   system-derived state change driven by actual money received/paid,
   not a user-facing workflow action.
3. ``issue_receipt_for_payment`` backs auto-receipting: every recorded
   payment gets a receipt (both money received from a client and money
   paid out to a supplier/employee/contractor) -- see
   PaymentViewSet.perform_create.
"""
from decimal import Decimal
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from invoicing.models import ClientInvoice, ContractorInvoice, SupplierInvoice

from .models import Payment, PaymentAllocation, Receipt

TWO_PLACES = Decimal('0.01')

# An invoice not yet SENT (DRAFT) or already CANCELLED isn't a real
# receivable/payable -- it has no outstanding balance to track.
_NO_BALANCE_STATUSES = {'DRAFT', 'CANCELLED'}


def generate_payment_number(payment_year=None) -> str:
    """
    Next payment number as ``PAY-<year>-<seq>`` (echoes the live
    ``PAY-2026-002`` data): one past the highest numeric suffix used that
    year. Create-only callers wrap the INSERT in a retry loop
    (create_payment_with_generated_number) since this is not
    unique-safe on its own.
    """
    year = payment_year or timezone.now().date().year
    prefix = f"PAY-{year}-"
    highest = 0
    for number in Payment.objects.filter(payment_number__startswith=prefix).values_list('payment_number', flat=True):
        match = re.search(r"-(\d+)$", number)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:04d}"


def create_payment_with_generated_number(validated_data) -> Payment:
    """``create()`` helper for PaymentSerializer: fills in a generated
    payment number when the caller left it blank, retrying (regenerating)
    if a concurrent request wins the same sequence value."""
    data = dict(validated_data)
    for _ in range(3):
        try:
            with transaction.atomic():
                number = (data.get('payment_number') or '').strip()
                if not number:
                    year = (data.get('payment_date') or timezone.now().date()).year
                    number = generate_payment_number(year)
                return Payment.objects.create(**{**data, 'payment_number': number})
        except IntegrityError:
            data = dict(validated_data)
    raise IntegrityError("Could not allocate a unique payment number; please retry.")


def outstanding_balance(invoice) -> Decimal:
    """
    invoice: a ClientInvoice, SupplierInvoice, or ContractorInvoice
    instance.

    Returns 0 for DRAFT/CANCELLED invoices (see module docstring);
    otherwise total_amount minus the sum of this invoice's
    PaymentAllocations.
    """
    if invoice.status in _NO_BALANCE_STATUSES:
        return Decimal('0.00')

    field_name = {
        ClientInvoice: 'client_invoice',
        SupplierInvoice: 'supplier_invoice',
        ContractorInvoice: 'contractor_invoice',
    }.get(type(invoice))
    if field_name is None:
        raise ValidationError("invoice must be a ClientInvoice, SupplierInvoice, or ContractorInvoice.")

    allocated = PaymentAllocation.objects.filter(**{field_name: invoice}).aggregate(
        total=Sum('allocated_amount')
    )['total'] or Decimal('0.00')
    return invoice.total_amount - allocated


def unallocated_amount(payment: Payment) -> Decimal:
    """How much of a Payment has not yet been applied to any invoice."""
    allocated = payment.allocations.aggregate(total=Sum('allocated_amount'))['total'] or Decimal('0.00')
    return payment.amount - allocated


@transaction.atomic
def allocate_payment(payment: Payment, invoice, allocated_amount: Decimal) -> PaymentAllocation:
    """
    Apply part or all of a Payment against one invoice, and advance that
    invoice's status accordingly.

    Validates:
    - the payment's direction matches the invoice type (INCOMING can
      only fund a ClientInvoice, OUTGOING only a SupplierInvoice or
      ContractorInvoice -- money received from a client can't pay a
      supplier/contractor bill and vice versa);
    - the invoice is SENT, OVERDUE, or PARTIALLY_PAID (DRAFT hasn't been
      billed yet, while PAID/CANCELLED states shouldn't accept money);
    - the payment party matches the invoice party;
    - allocated_amount is positive, doesn't exceed the payment's own
      remaining unallocated_amount, and doesn't exceed the invoice's own
      outstanding_balance (over-allocating either side would make the
      derived balance go negative); both rows are locked while these
      values are calculated so concurrent requests cannot over-allocate.

    On success: creates the PaymentAllocation, then sets the invoice to
    PAID if its new outstanding balance is <= 0, else PARTIALLY_PAID.
    """
    is_client_invoice = isinstance(invoice, ClientInvoice)
    is_supplier_invoice = isinstance(invoice, SupplierInvoice)
    is_contractor_invoice = isinstance(invoice, ContractorInvoice)
    if not (is_client_invoice or is_supplier_invoice or is_contractor_invoice):
        raise ValidationError(
            "invoice must be a ClientInvoice, SupplierInvoice, or ContractorInvoice."
        )

    if is_client_invoice and payment.direction != Payment.Direction.INCOMING:
        raise ValidationError("An OUTGOING payment cannot be allocated to a client invoice.")
    if (is_supplier_invoice or is_contractor_invoice) and payment.direction != Payment.Direction.OUTGOING:
        raise ValidationError("An INCOMING payment cannot be allocated to a supplier or contractor invoice.")

    # Lock both mutable balances before calculating either one. Locking the
    # payment serializes allocations to different invoices as well.
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if is_client_invoice:
        invoice_model = ClientInvoice
    elif is_supplier_invoice:
        invoice_model = SupplierInvoice
    else:
        invoice_model = ContractorInvoice
    invoice = invoice_model.objects.select_for_update().get(pk=invoice.pk)

    if is_client_invoice and payment.client_id != invoice.client_id:
        raise ValidationError("The payment client must match the invoice client.")
    if is_supplier_invoice and payment.supplier_id != invoice.supplier_id:
        raise ValidationError("The payment supplier must match the invoice supplier.")
    if is_contractor_invoice and payment.contractor_id != invoice.contractor_id:
        raise ValidationError("The payment contractor must match the invoice contractor.")

    allowed_invoice_statuses = {
        invoice.Status.SENT, invoice.Status.OVERDUE, invoice.Status.PARTIALLY_PAID,
    }
    if invoice.status not in allowed_invoice_statuses:
        raise ValidationError(
            f"Cannot allocate a payment to an invoice that is {invoice.get_status_display()}."
        )

    if allocated_amount <= 0:
        raise ValidationError("allocated_amount must be positive.")

    remaining_on_payment = unallocated_amount(payment)
    if allocated_amount > remaining_on_payment:
        raise ValidationError(
            f"Cannot allocate {allocated_amount} -- only {remaining_on_payment} of this payment is unallocated."
        )

    remaining_on_invoice = outstanding_balance(invoice)
    if allocated_amount > remaining_on_invoice:
        raise ValidationError(
            f"Cannot allocate {allocated_amount} -- this invoice's outstanding balance is only {remaining_on_invoice}."
        )

    allocation = PaymentAllocation.objects.create(
        payment=payment,
        client_invoice=invoice if is_client_invoice else None,
        supplier_invoice=invoice if is_supplier_invoice else None,
        contractor_invoice=invoice if is_contractor_invoice else None,
        allocated_amount=allocated_amount,
    )

    new_balance = remaining_on_invoice - allocated_amount
    invoice.status = invoice.Status.PAID if new_balance <= Decimal('0.00') else invoice.Status.PARTIALLY_PAID
    invoice.save(update_fields=['status', 'updated_at'])

    return allocation


def issue_receipt_for_payment(payment: Payment) -> Receipt:
    """
    Create the (single) receipt for a Payment; a no-op if one already
    exists. Used for auto-receipting on payment creation -- a payment
    with an existing receipt must keep its original, and a receipt can
    never be re-issued.
    """
    if hasattr(payment, 'receipt'):
        return payment.receipt
    return Receipt.objects.create(
        payment=payment,
        receipt_number=f"RCT-{payment.payment_number}",
        receipt_date=payment.payment_date,
        amount=payment.amount,
    )
