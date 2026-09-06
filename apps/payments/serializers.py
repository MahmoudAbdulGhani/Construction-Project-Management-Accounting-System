"""
DRF serializers for the ``payments`` app -- Accounts Receivable &
Accounts Payable slice (CPMAS-35).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from contractors.models import Contractor
from employees.models import Employee

from .models import Payment, PaymentAllocation, Receipt
from .services import (
    allocate_payment,
    create_payment_with_generated_number,
    unallocated_amount,
)

# Renders a SerializerMethodField Decimal the same way a real
# DecimalField would (a "0.00"-style JSON string) -- see
# PaymentSerializer.get_unallocated_amount.
DECIMAL_FIELD = serializers.DecimalField(max_digits=18, decimal_places=2)


class PaymentSerializer(serializers.ModelSerializer):
    """
    Serializer for Payment CRUD.

    Read/create only at the viewset level -- see PaymentViewSet -- since
    a recorded payment is a ledger entry (same immutability reasoning as
    StockMovement).
    """

    client_name = serializers.CharField(source='client.name', read_only=True, default=None)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True, default=None)
    employee_name = serializers.SerializerMethodField()
    contractor_name = serializers.SerializerMethodField()
    payee_name = serializers.SerializerMethodField()
    payee_type = serializers.SerializerMethodField()
    allocatable = serializers.SerializerMethodField()
    has_receipt = serializers.SerializerMethodField()
    unallocated_amount = serializers.SerializerMethodField()
    # Optional: a blank payment_number gets auto-generated
    # (PAY-<year>-<seq>) by create_payment_with_generated_number on create.
    payment_number = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
        validators=[UniqueValidator(queryset=Payment.objects.all())],
    )

    class Meta:
        model = Payment
        fields = [
            'id', 'payment_number', 'payment_date', 'amount', 'direction',
            'payment_method', 'client', 'client_name', 'supplier', 'supplier_name',
            'employee_id', 'employee_name', 'contractor_id', 'contractor_name',
            'payee_name', 'payee_type', 'allocatable', 'has_receipt',
            'reference', 'notes', 'created_by', 'unallocated_amount', 'created_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at']

    def create(self, validated_data):
        return create_payment_with_generated_number(validated_data)

    def validate_payment_number(self, value):
        # Blank is fine -- create() generates one. Only trim here; reject
        # nothing, so the auto-generation path isn't tripped by whitespace.
        return (value or '').strip()

    def validate_payment_method(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def get_unallocated_amount(self, obj):
        return DECIMAL_FIELD.to_representation(unallocated_amount(obj))

    def get_employee_name(self, obj):
        if not obj.employee_id:
            return None
        return Employee.objects.filter(pk=obj.employee_id).values_list('name', flat=True).first()

    def get_contractor_name(self, obj):
        if not obj.contractor_id:
            return None
        return Contractor.objects.filter(pk=obj.contractor_id).values_list('name', flat=True).first()

    def get_payee_name(self, obj):
        return (
            obj.client.name if obj.client_id else
            obj.supplier.name if obj.supplier_id else
            self.get_employee_name(obj) or self.get_contractor_name(obj)
        )

    def get_payee_type(self, obj):
        if obj.client_id:
            return 'CLIENT'
        if obj.supplier_id:
            return 'SUPPLIER'
        if obj.employee_id:
            return 'EMPLOYEE'
        if obj.contractor_id:
            return 'CONTRACTOR'
        return None

    def get_allocatable(self, obj):
        # Clients and suppliers fund client/supplier invoices; contractors
        # now fund contractor invoices too. Only employee payments are
        # direct (wages/salary have no invoice to allocate against).
        return bool(obj.client_id or obj.supplier_id or obj.contractor_id)

    def get_has_receipt(self, obj):
        return hasattr(obj, 'receipt')

    def validate(self, attrs):
        direction = attrs.get('direction')
        client = attrs.get('client')
        supplier = attrs.get('supplier')
        employee_id = attrs.get('employee_id')
        contractor_id = attrs.get('contractor_id')

        amount = attrs.get('amount')
        if amount is not None and amount <= 0:
            raise serializers.ValidationError({'amount': "Payment amount must be positive."})

        parties = [client, supplier, employee_id, contractor_id]
        if sum(bool(party) for party in parties) != 1:
            raise serializers.ValidationError(
                "Exactly one client, supplier, employee, or contractor must be specified."
            )

        if direction == Payment.Direction.INCOMING and (not client or supplier or employee_id or contractor_id):
            raise serializers.ValidationError(
                "An INCOMING payment must specify a client and must not specify a supplier."
            )
        if direction == Payment.Direction.OUTGOING and client:
            raise serializers.ValidationError(
                "An OUTGOING payment must specify a supplier, employee, or contractor."
            )

        if employee_id and not Employee.objects.filter(pk=employee_id).exists():
            raise serializers.ValidationError({'employee_id': "Employee does not exist."})
        if contractor_id and not Contractor.objects.filter(pk=contractor_id).exists():
            raise serializers.ValidationError({'contractor_id': "Contractor does not exist."})

        return attrs


class PaymentAllocationSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentAllocation. Create-only at the viewset level
    (append-only, same reasoning as Payment) -- .create() delegates to
    payments.services.allocate_payment, which is the single place an
    allocation gets created AND an invoice's status advances as a
    result, rather than a plain ModelSerializer.create().
    """

    class Meta:
        model = PaymentAllocation
        fields = ['id', 'payment', 'client_invoice', 'supplier_invoice', 'contractor_invoice', 'allocated_amount']

    def validate(self, attrs):
        # Mirrors the live database's CHECK constraint (defense in
        # depth, same pattern as TransactionLine's mirrored CHECKs).
        client_invoice = attrs.get('client_invoice')
        supplier_invoice = attrs.get('supplier_invoice')
        contractor_invoice = attrs.get('contractor_invoice')
        set_count = sum(bool(x) for x in (client_invoice, supplier_invoice, contractor_invoice))
        if set_count != 1:
            raise serializers.ValidationError(
                "Exactly one of client_invoice, supplier_invoice, or contractor_invoice must be set."
            )
        if attrs.get('allocated_amount') is not None and attrs['allocated_amount'] <= 0:
            raise serializers.ValidationError({'allocated_amount': "Allocation amount must be positive."})
        return attrs

    def create(self, validated_data):
        payment = validated_data['payment']
        invoice = (
            validated_data.get('client_invoice')
            or validated_data.get('supplier_invoice')
            or validated_data.get('contractor_invoice')
        )
        amount = validated_data['allocated_amount']
        try:
            return allocate_payment(payment, invoice, amount)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'detail': exc.messages})


class ReceiptSerializer(serializers.ModelSerializer):
    """
    Serializer for Receipt. Create-only at the viewset level (proof of
    receipt, immutable once issued).

    Issued for either payment direction -- a receipt documents money
    received FROM a client or paid TO a supplier/employee/contractor (see
    PaymentViewSet.perform_create, which auto-issues receipts on payment
    creation). client_name/supplier_name/contractor_name/employee_name/
    payment_method are read-only, derived through the receipt's payment --
    BRD 5.19 lists "Client/supplier" and "Payment method" as receipt
    fields, but the schema's receipts table has no such columns of its
    own (a receipt is always one-to-one with a payment, so nothing would
    be gained by duplicating them here). Currency is in BRD 5.19 too but
    is out of scope for this version (BRD 3.2 lists multi-currency as a
    future enhancement).
    """

    payment_number = serializers.CharField(source='payment.payment_number', read_only=True)
    client_name = serializers.CharField(source='payment.client.name', read_only=True, default=None)
    supplier_name = serializers.CharField(source='payment.supplier.name', read_only=True, default=None)
    contractor_name = serializers.SerializerMethodField()
    employee_name = serializers.SerializerMethodField()
    payee_name = serializers.SerializerMethodField()
    payment_method = serializers.CharField(source='payment.payment_method', read_only=True)

    class Meta:
        model = Receipt
        fields = [
            'id', 'payment', 'payment_number', 'client_name', 'supplier_name',
            'contractor_name', 'employee_name', 'payee_name', 'payment_method',
            'receipt_number', 'receipt_date', 'amount', 'reference', 'created_at',
        ]

    def get_contractor_name(self, obj):
        if not obj.payment.contractor_id:
            return None
        return Contractor.objects.filter(pk=obj.payment.contractor_id).values_list('name', flat=True).first()

    def get_employee_name(self, obj):
        if not obj.payment.employee_id:
            return None
        return Employee.objects.filter(pk=obj.payment.employee_id).values_list('name', flat=True).first()

    def get_payee_name(self, obj):
        return (
            obj.payment.client.name if obj.payment.client_id else
            obj.payment.supplier.name if obj.payment.supplier_id else
            self.get_employee_name(obj) or self.get_contractor_name(obj)
        )

    def validate_payment(self, payment):
        if hasattr(payment, 'receipt'):
            raise serializers.ValidationError("This payment already has a receipt.")
        return payment

    def validate(self, attrs):
        payment = attrs.get('payment')
        amount = attrs.get('amount')
        if amount is not None and amount <= 0:
            raise serializers.ValidationError({'amount': "Receipt amount must be positive."})
        if payment is not None and amount is not None and amount != payment.amount:
            raise serializers.ValidationError(
                {'amount': "Receipt amount must exactly equal the payment amount."}
            )
        return attrs
