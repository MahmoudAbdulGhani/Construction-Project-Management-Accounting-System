from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payments', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='employee_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='contractor_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
