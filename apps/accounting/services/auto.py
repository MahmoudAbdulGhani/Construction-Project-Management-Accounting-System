"""
Auto-generated journal entry service for the ``accounting`` app.

This module is the single boundary between the operational documents
(Expense, ClientInvoice, SupplierInvoice, ContractorInvoice, Payment) and
the general ledger. Operational apps never create FinancialTransaction /
TransactionLine rows directly; they call the ``book_*`` helpers here that
own account resolution, line construction, number generation, source-pair
idempotency, posting, and (where needed) void-and-rebook. Phase 1-3 of the
GL integration wire each document's transition into those helpers.

Core primitive: ``post_source_entry`` -- create a balanced journal entry
tied to one (source_type, source_id) pair and post it immediately. Auto
entries never sit in DRAFT; they go straight to POSTED. Re-invoking it for
a pair that already has a non-voided entry raises ``AccountingError``; the
``book_*`` wrappers decide how to treat that (no-op, or void-and-recreate
for allocations that change).
"""
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import current_request
from users.models import User

from ..models import Account, FinancialTransaction, TransactionLine
from .core import post_transaction, transaction_totals, void_transaction


class AccountingError(ValidationError):
    """
    Raised when an automatic journal entry cannot be created (missing
    account, unbalanced lines, no acting user, or a source pair already
    booked). Subclasses django's ValidationError so it surfaces as a 400
    through DRF when raised inside a request handler.
    """


def get_account(code, purpose):
    """
    Resolve the chart-of-accounts entry for ``code``, or raise a clear,
    actionable error explaining what it was needed for (e.g. "expense
    category ...", "client invoice revenue"). Raising makes the caller's
    enclosing atomic block roll back, so an unconfigured account never
    produces a half-transitioned document.
    """
    try:
        return Account.objects.get(code=code)
    except Account.DoesNotExist:
        raise AccountingError(
            f"No chart-of-accounts entry with code {code} is configured for {purpose}."
        )


def generate_transaction_number(transaction_date=None) -> str:
    """
    Next GL journal number as ``GL-<year>-<seq>``, echoing the INV-/PAY-
    numbering schemes used by the invoicing/payments apps. Not unique-safe
    on its own -- callers wrap the INSERT in a retry loop.
    """
    from django.utils.dateparse import parse_date

    if isinstance(transaction_date, str):
        parsed = parse_date(transaction_date)
        year = parsed.year if parsed else timezone.now().date().year
    elif transaction_date is not None:
        year = transaction_date.year
    else:
        year = timezone.now().date().year
    prefix = f"GL-{year}-"
    highest = 0
    for number in FinancialTransaction.objects.filter(transaction_number__startswith=prefix).values_list('transaction_number', flat=True):
        match = re.search(r"-(\d+)$", number)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:04d}"


def resolve_actor(created_by=None):
    """
    Resolve the user an auto-generated entry is attributed to: the explicit
    ``created_by`` when given, else the actor captured by the audit
    request context (see ``audit.services.current_request``). Raises
    AccountingError when neither is available -- auto entries are never
    created without an accountable actor.
    """
    if created_by is not None:
        return created_by
    request = current_request()
    user = getattr(request, 'user', None) if request is not None else None
    if user is None or getattr(user, 'is_anonymous', True):
        raise AccountingError(
            "Cannot book an automatic journal entry without an acting user."
        )
    if isinstance(user, User):
        return user
    resolved = User.objects.filter(pk=getattr(user, 'pk', None)).first()
    if resolved is None:
        raise AccountingError(
            "Cannot attribute an automatic journal entry to a non-existent user."
        )
    return resolved


def existing_source_entry(source_type, source_id) -> FinancialTransaction | None:
    """
    The live (non-voided) journal entry booked for a source pair, if any.
    VOIDED entries are ignored so a source can be rebooked after voiding --
    the partial unique constraint excludes VOIDED for the same reason.
    """
    return FinancialTransaction.objects.filter(
        source_type=source_type, source_id=source_id,
    ).exclude(status=FinancialTransaction.Status.VOIDED).first()


def post_source_entry(*, source_type, source_id, transaction_date, description,
                      reference=None, project=None, client=None, supplier=None,
                      lines, created_by=None) -> FinancialTransaction:
    """
    Central auto-booking primitive: create and immediately post one balanced
    journal entry for a (source_type, source_id) pair.

    ``lines`` is a sequence of dicts: ``{account, debit, credit,
    [description], [project]}``, where ``account`` is an Account instance
    (higher-level ``book_*`` helpers resolve them by code via get_account).
    Debit/credit are Decimals; the entry must balance (BR 12.7), and every
    line must be one-sided and nonzero.

    Raises AccountingError if the source pair already has a non-voided
    entry, if the lines are unbalanced or invalid, or if no acting user can
    be resolved. Returns the POSTED FinancialTransaction.
    """
    existing = existing_source_entry(source_type, source_id)
    if existing is not None:
        raise AccountingError(
            f"A journal entry for this {source_type} already exists "
            f"({existing.transaction_number})."
        )

    if not lines:
        raise AccountingError("Cannot book a journal entry with no lines.")

    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')
    normalized = []
    for raw in lines:
        account = raw.get('account')
        if account is None:
            raise AccountingError("Each journal line requires an account.")
        debit = raw.get('debit') or Decimal('0.00')
        credit = raw.get('credit') or Decimal('0.00')
        if debit < 0 or credit < 0:
            raise AccountingError("Debit and credit cannot be negative.")
        if debit > 0 and credit > 0:
            raise AccountingError("A line cannot have both a debit and a credit -- it's one or the other.")
        if debit == 0 and credit == 0:
            raise AccountingError("A line must have either a debit or a credit greater than zero.")
        total_debit += debit
        total_credit += credit
        normalized.append({
            'account': account,
            'debit': debit,
            'credit': credit,
            'description': raw.get('description'),
            'project': raw.get('project'),
        })

    if total_debit != total_credit:
        raise AccountingError(
            f"Cannot book an unbalanced entry: total debits ({total_debit}) "
            f"!= total credits ({total_credit})."
        )

    actor = resolve_actor(created_by)

    for _ in range(3):
        number = generate_transaction_number(transaction_date)
        try:
            with transaction.atomic():
                header = FinancialTransaction.objects.create(
                    transaction_number=number,
                    transaction_date=transaction_date,
                    description=description,
                    reference=reference,
                    project=project,
                    client=client,
                    supplier=supplier,
                    created_by=actor,
                    source_type=source_type,
                    source_id=source_id,
                )
                TransactionLine.objects.bulk_create(
                    TransactionLine(
                        transaction=header,
                        account=line['account'],
                        description=line['description'],
                        debit=line['debit'],
                        credit=line['credit'],
                        project=line['project'],
                    )
                    for line in normalized
                )
                return post_transaction(header)
        except IntegrityError:
            # Another writer won the race on transaction_number (or on the
            # source pair); regenerate and retry. A source-pair race can
            # only burn retries -- the DB partial unique constraint blocks
            # the duplicate outright.
            continue
    raise AccountingError("Could not allocate a unique journal entry number; please retry.")


def book_expense(expense) -> FinancialTransaction:
    """
    Phase 1 (CPMAS-34): recognize a paid Expense in the GL.

    ``expenses.services.transition_status`` calls this inside its own
    atomic block the moment a PENDING->APPROVED->PAID expense is marked
    PAID. Journals DR -> the expense category's chart-of-accounts entry
    and CR -> Cash (1000) for ``amount + tax_amount`` -- an Expense's only
    money columns (BRD 5.20: no line items).

    The category MUST have an account configured (clear contract for
    paying an expense disappears the moment one isn't -- a paid expense
    with nowhere to land is exactly the half-transitioned state the
    enclosing atomic block exists to roll back); a missing one raises
    AccountingError, which rolls the caller's transaction back and leaves
    the expense APPROVED instead of PAID.
    """
    category = expense.category
    if category.account is None:
        raise AccountingError(
            f'The expense category "{category.name}" does not have an '
            "accounting account configured."
        )
    total = expense.amount + expense.tax_amount
    if total <= 0:
        raise AccountingError("Cannot book an expense with a zero or negative total.")
    cash = get_account('1000', 'the cash side of a paid expense')
    return post_source_entry(
        source_type=FinancialTransaction.SourceType.EXPENSE,
        source_id=expense.id,
        transaction_date=expense.expense_date,
        description=f"Expense: {expense.description}",
        project=expense.project,
        client=None,
        supplier=expense.supplier,
        created_by=getattr(expense, 'created_by', None),
        lines=[
            {'account': category.account, 'debit': total, 'project': expense.project},
            {'account': cash, 'credit': total, 'project': expense.project},
        ],
    )


def void_source_entry(source_type, source_id) -> FinancialTransaction | None:
    """
    Void the live (non-voided) journal entry booked for a source pair, if
    any, and return it. A no-op for pairs that were never booked (e.g.
    cancelling an invoice straight from DRAFT). Used when an operational
    document that was already recognized is cancelled -- the original
    posted lines stay visible but flagged invalid, and the partial unique
    constraint excludes VOIDED so cancellation can never be followed by a
    double-book, only (where the workflow allows) a fresh entry.
    """
    entry = existing_source_entry(source_type, source_id)
    if entry is not None:
        void_transaction(entry)
    return entry


def _invoice_lines(lines):
    """Drop zero-value lines so post_source_entry's nonzero rule is only
    reached with amounts that actually move money (e.g. a client invoice
    with no tax has no tax-payable credit)."""
    return [line for line in lines if line.get('debit') or line.get('credit')]


def book_supplier_invoice(invoice, *, created_by=None) -> FinancialTransaction | None:
    """
    Phase 2 (CPMAS-34/BR 12.x): recognize a SupplierInvoice when it is
    sent (billed). Journals DR -> Cost of Construction (5000) and
    CR -> Accounts Payable (2000) for the invoice's total_amount (which
    already includes its tax, per BRD 5.16). Called by
    ``invoicing.services.transition_status`` inside its atomic block.
    """
    total = invoice.total_amount
    if total <= 0:
        # A zero-total invoice bills nothing and recognizes nothing --
        # there is no AP liability to record, so the transition proceeds
        # with no journal entry (pre-GL behavior always allowed sending
        # an itemless invoice).
        return None
    cost = get_account('5000', 'the cost side of a supplier invoice')
    payable = get_account('2000', 'the accounts payable side of a supplier invoice')
    return post_source_entry(
        source_type=FinancialTransaction.SourceType.SUPPLIER_INVOICE,
        source_id=invoice.id,
        transaction_date=invoice.invoice_date,
        description=f"Supplier invoice: {invoice.invoice_number}",
        project=invoice.project,
        supplier=invoice.supplier,
        created_by=created_by,
        lines=[
            {'account': cost, 'debit': total, 'project': invoice.project},
            {'account': payable, 'credit': total, 'project': invoice.project},
        ],
    )


def book_contractor_invoice(invoice, *, created_by=None) -> FinancialTransaction | None:
    """
    Phase 2: recognize a ContractorInvoice when sent -- the same AP
    treatment as book_supplier_invoice (DR Cost of Construction 5000 /
    CR Accounts Payable 2000 for total_amount, tax included). The header
    keeps no contractor FK (contractors is a managed=False reflection, and
    contractor_id on ContractorInvoice is a plain UUID column), so the
    invoice number in the description -- and the source_id, which is the
    invoice's own id -- are what tie the entry back to the contractor
    billing record.
    """
    total = invoice.total_amount
    if total <= 0:
        return None
    cost = get_account('5000', 'the cost side of a contractor invoice')
    payable = get_account('2000', 'the accounts payable side of a contractor invoice')
    return post_source_entry(
        source_type=FinancialTransaction.SourceType.CONTRACTOR_INVOICE,
        source_id=invoice.id,
        transaction_date=invoice.invoice_date,
        description=f"Contractor invoice: {invoice.invoice_number}",
        project=invoice.project,
        created_by=created_by,
        lines=[
            {'account': cost, 'debit': total, 'project': invoice.project},
            {'account': payable, 'credit': total, 'project': invoice.project},
        ],
    )


def book_client_invoice(invoice, *, created_by=None) -> FinancialTransaction | None:
    """
    Phase 2: recognize a ClientInvoice when sent. Journals
    DR -> Accounts Receivable (1100) for total_amount, split across
    CR -> Construction Revenue (4000) for the pre-tax portion and
    CR -> Tax Payable (2100) for the tax portion -- the Sales-tax-style
    split a client invoice implies (BRD 5.16/5.22). Zero-value credits
    (an untaxed invoice) are dropped so every line moves money.
    """
    total = invoice.total_amount
    if total <= 0:
        return None
    tax = invoice.tax_amount or Decimal('0.00')
    receivable = get_account('1100', 'the accounts receivable side of a client invoice')
    revenue = get_account('4000', 'the revenue side of a client invoice')
    tax_payable = get_account('2100', 'the tax payable side of a client invoice')
    return post_source_entry(
        source_type=FinancialTransaction.SourceType.CLIENT_INVOICE,
        source_id=invoice.id,
        transaction_date=invoice.invoice_date,
        description=f"Client invoice: {invoice.invoice_number}",
        project=invoice.project,
        client=invoice.client,
        created_by=created_by,
        lines=_invoice_lines([
            {'account': receivable, 'debit': total, 'project': invoice.project},
            {'account': revenue, 'credit': total - tax, 'project': invoice.project},
            {'account': tax_payable, 'credit': tax, 'project': invoice.project},
        ]),
    )


def book_payment(payment, *, created_by=None) -> FinancialTransaction | None:
    """
    Phase 3 (CPMAS-34): recognize a Payment in the general ledger from
    its current allocation set.

    INCOMING payments allocated to client invoices settle the receivable:
    DR Cash (1000) / CR Accounts Receivable (1100) per allocation.
    OUTGOING payments allocated to supplier/contractor invoices settle the
    payable: DR Accounts Payable (2000) / CR Cash (1000) per allocation.
    Each journal line carries its allocation's invoice project, so a
    single payment spanning several projects rolls up correctly under the
    per-line project dimension.

    Called from payments.services.allocate_payment, which first voids any
    existing PAYMENT entry (see void_source_entry) so the live journal
    always mirrors the payment's real allocation state: a changed
    allocation set makes the old entry VOIDED (its posted lines remain in
    the ledger as the prior record) and books a fresh POSTED one. A
    payment with no allocations yet -- e.g. an employee wage payment,
    which never allocates -- recognizes nothing.
    """
    projections = list(payment.allocations.select_related(
        'client_invoice', 'client_invoice__project',
        'supplier_invoice', 'supplier_invoice__project',
        'contractor_invoice', 'contractor_invoice__project',
    ))
    if not projections:
        return None

    cash = get_account('1000', 'the cash side of a payment')
    if payment.direction == 'INCOMING':
        book_account = get_account('1100', 'the accounts receivable side of an incoming payment')
    else:
        book_account = get_account('2000', 'the accounts payable side of an outgoing payment')

    lines = []
    for allocation in projections:
        invoice = allocation.client_invoice or allocation.supplier_invoice or allocation.contractor_invoice
        amount = allocation.allocated_amount
        if amount <= 0:
            continue
        project = invoice.project if invoice is not None else None
        if payment.direction == 'INCOMING':
            lines.extend([
                {'account': cash, 'debit': amount, 'project': project},
                {'account': book_account, 'credit': amount, 'project': project},
            ])
        else:
            lines.extend([
                {'account': book_account, 'debit': amount, 'project': project},
                {'account': cash, 'credit': amount, 'project': project},
            ])

    if not lines:
        raise AccountingError("Cannot book a payment with no allocation lines.")

    return post_source_entry(
        source_type=FinancialTransaction.SourceType.PAYMENT,
        source_id=payment.id,
        transaction_date=payment.payment_date,
        description=f"Payment: {payment.payment_number}",
        reference=payment.reference,
        project=None,
        client=payment.client,
        supplier=payment.supplier,
        created_by=created_by,
        lines=lines,
    )