"""
Project-level financial roll-up (income + expenses) derived from the
invoicing + payments apps.

This is the "Confirm the project financial summary changes" step of the
invoice workflow: once a payment is allocated against a client/supplier/
contractor invoice that's linked to a project, this summary's
revenue.received / expenses.paid shift accordingly.

All monetary values are computed, never stored (same derivation
philosophy as ``payments.services.outstanding_balance`` and the invoice
total recalculators). Only invoice kinds with a ``project`` link count
toward a project -- supplier/contractor invoices can carry a project
(optional, like ClientInvoice already has).

Imports are intentionally deferred into the functions so this module
costs nothing at app startup and can't participate in any import cycle:
``invoicing``/``payments`` load before ``projects`` at runtime only if
they're imported first, and ``projects`` may load before both.
"""
from decimal import Decimal

from django.db.models import Sum

# Invoice statuses that count as "billed" for a financial position.
# DRAFT hasn't been issued yet and CANCELLED is void -- mirrors
# payments.services.outstanding_balance's _NO_BALANCE_STATUSES.
_BILLED = ('SENT', 'PARTIALLY_PAID', 'PAID', 'OVERDUE')


def _invoice_bucket(model, allocation_field, project):
    """
    For one invoice kind linked to ``project``: (total_billed,
    paid_allocated, outstanding). ``model`` is the invoice model and
    ``allocation_field`` the PaymentAllocation FK name pointing at it.
    """
    from payments.models import PaymentAllocation

    # _BILLED is indexed on status, so this stays a cheap filtered query
    # even with a few thousand invoices.
    invoices = model.objects.filter(project=project, status__in=_BILLED)
    total = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

    ids = list(invoices.values_list('pk', flat=True))
    if not ids:
        return total, Decimal('0.00'), total

    paid = (
        PaymentAllocation.objects.filter(**{f'{allocation_field}__in': ids})
        .aggregate(total=Sum('allocated_amount'))['total']
        or Decimal('0.00')
    )
    outstanding = max(total - paid, Decimal('0.00'))
    return total, paid, outstanding


def get_project_financial_summary(project):
    """
    Financial roll-up for ``project``:

    - revenue.*  -- client invoices: billed, received (allocated), outstanding
    - expenses.* -- supplier + contractor invoices: invoiced, paid, outstanding
    - net.*      -- accrued profit (billed - invoiced), cash position
                    (received - paid), total outstanding (AR + AP)

    Values are returned as "0.00"-style strings so the JSON keeps the
    decimal precision every other monetary field on this API exposes.
    """
    from invoicing.models import ClientInvoice, ContractorInvoice, SupplierInvoice

    revenue_total, revenue_received, revenue_outstanding = _invoice_bucket(
        ClientInvoice, 'client_invoice', project,
    )
    supplier_total, supplier_paid, supplier_outstanding = _invoice_bucket(
        SupplierInvoice, 'supplier_invoice', project,
    )
    contractor_total, contractor_paid, contractor_outstanding = _invoice_bucket(
        ContractorInvoice, 'contractor_invoice', project,
    )

    expense_total = supplier_total + contractor_total
    expense_paid = supplier_paid + contractor_paid
    expense_outstanding = supplier_outstanding + contractor_outstanding

    # Normalize to fixed two-decimal notation ("5000.00", not "5000") so
    # every monetary value in the payload shares one shape.
    strip = lambda d: format(d, '.2f')  # noqa: E731 -- keep the expression terse

    return {
        'project': {'id': str(project.id), 'code': project.code, 'name': project.name},
        'revenue': {
            'billed': strip(revenue_total),
            'received': strip(revenue_received),
            'outstanding': strip(revenue_outstanding),
        },
        'expenses': {
            'invoiced': strip(expense_total),
            'paid': strip(expense_paid),
            'outstanding': strip(expense_outstanding),
        },
        'net': {
            'accrual': strip(revenue_total - expense_total),
            'cash': strip(revenue_received - expense_paid),
            'outstanding': strip(revenue_outstanding + expense_outstanding),
        },
    }