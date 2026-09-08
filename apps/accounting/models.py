"""
Models for the ``accounting`` app -- Accounting / Financial Transactions
slice (CPMAS-34).

Implements ``Account`` (chart of accounts), ``FinancialTransaction``
(journal entry header), and ``TransactionLine`` (journal entry line),
matching the ``accounts`` / ``financial_transactions`` /
``transaction_lines`` tables in the approved schema (BRD 5.22 Accounting
/ Financial Transactions).

Business rule 12.7 ("Financial transactions MUST maintain balanced
entries -- Total Debits = Total Credits") is enforced by
``accounting.services.post_transaction``: a transaction can only move
from DRAFT to POSTED if its lines' debits and credits sum equal. There
is no stored total_debits/total_credits column on FinancialTransaction
-- the schema doesn't define one, and unlike PurchaseOrder/
SupplierInvoice's subtotal/tax/total, nothing else needs to read a
cached balance, so it's simply computed at post time rather than
maintained as a derived field.

This is the first accounting/purchasing/invoicing-family ticket in this
codebase with zero deferred foreign keys: project, client, and supplier
are all real models by this point (CPMAS-47/CPMAS-32-era work), and
Account is defined in this same app.
"""
import uuid

from django.core.exceptions import ValidationError
from django.db import models


class Account(models.Model):
    """
    A general ledger account (e.g. "1000 - Cash", "4000 - Construction
    Revenue"), optionally nested under a parent account for a chart-of-
    accounts hierarchy.

    Matches the ``accounts`` table in the approved schema.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # PROTECT: deleting a parent account out from under its children
    # would silently orphan (or, with CASCADE, delete) part of the chart
    # of accounts -- re-parenting should be an explicit, deliberate step.
    parent_account = models.ForeignKey(
        'self', on_delete=models.PROTECT, blank=True, null=True, related_name='child_accounts',
    )

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)

    # Free text per the schema (Asset/Liability/Equity/Revenue/Expense
    # etc.) rather than a fixed choices list -- BRD 5.22 lists the
    # standard categories but the schema doesn't constrain this column
    # to an enum, unlike e.g. movement_type or the various status enums.
    account_type = models.CharField(max_length=30)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'accounts'
        ordering = ['code']
        verbose_name = 'Account'
        verbose_name_plural = 'Accounts'

    def __str__(self):
        return f"{self.code} - {self.name}"


class FinancialTransaction(models.Model):
    """
    A journal entry header. Matches the ``financial_transactions`` table.

    ``status`` matches the live Postgres enum ``transaction_status_enum``
    (DRAFT, POSTED, VOIDED) exactly. Only ever changed through
    ``accounting.services.post_transaction``/``void_transaction`` -- see
    those functions' docstrings for why a raw status PATCH isn't exposed.

    ``source_type`` / ``source_id`` optionally link a journal entry back to
    the operational document that generated it (a ClientInvoice,
    SupplierInvoice, ContractorInvoice, Payment, or Expense). Manual entries
    keep both NULL; system-generated entries carry both, and the pair must
    be unique among non-voided entries (see Meta.constraints) so a document
    can never be booked twice into the live ledger. Managed by
    ``accounting.services.auto`` -- operational apps never touch these
    directly.
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        POSTED = 'POSTED', 'Posted'
        VOIDED = 'VOIDED', 'Voided'

    class SourceType(models.TextChoices):
        CLIENT_INVOICE = 'CLIENT_INVOICE', 'Client Invoice'
        SUPPLIER_INVOICE = 'SUPPLIER_INVOICE', 'Supplier Invoice'
        CONTRACTOR_INVOICE = 'CONTRACTOR_INVOICE', 'Contractor Invoice'
        PAYMENT = 'PAYMENT', 'Payment'
        EXPENSE = 'EXPENSE', 'Expense'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    transaction_number = models.CharField(max_length=100, unique=True)
    transaction_date = models.DateField()
    description = models.TextField()
    reference = models.CharField(max_length=255, blank=True, null=True)

    # Source tracking (BRD 5.22: financial transactions carry the document
    # they came from). Both NULL for manual entries; both set -- and unique
    # among non-voided entries -- for system-generated ones. source_id is
    # the FKs' UUID of the generating document; there's deliberately no
    # generic ContentType-style polymorphic reference, mirroring how each
    # operational app already has its own journal-facing columns.
    source_type = models.CharField(max_length=50, choices=SourceType.choices, blank=True, null=True, db_index=True)
    source_id = models.UUIDField(blank=True, null=True)

    # All three dimension FKs are optional in the schema -- a journal
    # entry doesn't have to relate to a specific project/client/supplier
    # (e.g. a general ledger adjustment). SET_NULL: losing one of these
    # references shouldn't delete or block a posted financial record.
    project = models.ForeignKey('projects.Project', on_delete=models.SET_NULL, blank=True, null=True, related_name='financial_transactions')
    client = models.ForeignKey('clients.Client', on_delete=models.SET_NULL, blank=True, null=True, related_name='financial_transactions')
    supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.SET_NULL, blank=True, null=True, related_name='financial_transactions')

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)

    # PROTECT: who created a journal entry is part of its audit trail
    # (same reasoning as PurchaseOrder.created_by, CPMAS-30) and
    # shouldn't be erasable by deleting their user record. db_column
    # ='created_by': same naming quirk as PurchaseOrder/Expense -- the
    # live column has no _id suffix.
    created_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='financial_transactions_created',
        db_column='created_by',
    )

    posted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'financial_transactions'
        ordering = ['-transaction_date', '-created_at']
        verbose_name = 'Financial Transaction'
        verbose_name_plural = 'Financial Transactions'
        constraints = [
            models.UniqueConstraint(
                fields=['source_type', 'source_id'],
                name='uniq_source_pair',
                condition=models.Q(
                    source_type__isnull=False,
                    source_id__isnull=False,
                ) & ~models.Q(status='VOIDED'),
            ),
        ]

    def __str__(self):
        return self.transaction_number

    def clean(self):
        super().clean()
        if (self.source_type is None) != (self.source_id is None):
            raise ValidationError(
                "source_type and source_id must both be set on a system-generated "
                "journal entry, or both be blank on a manual entry."
            )


class TransactionLine(models.Model):
    """
    A single debit or credit line on a journal entry.

    Matches the ``transaction_lines`` table, including its two CHECK
    constraints (mirrored in ``accounting.serializers.TransactionLineSerializer
    .validate`` as defense in depth, not just relied on at the DB layer):
    debit/credit must both be >= 0, and a line can't have both a debit
    and a credit at once (it's one or the other).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # CASCADE matches the live database's FK constraint exactly: deleting
    # a journal entry deletes its lines with it (a header without any of
    # its own lines is a data-integrity nonsense state, not something to
    # protect against by blocking the delete) -- same reasoning as
    # PurchaseOrderItem.purchase_order (CPMAS-30).
    transaction = models.ForeignKey(FinancialTransaction, on_delete=models.CASCADE, related_name='lines')

    # PROTECT: an account referenced by an existing journal line
    # shouldn't be deletable out from under it.
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transaction_lines')

    description = models.TextField(blank=True, null=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # Optional "project dimension" per the schema -- lets a single
    # journal entry span lines touching different projects (e.g. an
    # allocation), even though the entry header itself has only one
    # (optional) project reference.
    project = models.ForeignKey('projects.Project', on_delete=models.SET_NULL, blank=True, null=True, related_name='transaction_lines')

    class Meta:
        db_table = 'transaction_lines'
        # No natural ordering column in the schema -- see the same note
        # on purchasing.PurchaseOrderItem.Meta.ordering.
        ordering = ['id']
        verbose_name = 'Transaction Line'
        verbose_name_plural = 'Transaction Lines'

    def __str__(self):
        side = f"Dr {self.debit}" if self.debit else f"Cr {self.credit}"
        return f"{side} {self.account} on {self.transaction.transaction_number}"
