"""
Business logic for the ``expenses`` app that must not live in a
serializer or viewset.

Expense.status only ever changes through transition_status, validated
against ALLOWED_TRANSITIONS -- never a raw field assignment -- so a
client can't jump e.g. straight from PENDING to PAID without ever being
APPROVED. Same reasoning as purchasing.services.transition_status
(CPMAS-30) and invoicing.services.transition_status (CPMAS-32).

Since CPMAS-34 (Accounting/GL integration, Phase 1), marking an expense
PAID also recognizes it in the general ledger: ``book_expense`` is called
inside the same atomic block, so a paid expense either lands as PAID with
its DR expense / CR Cash journal entry, or stays APPROVED with no ledger
trace (e.g. when its category has no accounting account configured).
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.services import book_expense

from .models import Expense

ALLOWED_TRANSITIONS = {
    Expense.Status.PENDING: {Expense.Status.APPROVED, Expense.Status.REJECTED},
    Expense.Status.APPROVED: {Expense.Status.PAID, Expense.Status.REJECTED},
    Expense.Status.PAID: set(),
    Expense.Status.REJECTED: set(),
}


def transition_status(expense: Expense, new_status: str) -> Expense:
    """Move an Expense to new_status if valid; raises ValidationError otherwise."""
    current = Expense.Status(expense.status)
    target = Expense.Status(new_status)

    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValidationError(
            f"Cannot move an expense from {current.label} to {target.label}."
        )

    if target == Expense.Status.PAID:
        # Booking and the PAID flag commit together: a failed booking
        # (unconfigured category account, no cash account, no actor)
        # rolls back the status change, so the expense stays APPROVED.
        with transaction.atomic():
            expense.status = target
            expense.save(update_fields=['status', 'updated_at'])
            book_expense(expense)
    else:
        expense.status = target
        expense.save(update_fields=['status', 'updated_at'])
    return expense
