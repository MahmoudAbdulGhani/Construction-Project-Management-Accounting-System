"""Serializers for the ``taxes`` app (Tax Rates configuration)."""
from rest_framework import serializers

from .models import TaxRate


class TaxRateSerializer(serializers.ModelSerializer):
    """Read/write representation of a configurable tax rate.

    Mirrors the ``tax_rates`` table: ``name``, ``rate`` (percent), the free
    text ``tax_type``, ``effective_date``, and ``is_active``. ``rate`` uses
    the schema's DECIMAL(8,4) precision; it's serialized as a string so the
    four decimal places survive JSON round trips.
    """

    class Meta:
        model = TaxRate
        fields = [
            'id', 'name', 'rate', 'tax_type', 'effective_date', 'is_active',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'rate': {'coerce_to_string': False},
        }

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Tax rate name is required.')
        return value

    def validate_rate(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError('Rate must be zero or greater.')
        return value