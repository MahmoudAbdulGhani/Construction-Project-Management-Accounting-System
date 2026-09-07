"""
Business logic for the ``accounting`` app that must not live in a
serializer or viewset.

Split across two modules:

- ``core``: the ledger primitives -- transaction_totals, post_transaction
  (the BR 12.7 balance gate), and void_transaction.
- ``auto``: system-generated journal entries from operational documents
  (financial transactions that book themselves from an Expense, invoice,
  or Payment).

Everything is re-exported here so ``from accounting.services import ...``
keeps working as a single stable import surface for app internals.
"""
from .auto import (  # noqa: F401
    AccountingError,
    book_client_invoice,
    book_contractor_invoice,
    book_expense,
    book_payment,
    book_supplier_invoice,
    existing_source_entry,
    generate_transaction_number,
    get_account,
    post_source_entry,
    resolve_actor,
    void_source_entry,
)
from .core import post_transaction, transaction_totals, void_transaction  # noqa: F401

__all__ = [
    'AccountingError',
    'book_client_invoice',
    'book_contractor_invoice',
    'book_expense',
    'book_payment',
    'book_supplier_invoice',
    'existing_source_entry',
    'generate_transaction_number',
    'get_account',
    'post_source_entry',
    'resolve_actor',
    'void_source_entry',
    'post_transaction',
    'transaction_totals',
    'void_transaction',
]