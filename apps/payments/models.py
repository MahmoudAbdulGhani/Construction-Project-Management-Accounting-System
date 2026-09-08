"""
Models for the ``payments`` app -- Accounts Receivable & Accounts
Payable slice (CPMAS-35).

Implements ``Payment``, ``PaymentAllocation``, and ``Receipt``, matching
the ``payments`` / ``payment_allocations`` / ``receipts`` tables in the
approved schema (BRD 5.23 Payments, 5.24 Receipts).

This is the layer that settles both AP (``invoicing.SupplierInvoice``,
``invoicing.ContractorInvoice``) and AR (``invoicing.ClientInvoice``)
invoices: a single Payment can fund one or more PaymentAllocations, each
applied against exactly one invoice (any of the three sides), and
``payments.services.allocate_payment`` is the sole place an invoice's
status advances to PARTIALLY_PAID/PAID as a result. "Outstanding balance
is calculated from invoice totals minus payment allocations, not
maintained as a manually editable value" (BRD 5.23/5.24) is why neither
invoice model stores a balance column -- ``payments.services
.outstanding_balance`` computes it on read.

Note ``clients.models`` already has managed=False, read-only reflections
of ``payments``/``payment_allocations`` (``ClientPayment``,
``PaymentAllocation``) for the Clients app's own outstanding-balance
summary. Both mappings coexisting is safe: only this app's models are
managed=True and actually own migrations for these tables.
"""
import uuid

from django.db import models


class Payment(models.Model):
    """
    A single payment received from a client (INCOMING), or made to a
    supplier, employee, or contractor (OUTGOING).

    Only one of client/supplier is expected to be set, matching its
    direction (validated in payments.serializers, not a DB CHECK
    constraint -- the schema itself doesn't enforce this pairing at the
    column level, unlike PaymentAllocation's exactly-one-of CHECK below).
    """

    class Direction(models.TextChoices):
        INCOMING = 'INCOMING', 'Incoming'
        OUTGOING = 'OUTGOING', 'Outgoing'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    payment_number = models.CharField(max_length=100, unique=True)
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    # Schema types this as a plain VARCHAR with a CHECK(direction IN
    # (...)) rather than a named Postgres enum (unlike e.g. invoice/PO
    # status) -- TextChoices still gives the same validation at the
    # Django layer.
    direction = models.CharField(max_length=20, choices=Direction.choices, db_index=True)

    payment_method = models.CharField(max_length=50)

    # SET_NULL: losing the client/supplier reference shouldn't delete or
    # block a historical payment record.
    client = models.ForeignKey('clients.Client', on_delete=models.SET_NULL, blank=True, null=True, related_name='payments')
    supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.SET_NULL, blank=True, null=True, related_name='payments')
    # Employees and contractors are unmanaged reflections of existing
    # Supabase tables. UUID columns keep this managed ledger migration
    # independent while serializer validation guarantees valid payees.
    employee_id = models.UUIDField(blank=True, null=True, db_index=True)
    contractor_id = models.UUIDField(blank=True, null=True, db_index=True)

    reference = models.CharField(max_length=255, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    # PROTECT + db_column: same reasoning/naming quirk as
    # PurchaseOrder.created_by/Expense.created_by/FinancialTransaction
    # .created_by -- the live column has no _id suffix.
    created_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='payments_created',
        db_column='created_by',
    )

    # No updated_at in the schema -- a recorded payment is a ledger
    # entry, not something edited in place after creation (same
    # immutability reasoning as StockMovement/GoodsReceipt elsewhere in
    # this codebase).
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments'
        ordering = ['-payment_date', '-created_at']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return self.payment_number


class PaymentAllocation(models.Model):
    """
    How much of a Payment was applied against one specific invoice.

    Matches the ``payment_allocations`` table, including its CHECK
    constraint (mirrored in payments.serializers.PaymentAllocationSerializer
    .validate as defense in depth, same pattern as
    accounting.TransactionLine's mirrored CHECKs): exactly one of
    client_invoice/supplier_invoice/contractor_invoice must be set,
    never two, never none.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # CASCADE matches the live database's FK constraint exactly.
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='allocations')

    client_invoice = models.ForeignKey(
        'invoicing.ClientInvoice', on_delete=models.CASCADE, blank=True, null=True, related_name='payment_allocations',
    )
    supplier_invoice = models.ForeignKey(
        'invoicing.SupplierInvoice', on_delete=models.CASCADE, blank=True, null=True, related_name='payment_allocations',
    )
    contractor_invoice = models.ForeignKey(
        'invoicing.ContractorInvoice', on_delete=models.CASCADE, blank=True, null=True, related_name='payment_allocations',
    )

    allocated_amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        db_table = 'payment_allocations'
        # No natural ordering column in the schema -- see the same note
        # on purchasing.PurchaseOrderItem.Meta.ordering.
        ordering = ['id']
        verbose_name = 'Payment Allocation'
        verbose_name_plural = 'Payment Allocations'

    def __str__(self):
        invoice = self.client_invoice or self.supplier_invoice or self.contractor_invoice
        return f"{self.allocated_amount} of {self.payment.payment_number} -> {invoice}"


class Receipt(models.Model):
    """
    Proof-of-receipt for a Payment, in either direction. Matches the
    ``receipts`` table, including its UNIQUE(payment_id) constraint (a
    payment gets at most one receipt) -- enforced here via OneToOneField.

    Issued automatically whenever a payment is recorded (both INCOMING
    and OUTGOING -- money received from a client and money paid out are
    each receipted), and additionally available on demand through the
    receipts API for payments that predate auto-issuance.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='receipt')

    receipt_number = models.CharField(max_length=100, unique=True)
    receipt_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reference = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'receipts'
        ordering = ['-receipt_date', '-created_at']
        verbose_name = 'Receipt'
        verbose_name_plural = 'Receipts'

    def __str__(self):
        return self.receipt_number
