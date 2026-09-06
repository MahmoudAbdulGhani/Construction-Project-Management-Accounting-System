"""
Migration for the ``invoicing`` app: adds ContractorInvoice/
ContractorInvoiceItem -- contractor billing on the Accounts Payable side,
settled through payment allocations the same way supplier invoices are.

Both tables (``contractor_invoices``, ``contractor_invoice_items``)
already exist in the live Supabase database, provisioned by the canonical
SQL script ahead of this app owning them. Applied against the live
database with ``--fake`` (structure already matches); runs normally
(creates the tables) on any fresh environment, e.g. the in-memory
SQLite test DB.

``ContractorInvoice.contractor_id`` is intentionally a plain UUID column,
not a foreign key: ``contractors.Contractor`` is a managed=False
reflection, and the live schema owns the REFERENCES constraint (same
pattern as ``payments.Payment.employee_id``/``contractor_id``).
"""
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoicing', '0002_clientinvoice_clientinvoiceitem'),
        ('taxes', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContractorInvoice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('contractor_id', models.UUIDField(db_index=True)),
                ('invoice_number', models.CharField(max_length=100, unique=True)),
                ('invoice_date', models.DateField()),
                ('due_date', models.DateField(blank=True, null=True)),
                ('subtotal', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('tax_amount', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('SENT', 'Sent'), ('PARTIALLY_PAID', 'Partially Paid'), ('PAID', 'Paid'), ('OVERDUE', 'Overdue'), ('CANCELLED', 'Cancelled')], db_index=True, default='DRAFT', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Contractor Invoice',
                'verbose_name_plural': 'Contractor Invoices',
                'db_table': 'contractor_invoices',
                'ordering': ['-invoice_date', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ContractorInvoiceItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('description', models.TextField()),
                ('quantity', models.DecimalField(blank=True, decimal_places=3, max_digits=18, null=True)),
                ('unit_price', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('tax_amount', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('contractor_invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='invoicing.contractorinvoice')),
                ('tax_rate', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='contractor_invoice_items', to='taxes.taxrate')),
            ],
            options={
                'verbose_name': 'Contractor Invoice Item',
                'verbose_name_plural': 'Contractor Invoice Items',
                'db_table': 'contractor_invoice_items',
                'ordering': ['id'],
            },
        ),
    ]