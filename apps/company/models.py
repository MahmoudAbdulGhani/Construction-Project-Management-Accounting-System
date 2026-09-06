"""
Models for the ``company`` app -- Company Administration.

Two models live here. ``CompanyProfile`` is a read-mostly mapping onto the shared
``company_details`` table (schema line 19: name, registration_number,
address, phone, email, website, currency, tax_information, logo,
created_at, updated_at). This table stores the single system-wide company
identity used on invoices, receipts, reports, and official documents
(Company profile / Administration screen).

``managed = False``: the table already exists in Supabase and isn't owned
by this Django app -- same reflection style as ``clients``/``users``/
``projects`` read-mostly mappings elsewhere in the codebase.

``currency`` is a UUID NOT NULL column with no FKs to a currencies table
in the schema (none is provisioned), matching the cross-cutting decision
that the system currency is fixed at USD. The web form never writes it;
``DEFAULT_CURRENCY_UUID`` is only used when the very first row must be
created (a real deployment will have the seeded row already).
"""
import uuid

from decimal import Decimal

from django.db import models


class CompanyProfile(models.Model):
    """The single company identity record (``company_details`` table)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255)
    registration_number = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=255, blank=True, null=True)
    website = models.CharField(max_length=255, blank=True, null=True)
    currency = models.UUIDField()
    tax_information = models.TextField(blank=True, null=True)
    logo = models.CharField(max_length=500, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "company_details"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name or "Company profile"

    @property
    def initials(self):
        """Up to two letters for the logo placeholder chip (e.g. "CC")."""
        words = [word for word in (self.name or "").split() if word]
        return "".join(word[0] for word in words[:2]).upper() or "CC"


# Fixed system-wide currency (USD). See module docstring: no currencies
# table exists in the approved schema; the value is only needed to satisfy
# company_details.currency NOT NULL when a deployment has no seed row.
DEFAULT_CURRENCY_UUID = uuid.UUID("2e01d3b0-9c82-4f1e-8f7f-5c1d6f1f0000")


class FinancialSettings(models.Model):
    """
    Single-row rules for the Financial settings tab (Chart of accounts +
    Financial rules pane).

    Unlike the reflected pre-existing tables (``CompanyProfile`` is
    unmanaged), ``financial_settings`` is a *new* table Django owns via the
    ``apps/company`` migrations -- same pattern as ``taxes``/``payments``.

    The row always carries id = 1: there is never more than one record. The
    API layer creates it on first read (get_or_create) so the rest of the
    system can assume it exists.
    """

    # Fixed primary key keeps the singleton row at id=1.
    SINGLETON_PK = 1

    id = models.PositiveIntegerField(
        primary_key=True, default=SINGLETON_PK, editable=False
    )

    # Fiscal calendar: month + day on which the accounting year begins.
    fiscal_year_start_month = models.PositiveSmallIntegerField(default=1)
    fiscal_year_start_day = models.PositiveSmallIntegerField(default=1)

    # Period locking: when enabled, financial periods are considered closed
    # ``period_lock_after_days`` days after a period close. 0 / null = never
    # locked automatically.
    lock_financial_periods = models.BooleanField(default=True)
    period_lock_after_days = models.IntegerField(null=True, blank=True, default=30)

    # Billing defaults applied to new purchase orders and invoices.
    default_tax_rate = models.ForeignKey(
        "taxes.TaxRate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Default tax rate",
    )
    default_payment_terms = models.CharField(
        max_length=20,
        choices=[
            ("NET30", "Net 30"),
            ("NET60", "Net 60"),
            ("IMMEDIATE", "Immediate"),
        ],
        default="NET30",
    )

    # Retention: percentage withheld from subcontractor payments.
    retention_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("5.00")
    )

    # Budget control: percentage that triggers an over-budget alert.
    budget_alert_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("90.00")
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "financial_settings"
        verbose_name = "Financial settings"
        verbose_name_plural = "Financial settings"
        ordering = ["id"]

    def __str__(self):
        return "Financial rules"