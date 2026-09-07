"""
Migration for the ``accounting`` app -- source tracking + COA seed.

Adds ``source_type`` / ``source_id`` to ``financial_transactions`` and a
partial unique constraint over the pair (only among non-voided entries),
so an operational document (Expense / ClientInvoice / SupplierInvoice /
ContractorInvoice / Payment) can be booked into the ledger at most once
(BRD 5.22 source tracking). VOIDED entries are deliberately excluded from
the constraint: cancelling a document voids its journal entry, and a
re-created entry (e.g. a payment whose allocations changed) is a fresh
POSTED journal, never an in-place edit of posted lines.

Also seeds the conservative starter chart of accounts (Cash, AR, AP, Tax
Payable, Construction Revenue, Cost of Construction, General Operating
Expenses) exactly once -- ``get_or_create`` by code, so it never overwrites
accounts a user has already named/re-typed, and re-running is a no-op.

Applied against the live Supabase database as a normal migration (unlike
0001's ``--fake-initial``); the operations here are purely additive -- two
nullable columns, a partial unique index, and idempotent seed rows -- so
existing rows are unaffected.
"""
from django.db import migrations, models

SEED_ACCOUNTS = [
    ('1000', 'Cash', 'Asset'),
    ('1100', 'Accounts Receivable', 'Asset'),
    ('2000', 'Accounts Payable', 'Liability'),
    ('2100', 'Tax Payable', 'Liability'),
    ('4000', 'Construction Revenue', 'Revenue'),
    ('5000', 'Cost of Construction', 'Expense'),
    ('6000', 'General Operating Expenses', 'Expense'),
]


def seed_chart_of_accounts(apps, schema_editor):
    Account = apps.get_model('accounting', 'Account')
    for code, name, account_type in SEED_ACCOUNTS:
        Account.objects.get_or_create(
            code=code,
            defaults={'name': name, 'account_type': account_type},
        )


def unseed_chart_of_accounts(apps, schema_editor):
    """Reverse: delete only seed rows nobody has reused or referenced yet."""
    Account = apps.get_model('accounting', 'Account')
    for code, name, account_type in SEED_ACCOUNTS:
        account = Account.objects.filter(
            code=code, name=name, account_type=account_type,
            parent_account__isnull=True,
        ).first()
        if account is not None and not account.transaction_lines.exists():
            account.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='financialtransaction',
            name='source_id',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='source_type',
            field=models.CharField(blank=True, choices=[('CLIENT_INVOICE', 'Client Invoice'), ('SUPPLIER_INVOICE', 'Supplier Invoice'), ('CONTRACTOR_INVOICE', 'Contractor Invoice'), ('PAYMENT', 'Payment'), ('EXPENSE', 'Expense')], db_index=True, max_length=50, null=True),
        ),
        migrations.AddConstraint(
            model_name='financialtransaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(source_type__isnull=False, source_id__isnull=False) & ~models.Q(status='VOIDED'),
                fields=('source_type', 'source_id'),
                name='uniq_source_pair',
            ),
        ),
        migrations.RunPython(seed_chart_of_accounts, unseed_chart_of_accounts),
    ]