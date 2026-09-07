"""
Ledger primitives for the ``accounting`` app that must not live in a
serializer or viewset.

The single most important rule in this app: BR 12.7 / BRD 5.22 --
"Financial transactions MUST maintain balanced entries (Total Debits =
Total Credits)". Enforced here, not in a serializer, so it can't be
bypassed by any future code path that touches FinancialTransaction.status
directly.

Auto-generated entries (see ``accounting.services.auto``) go through the
same ``post_transaction`` gate; there is deliberately no separate "auto"
posting path that could skip the balance check.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import FinancialTransaction


def transaction_totals(financial_transaction: FinancialTransaction) -> tuple[Decimal, Decimal]:
    """Return (total_debit, total_credit) across a transaction's lines."""
    totals = financial_transaction.lines.aggregate(
        total_debit=Sum('debit'), total_credit=Sum('credit'),
    )
    return (
        totals['total_debit'] or Decimal('0.00'),
        totals['total_credit'] or Decimal('0.00'),
    )


@db_transaction.atomic
def post_transaction(financial_transaction: FinancialTransaction) -> FinancialTransaction:
    """
    Move a FinancialTransaction from DRAFT to POSTED.

    Only allowed if:
    - it currently is DRAFT (POSTED/VOIDED are terminal for this action --
      you don't "re-post" an already-posted or voided entry);
    - it has at least one line (an empty journal entry has nothing to
      balance and isn't a real transaction);
    - total debits equal total credits across its lines (BR 12.7).

    Sets posted_at to now on success.
    """
    if financial_transaction.status != FinancialTransaction.Status.DRAFT:
        raise ValidationError(
            f"Cannot post a financial transaction that is {financial_transaction.get_status_display()}."
        )

    if not financial_transaction.lines.exists():
        raise ValidationError("Cannot post a financial transaction with no lines.")

    total_debit, total_credit = transaction_totals(financial_transaction)
    if total_debit != total_credit:
        raise ValidationError(
            f"Cannot post an unbalanced transaction: total debits ({total_debit}) "
            f"!= total credits ({total_credit})."
        )

    financial_transaction.status = FinancialTransaction.Status.POSTED
    financial_transaction.posted_at = timezone.now()
    financial_transaction.save(update_fields=['status', 'posted_at', 'updated_at'])
    return financial_transaction


def void_transaction(financial_transaction: FinancialTransaction) -> FinancialTransaction:
    """
    Move a FinancialTransaction to VOIDED, from DRAFT or POSTED.

    Voiding a posted entry doesn't undo its effects programmatically --
    there's no balance/reporting layer yet (that's the Reports ticket,
    unbuilt) for this to reverse. It just flags the entry as no longer
    valid; a real correction is a new, separate journal entry, same as
    the ledger-immutability pattern used for StockMovement/GoodsReceipt
    elsewhere in this codebase. For auto-generated entries this is exactly
    how a cancelled invoice is handled: the original posted lines stay
    visible but are flagged invalid, and the source pair is released
    (VOIDED entries are excluded from the partial unique constraint) so the
    document can never be booked twice into the live ledger.
    """
    if financial_transaction.status == FinancialTransaction.Status.VOIDED:
        raise ValidationError("This financial transaction is already voided.")

    financial_transaction.status = FinancialTransaction.Status.VOIDED
    financial_transaction.save(update_fields=['status', 'updated_at'])
    return financial_transaction