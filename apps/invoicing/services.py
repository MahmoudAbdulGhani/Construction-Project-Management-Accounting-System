"""
Business logic for the ``invoicing`` app that must not live in a
serializer or viewset.

Same reasoning as purchasing.services (CPMAS-30): centralizing these
rules in one place makes them structurally enforced rather than just
documented.

1. Monetary totals are always computed here, not accepted as direct API
   input for the invoice header.
2. SupplierInvoice.status/ClientInvoice.status only ever change through
   transition_status/transition_client_invoice_status, validated against
   their respective ALLOWED_TRANSITIONS maps -- except PARTIALLY_PAID/
   PAID/OVERDUE, which are set only by payments.services.allocate_payment
   (CPMAS-35), bypassing these allow-lists entirely (same reasoning as
   purchasing.services._recalculate_po_receipt_status: that's a
   system-derived state change, not a user-facing action to validate
   against a manual workflow).
3. OVERDUE itself is derived state too: an invoice whose due_date has
   passed (SENT or PARTIALLY_PAID) becomes OVERDUE via
   sync_overdue_statuses, called from the invoice viewsets on read -- a
   page view is what makes "past due" visible, no user action required.

Since CPMAS-34 (Accounting/GL integration, Phase 2), sending an invoice
also recognizes it in the general ledger: ``transition_status`` /
``transition_client_invoice_status`` / ``transition_contractor_invoice_status``
call ``accounting.services.book_*_invoice`` inside the same atomic block
when the target is SENT, and void the linked journal entry (via
``accounting.services.void_source_entry``) when a SENT invoice is
cancelled. A failed booking rolls the whole transition back, so an
invoice is either SENT with its GL entry or it isn't sent at all.
"""
from decimal import ROUND_HALF_UP, Decimal
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounting.models import FinancialTransaction
from accounting.services import (
    book_client_invoice,
    book_contractor_invoice,
    book_supplier_invoice,
    void_source_entry,
)

from .models import (
    ClientInvoice,
    ClientInvoiceItem,
    ContractorInvoice,
    ContractorInvoiceItem,
    SupplierInvoice,
    SupplierInvoiceItem,
)

TWO_PLACES = Decimal('0.01')

# Invoice states that have been billed and are therefore eligible to go
# OVERDUE once due_date passes. DRAFT hasn't been issued, and PAID/
# CANCELLED are terminal -- none of them can be past-due.
_BILLED_STATUSES = {'SENT', 'PARTIALLY_PAID'}


def generate_invoice_number(instance_model, invoice_year=None) -> str:
    """
    Next invoice number for ``instance_model`` (one of the three invoice
    models) as ``INV-<year>-<seq>``, where seq is one past the highest
    numeric suffix already used that year. The scheme is
    ``INV-2026-0001``-style to echo the ``PAY-2026-002`` payment numbers
    already in the live data. Not unique-safe on its own -- callers wrap
    the eventual INSERT in a retry loop (create_invoice_with_generated_number).
    """
    year = invoice_year or timezone.now().date().year
    prefix = f"INV-{year}-"
    highest = 0
    for number in instance_model.objects.filter(invoice_number__startswith=prefix).values_list('invoice_number', flat=True):
        match = re.search(r"-(\d+)$", number)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:04d}"


def create_invoice_with_generated_number(instance_model, validated_data):
    """
    ``create()`` helper for the three invoice header serializers: assigns
    a generated invoice number when the caller left it blank, then creates
    the row. Retries (regenerating the number) if a concurrent request
    raced us to the same sequence value.
    """
    data = dict(validated_data)
    for _ in range(3):
        try:
            with transaction.atomic():
                number = (data.get('invoice_number') or '').strip()
                if not number:
                    year = (data.get('invoice_date') or timezone.now().date()).year
                    number = generate_invoice_number(instance_model, year)
                return instance_model.objects.create(**{**data, 'invoice_number': number})
        except IntegrityError:
            data = dict(validated_data)
    raise IntegrityError("Could not allocate a unique invoice number; please retry.")


def compute_item_amounts(item: SupplierInvoiceItem) -> SupplierInvoiceItem:
    """
    Set tax_amount and total_amount on a (not-yet-saved) SupplierInvoiceItem.

    Two cases, per the schema allowing quantity/unit_price to be null
    (unlike PurchaseOrderItem, where both are required):

    - Both quantity and unit_price are given: derive exactly like a PO
      item (quantity * unit_price, plus tax_rate.rate% if set) --
      whatever tax_amount/total_amount the caller sent are overwritten.
    - Either is missing (a flat-charge line, e.g. a delivery fee): there
      is nothing to multiply, so the caller-supplied total_amount is
      trusted as-is; tax_amount defaults to 0 unless the caller already
      set one (a flat charge can still carry its own tax figure without
      a quantity/price breakdown).
    """
    if item.quantity is not None and item.unit_price is not None:
        line_subtotal = (item.quantity * item.unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        if item.tax_rate_id and item.tax_rate:
            tax_amount = (line_subtotal * item.tax_rate.rate / Decimal('100')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            tax_amount = Decimal('0.00')

        item.tax_amount = tax_amount
        item.total_amount = line_subtotal + tax_amount
    else:
        # Flat-charge line: nothing to derive from, keep whatever the
        # caller provided (defaulting to 0 if they provided nothing).
        item.tax_amount = item.tax_amount or Decimal('0.00')
        item.total_amount = item.total_amount or Decimal('0.00')

    return item


@transaction.atomic
def recalculate_invoice_totals(invoice: SupplierInvoice) -> SupplierInvoice:
    """
    Recompute a SupplierInvoice's subtotal/tax_amount/total_amount from
    its current line items.

    subtotal is derived as (total_amount - tax_amount) per line rather
    than re-deriving quantity*unit_price, so it works uniformly whether
    a given line's amounts came from the quantity/price path or were
    supplied directly as a flat charge (see compute_item_amounts).
    """
    items = invoice.items.all()

    subtotal_sum = sum((i.total_amount - i.tax_amount for i in items), Decimal('0.00'))
    tax_sum = sum((i.tax_amount for i in items), Decimal('0.00'))
    total_sum = sum((i.total_amount for i in items), Decimal('0.00'))

    invoice.subtotal = subtotal_sum
    invoice.tax_amount = tax_sum
    invoice.total_amount = total_sum
    invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount', 'updated_at'])
    return invoice


# PARTIALLY_PAID/PAID/OVERDUE are not reachable here -- they depend on
# payment allocations, which don't exist yet (see module docstring).
ALLOWED_TRANSITIONS = {
    SupplierInvoice.Status.DRAFT: {SupplierInvoice.Status.SENT, SupplierInvoice.Status.CANCELLED},
    SupplierInvoice.Status.SENT: {SupplierInvoice.Status.CANCELLED},
    SupplierInvoice.Status.PARTIALLY_PAID: set(),
    SupplierInvoice.Status.PAID: set(),
    SupplierInvoice.Status.OVERDUE: set(),
    SupplierInvoice.Status.CANCELLED: set(),
}


def transition_status(invoice: SupplierInvoice, new_status: str, *, created_by=None) -> SupplierInvoice:
    """Move a SupplierInvoice to new_status if valid; raises ValidationError otherwise.

    SENT bookings (and SENT->CANCELLED voids) run inside the same atomic
    block as the status change, so an unconfigured GL account rolls the
    transition back and the invoice stays DRAFT/SENT.
    """
    current = SupplierInvoice.Status(invoice.status)
    target = SupplierInvoice.Status(new_status)

    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValidationError(
            f"Cannot move a supplier invoice from {current.label} to {target.label}."
        )

    if target == SupplierInvoice.Status.SENT:
        with transaction.atomic():
            invoice.status = target
            invoice.save(update_fields=['status', 'updated_at'])
            book_supplier_invoice(invoice, created_by=created_by)
    elif target == SupplierInvoice.Status.CANCELLED and current == SupplierInvoice.Status.SENT:
        with transaction.atomic():
            invoice.status = target
            invoice.save(update_fields=['status', 'updated_at'])
            void_source_entry(FinancialTransaction.SourceType.SUPPLIER_INVOICE, invoice.id)
    else:
        invoice.status = target
        invoice.save(update_fields=['status', 'updated_at'])
    return invoice


def compute_client_invoice_item_amounts(item: ClientInvoiceItem) -> ClientInvoiceItem:
    """
    Set tax_amount and total_amount on a (not-yet-saved) ClientInvoiceItem.

    Unlike SupplierInvoiceItem, quantity/unit_price are always required
    here, so there's no flat-charge branch: this always derives from
    quantity * unit_price, minus discount_amount, plus tax_rate.rate% of
    the discounted subtotal if a tax_rate is set. total_amount is the
    net line total (post-discount, post-tax) -- see
    recalculate_client_invoice_totals for how the header's own subtotal/
    discount_amount/tax_amount/total_amount are then summed from this.
    """
    line_gross = (item.quantity * item.unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    discount = item.discount_amount or Decimal('0.00')
    net_before_tax = line_gross - discount

    if item.tax_rate_id and item.tax_rate:
        tax_amount = (net_before_tax * item.tax_rate.rate / Decimal('100')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        tax_amount = Decimal('0.00')

    item.tax_amount = tax_amount
    item.total_amount = net_before_tax + tax_amount
    return item


@transaction.atomic
def recalculate_client_invoice_totals(invoice: ClientInvoice) -> ClientInvoice:
    """
    Recompute a ClientInvoice's subtotal/discount_amount/tax_amount/
    total_amount from its current line items.

    subtotal is the pre-discount, pre-tax gross (quantity * unit_price
    summed across lines) -- standard invoicing convention, distinct from
    SupplierInvoice's subtotal (which has no discount concept to net
    out). discount_amount/tax_amount/total_amount are then each summed
    directly from the per-line values compute_client_invoice_item_amounts
    already derived.
    """
    items = invoice.items.all()

    subtotal_sum = sum((i.quantity * i.unit_price for i in items), Decimal('0.00')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    discount_sum = sum(((i.discount_amount or Decimal('0.00')) for i in items), Decimal('0.00'))
    tax_sum = sum((i.tax_amount for i in items), Decimal('0.00'))
    total_sum = sum((i.total_amount for i in items), Decimal('0.00'))

    invoice.subtotal = subtotal_sum
    invoice.discount_amount = discount_sum
    invoice.tax_amount = tax_sum
    invoice.total_amount = total_sum
    invoice.save(update_fields=['subtotal', 'discount_amount', 'tax_amount', 'total_amount', 'updated_at'])
    return invoice


# PARTIALLY_PAID/PAID/OVERDUE are not reachable here -- see module docstring.
CLIENT_INVOICE_ALLOWED_TRANSITIONS = {
    ClientInvoice.Status.DRAFT: {ClientInvoice.Status.SENT, ClientInvoice.Status.CANCELLED},
    ClientInvoice.Status.SENT: {ClientInvoice.Status.CANCELLED},
    ClientInvoice.Status.PARTIALLY_PAID: set(),
    ClientInvoice.Status.PAID: set(),
    ClientInvoice.Status.OVERDUE: set(),
    ClientInvoice.Status.CANCELLED: set(),
}


def transition_client_invoice_status(invoice: ClientInvoice, new_status: str, *, created_by=None) -> ClientInvoice:
    """Move a ClientInvoice to new_status if valid; raises ValidationError otherwise.

    Same SENT booking / SENT->CANCELLED void semantics as transition_status.
    """
    current = ClientInvoice.Status(invoice.status)
    target = ClientInvoice.Status(new_status)

    if target not in CLIENT_INVOICE_ALLOWED_TRANSITIONS[current]:
        raise ValidationError(
            f"Cannot move a client invoice from {current.label} to {target.label}."
        )

    if target == ClientInvoice.Status.SENT:
        with transaction.atomic():
            invoice.status = target
            invoice.save(update_fields=['status', 'updated_at'])
            book_client_invoice(invoice, created_by=created_by)
    elif target == ClientInvoice.Status.CANCELLED and current == ClientInvoice.Status.SENT:
        with transaction.atomic():
            invoice.status = target
            invoice.save(update_fields=['status', 'updated_at'])
            void_source_entry(FinancialTransaction.SourceType.CLIENT_INVOICE, invoice.id)
    else:
        invoice.status = target
        invoice.save(update_fields=['status', 'updated_at'])
    return invoice


def compute_contractor_item_amounts(item: ContractorInvoiceItem) -> ContractorInvoiceItem:
    """
    Set tax_amount and total_amount on a (not-yet-saved) ContractorInvoiceItem.

    Same rules as compute_item_amounts: with both quantity and unit_price
    set, derive quantity * unit_price plus tax_rate.rate%; with either
    missing (a flat-charge line, e.g. a lump-sum works item), keep the
    caller-supplied total_amount as-is.
    """
    if item.quantity is not None and item.unit_price is not None:
        line_subtotal = (item.quantity * item.unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        if item.tax_rate_id and item.tax_rate:
            tax_amount = (line_subtotal * item.tax_rate.rate / Decimal('100')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            tax_amount = Decimal('0.00')

        item.tax_amount = tax_amount
        item.total_amount = line_subtotal + tax_amount
    else:
        item.tax_amount = item.tax_amount or Decimal('0.00')
        item.total_amount = item.total_amount or Decimal('0.00')

    return item


@transaction.atomic
def recalculate_contractor_invoice_totals(invoice: ContractorInvoice) -> ContractorInvoice:
    """Same shape as recalculate_invoice_totals, for a ContractorInvoice."""
    items = invoice.items.all()

    subtotal_sum = sum((i.total_amount - i.tax_amount for i in items), Decimal('0.00'))
    tax_sum = sum((i.tax_amount for i in items), Decimal('0.00'))
    total_sum = sum((i.total_amount for i in items), Decimal('0.00'))

    invoice.subtotal = subtotal_sum
    invoice.tax_amount = tax_sum
    invoice.total_amount = total_sum
    invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount', 'updated_at'])
    return invoice


# Same allow-list as the supplier side, per the shared module docstring.
CONTRACTOR_INVOICE_ALLOWED_TRANSITIONS = {
    ContractorInvoice.Status.DRAFT: {ContractorInvoice.Status.SENT, ContractorInvoice.Status.CANCELLED},
    ContractorInvoice.Status.SENT: {ContractorInvoice.Status.CANCELLED},
    ContractorInvoice.Status.PARTIALLY_PAID: set(),
    ContractorInvoice.Status.PAID: set(),
    ContractorInvoice.Status.OVERDUE: set(),
    ContractorInvoice.Status.CANCELLED: set(),
}


def transition_contractor_invoice_status(invoice: ContractorInvoice, new_status: str, *, created_by=None) -> ContractorInvoice:
    """Move a ContractorInvoice to new_status if valid; raises ValidationError otherwise.

    Same SENT booking / SENT->CANCELLED void semantics as transition_status.
    """
    current = ContractorInvoice.Status(invoice.status)
    target = ContractorInvoice.Status(new_status)

    if target not in CONTRACTOR_INVOICE_ALLOWED_TRANSITIONS[current]:
        raise ValidationError(
            f"Cannot move a contractor invoice from {current.label} to {target.label}."
        )

    if target == ContractorInvoice.Status.SENT:
        with transaction.atomic():
            invoice.status = target
            invoice.save(update_fields=['status', 'updated_at'])
            book_contractor_invoice(invoice, created_by=created_by)
    elif target == ContractorInvoice.Status.CANCELLED and current == ContractorInvoice.Status.SENT:
        with transaction.atomic():
            invoice.status = target
            invoice.save(update_fields=['status', 'updated_at'])
            void_source_entry(FinancialTransaction.SourceType.CONTRACTOR_INVOICE, invoice.id)
    else:
        invoice.status = target
        invoice.save(update_fields=['status', 'updated_at'])
    return invoice


def sync_overdue_statuses() -> dict:
    """
    Derived-state reconciliation (see module docstring): flip any billed
    invoice whose due_date has passed to OVERDUE. Returns the per-model
    counts updated so callers/testing can assert what changed.

    Idempotent and cheap: a single UPDATE per invoice model over the
    (status, due_date) index. Called from the invoice viewsets on read.
    """
    today = timezone.now().date()
    updated = {}

    for model in (ClientInvoice, SupplierInvoice, ContractorInvoice):
        updated[model._meta.db_table] = (
            model.objects
            .filter(status__in=_BILLED_STATUSES, due_date__lt=today)
            .update(status=model.Status.OVERDUE, updated_at=timezone.now())
        )

    return updated
