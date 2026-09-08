"""
Migration for the ``payments`` app: adds PaymentAllocation
.contractor_invoice, letting an OUTGOING contractor payment be applied
against a contractor invoice (and advance it to PARTIALLY_PAID/PAID) the
same way supplier payments fund supplier invoices.

The live ``payment_allocations`` CHECK constraint is replaced in the
canonical SQL script (and the live database) to allow exactly one of
client_invoice/supplier_invoice/contractor_invoice; this migration only
adds the nullable FK column. Applied against the live database with
``--fake`` (column already added directly); runs normally (adds the
column) on any fresh environment, e.g. the in-memory SQLite test DB.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoicing', '0003_contractorinvoice_contractorinvoiceitem'),
        ('payments', '0002_payment_employee_contractor'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentallocation',
            name='contractor_invoice',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='payment_allocations', to='invoicing.contractorinvoice'),
        ),
    ]