"""
Models for the ``invoicing`` app -- Supplier Invoices slice (CPMAS-32).

Implements ``SupplierInvoice`` and ``SupplierInvoiceItem``, matching the
``supplier_invoices`` / ``supplier_invoice_items`` tables in the approved
schema (BRD 5.16 Supplier Invoices).

Line-item and header monetary totals follow the same derived-value
pattern as ``purchasing.PurchaseOrder``/``PurchaseOrderItem`` (CPMAS-30):
computed by ``invoicing.services``, never accepted as direct API input
for the header. Unlike PO items, ``SupplierInvoiceItem.quantity``/
``unit_price`` are nullable in the schema -- a line can be a flat charge
(e.g. a service fee) with nothing to multiply -- so the derivation rule
is slightly different; see ``invoicing.services.compute_item_amounts``.

``SupplierInvoice.status`` matches the live Postgres enum
``invoice_status_enum`` (DRAFT, SENT, PARTIALLY_PAID, PAID, OVERDUE,
CANCELLED) exactly. Originally (CPMAS-32) only DRAFT/SENT/CANCELLED were
reachable, since PARTIALLY_PAID/PAID/OVERDUE depend on payment
allocations -- the Payments app didn't exist yet. CPMAS-35 (Accounts
Receivable & Accounts Payable) fills that gap: ``payments.services
.allocate_payment`` is now the sole place those three statuses get set,
for both this model and ``ClientInvoice`` below. Same pattern as
CPMAS-30 originally leaving PurchaseOrder.RECEIVED unreachable until
CPMAS-31's goods receiving filled it in.

``ClientInvoice``/``ClientInvoiceItem`` (added in CPMAS-35) are this
app's Accounts Receivable counterpart to SupplierInvoice's Accounts
Payable: an invoice billed TO a client rather than received FROM a
supplier. They match the ``client_invoices``/``client_invoice_items``
tables. Note ``clients.models`` already has managed=False, read-only
reflections of these same tables (``ClientInvoiceSummary``,
``ClientPayment`` etc.) -- those were built by a teammate purely so the
Clients app could compute an outstanding-balance summary without owning
the real create/update/status-transition logic, which is this ticket's
job. Both mappings coexisting is safe: only this app's models are
managed=True and actually own migrations for these tables.

``ContractorInvoice``/``ContractorInvoiceItem`` extend the Accounts
Payable side to contractor billing (a contractor's invoice for work,
settled the same way a supplier invoice is). They match the
``contractor_invoices``/``contractor_invoice_items`` tables. Because
``contractors.Contractor`` is a managed=False reflection of a live
Supabase table, the header stores ``contractor_id`` as a plain UUID
column (the live schema's REFERENCES constraint is enforced by the
database), validated against `Contractor` in the serializer -- the same
pattern as ``payments.Payment.employee_id``/``contractor_id``.
"""
import uuid

from django.db import models


class SupplierInvoice(models.Model):
    """
    An invoice received from a supplier, optionally tied to the
    purchase order it bills against and/or a project it's a cost of.

    Matches the ``supplier_invoices`` table. Has no ``created_by`` column
    in the schema (unlike PurchaseOrder), so unlike that model there's no
    users.User dependency here at all.
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent'
        PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
        PAID = 'PAID', 'Paid'
        OVERDUE = 'OVERDUE', 'Overdue'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # PROTECT: a supplier with invoice history shouldn't be deletable out
    # from under it -- deactivate (is_active=False) instead.
    supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.PROTECT, related_name='supplier_invoices')

    # PROTECT (not SET_NULL): the PO/goods-receipt/invoice three-way match
    # is exactly the kind of audit trail that shouldn't silently go null
    # if the PO is deleted -- also matches the live DB's plain REFERENCES
    # with no ON DELETE clause (defaults to NO ACTION, i.e. blocks the
    # delete), unlike Material.tax_rate/default_supplier elsewhere in
    # this codebase, which really are meant to gracefully null out.
    purchase_order = models.ForeignKey(
        'purchasing.PurchaseOrder', on_delete=models.PROTECT, blank=True, null=True,
        related_name='supplier_invoices',
    )

    # SET_NULL: an invoice can be a general charge with no project
    # attached (Project.project_id column added to match the AP/AR
    # linking pattern on ClientInvoice). ClientInvoice uses SET_NULL for
    # the same reason -- the project is reference context, not an audit
    # anchor.
    project = models.ForeignKey(
        'projects.Project', on_delete=models.SET_NULL, blank=True, null=True,
        related_name='supplier_invoices',
    )

    invoice_number = models.CharField(max_length=100, unique=True)
    invoice_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)

    # Derived from line items by invoicing.services.recalculate_invoice_totals.
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'supplier_invoices'
        ordering = ['-invoice_date', '-created_at']
        verbose_name = 'Supplier Invoice'
        verbose_name_plural = 'Supplier Invoices'

    def __str__(self):
        return self.invoice_number


class SupplierInvoiceItem(models.Model):
    """
    A single line on a supplier invoice.

    Matches the ``supplier_invoice_items`` table. ``quantity``/
    ``unit_price`` are nullable (unlike PurchaseOrderItem's, which are
    required) -- a line can be a flat charge with no quantity/price
    breakdown, e.g. a delivery fee or service charge. See
    ``invoicing.services.compute_item_amounts`` for how tax_amount/
    total_amount are derived in each case.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # CASCADE matches the live database's FK constraint exactly.
    supplier_invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name='items')

    # SET_NULL: optional in the schema -- a flat-charge line (e.g. a
    # delivery fee) may not reference any material at all.
    material = models.ForeignKey('inventory.Material', on_delete=models.SET_NULL, blank=True, null=True, related_name='supplier_invoice_items')

    description = models.TextField()
    quantity = models.DecimalField(max_digits=18, decimal_places=3, blank=True, null=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)

    # SET_NULL: same reasoning as Material.tax_rate elsewhere in this codebase.
    tax_rate = models.ForeignKey('taxes.TaxRate', on_delete=models.SET_NULL, blank=True, null=True, related_name='supplier_invoice_items')

    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'supplier_invoice_items'
        # No natural ordering column in the schema -- see the same note
        # on purchasing.PurchaseOrderItem.Meta.ordering.
        ordering = ['id']
        verbose_name = 'Supplier Invoice Item'
        verbose_name_plural = 'Supplier Invoice Items'

    def __str__(self):
        return f"{self.description} on {self.supplier_invoice.invoice_number}"


class ClientInvoice(models.Model):
    """
    An invoice billed to a client (Accounts Receivable), optionally tied
    to the project it bills against.

    Matches the ``client_invoices`` table. Unlike SupplierInvoice, there
    is no ``created_by`` column in the schema. ``unit`` (references the
    unbuilt ``units`` table -- multi-unit project sub-billing) is
    deferred and intentionally omitted, same reasoning as every other
    not-yet-built cross-app FK in this codebase (see e.g.
    Expense.employee/contractor).
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent'
        PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
        PAID = 'PAID', 'Paid'
        OVERDUE = 'OVERDUE', 'Overdue'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # PROTECT: a client with invoice history shouldn't be deletable out
    # from under it -- same reasoning as SupplierInvoice.supplier.
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='client_invoices')

    # SET_NULL: an invoice doesn't have to be tied to a specific project
    # (e.g. a miscellaneous client charge).
    project = models.ForeignKey('projects.Project', on_delete=models.SET_NULL, blank=True, null=True, related_name='client_invoices')

    invoice_number = models.CharField(max_length=100, unique=True)
    invoice_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)

    # Derived from line items by invoicing.services.recalculate_client_invoice_totals.
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0, blank=True, null=True)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'client_invoices'
        ordering = ['-invoice_date', '-created_at']
        verbose_name = 'Client Invoice'
        verbose_name_plural = 'Client Invoices'

    def __str__(self):
        return self.invoice_number


class ContractorInvoice(models.Model):
    """
    An invoice received from a contractor for work done (Accounts
    Payable), settled through payment allocations exactly like a
    SupplierInvoice -- an OUTGOING payment to the same contractor ends up
    advancing this invoice to PARTIALLY_PAID/PAID and reducing its
    outstanding balance (see payments.services.allocate_payment).

    Matches the ``contractor_invoices`` table. ``contractor_id`` is a
    plain UUID column rather than a real FK, because
    ``contractors.Contractor`` is a managed=False reflection of a live
    Supabase table -- the live schema still REFERENCES contractors(id)
    (enforced by the database), and the serializer validates the id.
    Unlike SupplierInvoice there is no purchase_order (a contractor
    invoice bills work done, not goods received against a PO), but there
    is an optional project link so the same project-level financial
    roll-up works for every invoice kind.
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent'
        PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
        PAID = 'PAID', 'Paid'
        OVERDUE = 'OVERDUE', 'Overdue'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    contractor_id = models.UUIDField(db_index=True)

    # SET_NULL: same reasoning as SupplierInvoice.project -- a contractor
    # invoice can be a general charge with no project attached, and the
    # project is reference context, not an audit anchor.
    project = models.ForeignKey(
        'projects.Project', on_delete=models.SET_NULL, blank=True, null=True,
        related_name='contractor_invoices',
    )

    invoice_number = models.CharField(max_length=100, unique=True)
    invoice_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)

    # Derived from line items by invoicing.services.recalculate_contractor_invoice_totals.
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contractor_invoices'
        ordering = ['-invoice_date', '-created_at']
        verbose_name = 'Contractor Invoice'
        verbose_name_plural = 'Contractor Invoices'

    def __str__(self):
        return self.invoice_number


class ContractorInvoiceItem(models.Model):
    """
    A single line on a contractor invoice.

    Matches the ``contractor_invoice_items`` table. Like
    SupplierInvoiceItem, ``quantity``/``unit_price`` are nullable -- a
    contractor line can be a flat charge (e.g. a fixed lump-sum works
    item) or a measured quantity at a rate. See
    ``invoicing.services.compute_contractor_item_amounts`` for how
    tax_amount/total_amount are derived in each case.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # CASCADE matches the live database's FK constraint exactly.
    contractor_invoice = models.ForeignKey(ContractorInvoice, on_delete=models.CASCADE, related_name='items')

    description = models.TextField()
    quantity = models.DecimalField(max_digits=18, decimal_places=3, blank=True, null=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)

    # SET_NULL: same reasoning as SupplierInvoiceItem.tax_rate.
    tax_rate = models.ForeignKey('taxes.TaxRate', on_delete=models.SET_NULL, blank=True, null=True, related_name='contractor_invoice_items')

    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'contractor_invoice_items'
        # No natural ordering column in the schema -- see the same note
        # on purchasing.PurchaseOrderItem.Meta.ordering.
        ordering = ['id']
        verbose_name = 'Contractor Invoice Item'
        verbose_name_plural = 'Contractor Invoice Items'

    def __str__(self):
        return f"{self.description} on {self.contractor_invoice.invoice_number}"


class ClientInvoiceItem(models.Model):
    """
    A single line on a client invoice.

    Matches the ``client_invoice_items`` table. Unlike
    SupplierInvoiceItem, ``quantity``/``unit_price`` are both required
    (NOT NULL in the schema) -- a client invoice line always bills a
    quantity of something at a price, there is no flat-charge case here.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # CASCADE matches the live database's FK constraint exactly.
    client_invoice = models.ForeignKey(ClientInvoice, on_delete=models.CASCADE, related_name='items')

    description = models.TextField()
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0, blank=True, null=True)

    # SET_NULL: same reasoning as SupplierInvoiceItem.tax_rate.
    tax_rate = models.ForeignKey('taxes.TaxRate', on_delete=models.SET_NULL, blank=True, null=True, related_name='client_invoice_items')

    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'client_invoice_items'
        # No natural ordering column in the schema -- see the same note
        # on purchasing.PurchaseOrderItem.Meta.ordering.
        ordering = ['id']
        verbose_name = 'Client Invoice Item'
        verbose_name_plural = 'Client Invoice Items'

    def __str__(self):
        return f"{self.description} on {self.client_invoice.invoice_number}"
