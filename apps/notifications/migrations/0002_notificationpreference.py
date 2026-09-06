"""
Hand-written migration for the new ``notification_preferences`` table
(Notified settings tab). Unlike ``notifications``, this table does not
exist in the shared schema -- Django owns it, so it is created fresh on
every environment (run normally via ``migrate``).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationPreference',
            fields=[
                ('notification_type', models.CharField(max_length=100, primary_key=True, serialize=False)),
                ('is_enabled', models.BooleanField(default=True)),
                ('window_days', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Notification preference',
                'verbose_name_plural': 'Notification preferences',
                'db_table': 'notification_preferences',
                'ordering': ['notification_type'],
            },
        ),
    ]
