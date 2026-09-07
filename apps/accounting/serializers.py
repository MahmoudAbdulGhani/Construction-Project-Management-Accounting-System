"""
DRF serializers for the ``accounting`` app -- Accounting / Financial
Transactions slice (CPMAS-34).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Account, FinancialTransaction, TransactionLine
from .services import post_transaction, transaction_totals, void_transaction


class AccountSerializer(serializers.ModelSerializer):
    """Serializer for Account (chart of accounts) CRUD operations."""

    parent_account_code = serializers.CharField(source='parent_account.code', read_only=True, default=None)

    class Meta:
        model = Account
        fields = ['id', 'parent_account', 'parent_account_code', 'code', 'name', 'account_type', 'is_active']


class TransactionLineSerializer(serializers.ModelSerializer):
    """
    Serializer for TransactionLine CRUD.

    Mirrors the live database's two CHECK constraints at this layer too
    (defense in depth, not just relying on the DB to reject a bad
    insert): debit/credit must both be >= 0, and a line can't have both
    a debit and a credit at once. "Lines only editable while the parent
    transaction is DRAFT" is enforced in the viewset, same reasoning as
    PurchaseOrderItemViewSet (CPMAS-30).
    """

    account_code = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)

    class Meta:
        model = TransactionLine
        fields = [
            'id', 'transaction', 'account', 'account_code', 'account_name',
            'description', 'debit', 'credit', 'project',
        ]

    def validate(self, attrs):
        debit = attrs.get('debit', getattr(self.instance, 'debit', 0)) or 0
        credit = attrs.get('credit', getattr(self.instance, 'credit', 0)) or 0

        if debit < 0 or credit < 0:
            raise serializers.ValidationError("debit and credit cannot be negative.")
        if debit > 0 and credit > 0:
            raise serializers.ValidationError("A line cannot have both a debit and a credit -- it's one or the other.")
        if debit == 0 and credit == 0:
            raise serializers.ValidationError("A line must have either a debit or a credit greater than zero.")

        return attrs


class FinancialTransactionSerializer(serializers.ModelSerializer):
    """
    Serializer for FinancialTransaction header CRUD.

    status/posted_at are read-only: status changes go through the
    post/void actions on the viewset (see FinancialTransactionViewSet)
    rather than a raw PATCH, so BR 12.7's balance check can't be
    bypassed by writing POSTED directly.
    """

    project_name = serializers.CharField(source='project.name', read_only=True, default=None)
    client_name = serializers.CharField(source='client.name', read_only=True, default=None)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True, default=None)
    lines = TransactionLineSerializer(many=True, read_only=True)
    total_debit = serializers.SerializerMethodField()
    total_credit = serializers.SerializerMethodField()
    source_label = serializers.SerializerMethodField()

    class Meta:
        model = FinancialTransaction
        fields = [
            'id', 'transaction_number', 'transaction_date', 'description', 'reference',
            'project', 'project_name', 'client', 'client_name', 'supplier', 'supplier_name',
            'status', 'created_by', 'posted_at', 'source_type', 'source_id', 'source_label',
            'lines', 'total_debit', 'total_credit', 'created_at', 'updated_at',
        ]
        read_only_fields = ['status', 'posted_at', 'created_at', 'updated_at', 'source_type', 'source_id']

    def get_total_debit(self, obj):
        return transaction_totals(obj)[0]

    def get_total_credit(self, obj):
        return transaction_totals(obj)[1]

    def get_source_label(self, obj):
        return obj.get_source_type_display() if obj.source_type else 'Manual'


def apply_post(financial_transaction: FinancialTransaction) -> FinancialTransaction:
    """Shared helper for the viewset's post action -- 400 instead of 500 on an invalid post."""
    try:
        return post_transaction(financial_transaction)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'detail': exc.messages})


def apply_void(financial_transaction: FinancialTransaction) -> FinancialTransaction:
    """Shared helper for the viewset's void action -- 400 instead of 500 on an invalid void."""
    try:
        return void_transaction(financial_transaction)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'detail': exc.messages})
