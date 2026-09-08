"""
Serializers for the ``company`` app -- Company Administration.

``CompanyProfileSerializer`` is the read/update representation of the single
system-wide company record (``company_details`` table). Because this system
is built for exactly one company (Cedar Construction), the API offers only
view (GET) and update (PATCH) -- never create/list-of-many/delete.

Per the project decision (Option B), the company API is text-only: ``logo``
and ``currency`` are read-only here. The logo is changed from the web form
page (which uploads to Supabase and stores the public URL), and currency is
fixed at USD, so neither is writable through the API.
"""
from rest_framework import serializers

from .models import CompanyProfile, FinancialSettings


class CompanyProfileSerializer(serializers.ModelSerializer):
    """View/update the single company identity record."""

    class Meta:
        model = CompanyProfile
        fields = [
            "id",
            "name",
            "registration_number",
            "address",
            "phone",
            "email",
            "website",
            "tax_information",
            "currency",
            "logo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "currency",
            "logo",
            "created_at",
            "updated_at",
        ]


class FinancialSettingsSerializer(serializers.ModelSerializer):
    """View/update the single Financial rules record."""

    default_tax_rate_label = serializers.CharField(
        source="default_tax_rate.name", read_only=True, default=""
    )

    class Meta:
        model = FinancialSettings
        fields = [
            "id",
            "fiscal_year_start_month",
            "fiscal_year_start_day",
            "lock_financial_periods",
            "period_lock_after_days",
            "default_tax_rate",
            "default_tax_rate_label",
            "default_payment_terms",
            "retention_percent",
            "budget_alert_percent",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "default_tax_rate_label",
            "updated_at",
        ]

    def validate_fiscal_year_start_month(self, value):
        if not 1 <= value <= 12:
            raise serializers.ValidationError("Month must be between 1 and 12.")
        return value

    def validate_fiscal_year_start_day(self, value):
        if not 1 <= value <= 31:
            raise serializers.ValidationError("Day must be between 1 and 31.")
        return value

    def validate_period_lock_after_days(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Period lock days cannot be negative.")
        return value

    def validate_retention_percent(self, value):
        if not 0 <= value <= 100:
            raise serializers.ValidationError("Retention must be between 0 and 100.")
        return value

    def validate_budget_alert_percent(self, value):
        if not 0 <= value <= 100:
            raise serializers.ValidationError("Budget alert must be between 0 and 100.")
        return value
