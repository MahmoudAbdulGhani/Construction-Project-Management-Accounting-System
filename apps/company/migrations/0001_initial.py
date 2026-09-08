from decimal import Decimal

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("taxes", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyProfile",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "registration_number",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                ("address", models.TextField(blank=True, null=True)),
                ("phone", models.CharField(blank=True, max_length=50, null=True)),
                ("email", models.CharField(blank=True, max_length=255, null=True)),
                ("website", models.CharField(blank=True, max_length=255, null=True)),
                ("currency", models.UUIDField()),
                ("tax_information", models.TextField(blank=True, null=True)),
                ("logo", models.CharField(blank=True, max_length=500, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "company_details",
                "ordering": ["-updated_at"],
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="FinancialSettings",
            fields=[
                (
                    "id",
                    models.PositiveIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("fiscal_year_start_month", models.PositiveSmallIntegerField(default=1)),
                ("fiscal_year_start_day", models.PositiveSmallIntegerField(default=1)),
                ("lock_financial_periods", models.BooleanField(default=True)),
                (
                    "period_lock_after_days",
                    models.IntegerField(blank=True, default=30, null=True),
                ),
                (
                    "default_payment_terms",
                    models.CharField(
                        choices=[
                            ("NET30", "Net 30"),
                            ("NET60", "Net 60"),
                            ("IMMEDIATE", "Immediate"),
                        ],
                        default="NET30",
                        max_length=20,
                    ),
                ),
                (
                    "retention_percent",
                    models.DecimalField(
                        decimal_places=2, default=Decimal("5.00"), max_digits=5
                    ),
                ),
                (
                    "budget_alert_percent",
                    models.DecimalField(
                        decimal_places=2, default=Decimal("90.00"), max_digits=5
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "financial_settings",
                "ordering": ["id"],
                "verbose_name": "Financial settings",
                "verbose_name_plural": "Financial settings",
            },
        ),
        migrations.AddField(
            model_name="financialsettings",
            name="default_tax_rate",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="taxes.taxrate",
                verbose_name="Default tax rate",
            ),
        ),
    ]