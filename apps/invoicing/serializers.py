"""
DRF serializers for the ``invoicing`` app -- Supplier Invoices slice
(CPMAS-32).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from contractors.models import Contractor

from .models import (
    ClientInvoice,
    ClientInvoiceItem,
    ContractorInvoice,
    ContractorInvoiceItem,
    SupplierInvoice,
    SupplierInvoiceItem,
)
from .services import (
    compute_client_invoice_item_amounts,
    compute_contractor_item_amounts,
    compute_item_amounts,
    create_invoice_with_generated_number,
    recalculate_client_invoice_totals,
    recalculate_contractor_invoice_totals,
    recalculate_invoice_totals,
    transition_client_invoice_status,
    transition_contractor_invoice_status,
    transition_status,
)

# Shared instance used to render SerializerMethodField monetary values
# (outstanding_balance) as the same "0.00"-style string every DecimalField
# on this API produces -- see get_outstanding_balance's comment below.
DECIMAL_FIELD = serializers.DecimalField(max_digits=18, decimal_places=2)


class SupplierInvoiceItemSerializer(serializers.ModelSerializer):
    """
    Serializer for SupplierInvoiceItem CRUD.

    Unlike PurchaseOrderItemSerializer, tax_amount/total_amount are NOT
    read-only here: invoicing.services.compute_item_amounts only derives
    them when quantity+unit_price are both present -- for a flat-charge
    line (neither set), total_amount IS the direct input, so the
    serializer has to let it through to validated_data for
    compute_item_amounts to see it. compute_item_amounts still has the
    final say either way: it overwrites both fields on the
    quantity*price path, and only preserves the caller's values as a
    fallback on the flat-charge path.

    "Items only editable while the parent invoice is DRAFT" is enforced
    in the viewset, same reasoning as PurchaseOrderItemViewSet (CPMAS-30).
    """

    material_name = serializers.CharField(source='material.name', read_only=True, default=None)

    class Meta:
        model = SupplierInvoiceItem
        fields = [
            'id', 'supplier_invoice', 'material', 'material_name', 'description',
            'quantity', 'unit_price', 'tax_rate', 'tax_amount', 'total_amount',
        ]

    def validate(self, attrs):
        # Both-or-neither: a line with only one of quantity/unit_price
        # set is ambiguous (what would the other side of the
        # multiplication be?) -- reject rather than silently falling
        # into the flat-charge path with half the data ignored.
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', None))
        unit_price = attrs.get('unit_price', getattr(self.instance, 'unit_price', None))
        if (quantity is None) != (unit_price is None):
            raise serializers.ValidationError(
                "quantity and unit_price must both be set, or both left blank for a flat-charge line."
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        item = SupplierInvoiceItem(**validated_data)
        compute_item_amounts(item)
        item.save()
        recalculate_invoice_totals(item.supplier_invoice)
        return item

    @transaction.atomic
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        compute_item_amounts(instance)
        instance.save()
        recalculate_invoice_totals(instance.supplier_invoice)
        return instance


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    """
    Serializer for SupplierInvoice header CRUD.

    subtotal/tax_amount/total_amount/status are all read-only: totals
    are derived from line items, and status changes go through the
    mark_sent/cancel actions on the viewset rather than a raw PATCH.
    """

    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    purchase_order_number = serializers.CharField(source='purchase_order.po_number', read_only=True, default=None)
    project_name = serializers.CharField(source='project.name', read_only=True, default=None)
    items = SupplierInvoiceItemSerializer(many=True, read_only=True)
    outstanding_balance = serializers.SerializerMethodField()
    # Optional: a blank invoice_number gets auto-generated
    # (INV-<year>-<seq>) by create_invoice_with_generated_number on create.
    invoice_number = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
        validators=[UniqueValidator(queryset=SupplierInvoice.objects.all())],
    )

    class Meta:
        model = SupplierInvoice
        fields = [
            'id', 'supplier', 'supplier_name', 'purchase_order', 'purchase_order_number',
            'project', 'project_name',
            'invoice_number', 'invoice_date', 'due_date', 'subtotal', 'tax_amount',
            'total_amount', 'status', 'outstanding_balance', 'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['subtotal', 'tax_amount', 'total_amount', 'status', 'created_at', 'updated_at']

    def create(self, validated_data):
        return create_invoice_with_generated_number(SupplierInvoice, validated_data)

    def get_outstanding_balance(self, obj):
        # BRD 5.23/5.24: outstanding balance is always calculated from
        # invoice totals minus payment allocations, never a stored/
        # editable column -- see payments.services.outstanding_balance
        # (CPMAS-35). Imported here, not at module level, so this app
        # doesn't take a hard import-time dependency on payments.
        #
        # Routed through a plain DecimalField's to_representation rather
        # than returned as a raw Decimal: SerializerMethodField values
        # skip DecimalField's own string-coercion, so DRF's JSONEncoder
        # would otherwise render this as an imprecise JSON float (e.g.
        # 0.0) instead of the "0.00"-style string every other monetary
        # field on this API returns.
        from payments.services import outstanding_balance
        return DECIMAL_FIELD.to_representation(outstanding_balance(obj))


def apply_transition(invoice: SupplierInvoice, target_status: str) -> SupplierInvoice:
    """
    Shared helper used by the viewset's mark_sent/cancel actions: runs
    the transition and re-raises Django's ValidationError as DRF's, so
    an invalid transition comes back as a 400 instead of a 500.
    """
    try:
        return transition_status(invoice, target_status)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'status': exc.messages})


class ClientInvoiceItemSerializer(serializers.ModelSerializer):
    """
    Serializer for ClientInvoiceItem CRUD.

    Unlike SupplierInvoiceItemSerializer, tax_amount/total_amount ARE
    read-only: quantity/unit_price are always required here (no
    flat-charge line exists for client invoices), so
    compute_client_invoice_item_amounts always has what it needs to
    derive both fields -- there's no case where a caller-supplied total
    needs to pass through. "Items only editable while the parent invoice
    is DRAFT" is enforced in the viewset.
    """

    tax_rate_name = serializers.CharField(source='tax_rate.name', read_only=True, default=None)

    class Meta:
        model = ClientInvoiceItem
        fields = [
            'id', 'client_invoice', 'description', 'quantity', 'unit_price',
            'discount_amount', 'tax_rate', 'tax_rate_name', 'tax_amount', 'total_amount',
        ]
        read_only_fields = ['tax_amount', 'total_amount']

    @transaction.atomic
    def create(self, validated_data):
        item = ClientInvoiceItem(**validated_data)
        compute_client_invoice_item_amounts(item)
        item.save()
        recalculate_client_invoice_totals(item.client_invoice)
        return item

    @transaction.atomic
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        compute_client_invoice_item_amounts(instance)
        instance.save()
        recalculate_client_invoice_totals(instance.client_invoice)
        return instance


class ClientInvoiceSerializer(serializers.ModelSerializer):
    """
    Serializer for ClientInvoice header CRUD.

    subtotal/discount_amount/tax_amount/total_amount/status are all
    read-only: totals are derived from line items, and status changes go
    through the mark_sent/cancel actions (or payments.services
    .allocate_payment for PARTIALLY_PAID/PAID) rather than a raw PATCH.
    """

    client_name = serializers.CharField(source='client.name', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True, default=None)
    items = ClientInvoiceItemSerializer(many=True, read_only=True)
    outstanding_balance = serializers.SerializerMethodField()
    # Optional: a blank invoice_number gets auto-generated on create.
    invoice_number = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
        validators=[UniqueValidator(queryset=ClientInvoice.objects.all())],
    )

    class Meta:
        model = ClientInvoice
        fields = [
            'id', 'client', 'client_name', 'project', 'project_name',
            'invoice_number', 'invoice_date', 'due_date', 'subtotal', 'discount_amount',
            'tax_amount', 'total_amount', 'status', 'outstanding_balance', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'subtotal', 'discount_amount', 'tax_amount', 'total_amount', 'status',
            'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        return create_invoice_with_generated_number(ClientInvoice, validated_data)

    def get_outstanding_balance(self, obj):
        # See SupplierInvoiceSerializer.get_outstanding_balance's comment.
        from payments.services import outstanding_balance
        return DECIMAL_FIELD.to_representation(outstanding_balance(obj))


def apply_client_transition(invoice: ClientInvoice, target_status: str) -> ClientInvoice:
    """Same reasoning as apply_transition, for ClientInvoice."""
    try:
        return transition_client_invoice_status(invoice, target_status)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'status': exc.messages})


class ContractorInvoiceItemSerializer(serializers.ModelSerializer):
    """
    Serializer for ContractorInvoiceItem CRUD.

    Mirrors SupplierInvoiceItemSerializer: tax_amount/total_amount are
    writable so a flat-charge line can pass its total through to
    compute_contractor_item_amounts, which still has the final say on the
    quantity*price path. There's no material reference -- a contractor
    invoice bills work, not goods. "Items only editable while the parent
    invoice is DRAFT" is enforced in the viewset.
    """

    class Meta:
        model = ContractorInvoiceItem
        fields = [
            'id', 'contractor_invoice', 'description',
            'quantity', 'unit_price', 'tax_rate', 'tax_amount', 'total_amount',
        ]

    def validate(self, attrs):
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', None))
        unit_price = attrs.get('unit_price', getattr(self.instance, 'unit_price', None))
        if (quantity is None) != (unit_price is None):
            raise serializers.ValidationError(
                "quantity and unit_price must both be set, or both left blank for a flat-charge line."
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        item = ContractorInvoiceItem(**validated_data)
        compute_contractor_item_amounts(item)
        item.save()
        recalculate_contractor_invoice_totals(item.contractor_invoice)
        return item

    @transaction.atomic
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        compute_contractor_item_amounts(instance)
        instance.save()
        recalculate_contractor_invoice_totals(instance.contractor_invoice)
        return instance


class ContractorInvoiceSerializer(serializers.ModelSerializer):
    """
    Serializer for ContractorInvoice header CRUD.

    Same shape as SupplierInvoiceSerializer: contractor_name is resolved
    from the unmanaged Contractor reflection, totals/status are
    read-only, and status changes go through mark_sent/cancel (or
    payments.services.allocate_payment for PARTIALLY_PAID/PAID).
    """

    contractor_name = serializers.SerializerMethodField()
    project_name = serializers.CharField(source='project.name', read_only=True, default=None)
    items = ContractorInvoiceItemSerializer(many=True, read_only=True)
    outstanding_balance = serializers.SerializerMethodField()
    # Optional: a blank invoice_number gets auto-generated on create.
    invoice_number = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
        validators=[UniqueValidator(queryset=ContractorInvoice.objects.all())],
    )

    class Meta:
        model = ContractorInvoice
        fields = [
            'id', 'contractor_id', 'contractor_name', 'project', 'project_name',
            'invoice_number', 'invoice_date', 'due_date', 'subtotal', 'tax_amount',
            'total_amount', 'status', 'outstanding_balance', 'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['subtotal', 'tax_amount', 'total_amount', 'status', 'created_at', 'updated_at']

    def create(self, validated_data):
        return create_invoice_with_generated_number(ContractorInvoice, validated_data)

    def get_contractor_name(self, obj):
        return Contractor.objects.filter(pk=obj.contractor_id).values_list('name', flat=True).first()

    def validate_contractor_id(self, value):
        if not Contractor.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Contractor does not exist.")
        return value

    def get_outstanding_balance(self, obj):
        # See SupplierInvoiceSerializer.get_outstanding_balance's comment.
        from payments.services import outstanding_balance
        return DECIMAL_FIELD.to_representation(outstanding_balance(obj))


def apply_contractor_transition(invoice: ContractorInvoice, target_status: str) -> ContractorInvoice:
    """Same reasoning as apply_transition, for ContractorInvoice."""
    try:
        return transition_contractor_invoice_status(invoice, target_status)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'status': exc.messages})
