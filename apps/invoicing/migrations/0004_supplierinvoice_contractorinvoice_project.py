"""
Migration for the ``invoicing`` app: adds a project link to
SupplierInvoice and ContractorInvoice.

``project_id`` was added to the canonical Supabase schema (``project_id
UUID REFERENCES projects(id)``, nullable) so every invoice kind can be
rolled up into a project-level financial summary -- the same linking
pattern ClientInvoice already has. Applied against the live database
with ``--fake`` after the column is added by DDL; runs normally on any
fresh environment (e.g. the in-memory SQLite test DB).

SET_NULL matches ClientInvoice.project: the project is reference
context, not an audit anchor, so deleting (archiving) a project should
not destroy invoice history.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoicing', '0003_contractorinvoice_contractorinvoiceitem'),
        ('projects', '0003_remove_project_buyer_id_project_buyer_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierinvoice',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='supplier_invoices', to='projects.project'),
        ),
        migrations.AddField(
            model_name='contractorinvoice',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='contractor_invoices', to='projects.project'),
        ),
    ]