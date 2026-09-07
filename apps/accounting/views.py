"""
DRF viewsets for the ``accounting`` app -- Accounting / Financial
Transactions slice (CPMAS-34).
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from construction.filtering import filter_date_range

from .models import Account, FinancialTransaction, TransactionLine
from .serializers import (
    AccountSerializer,
    FinancialTransactionSerializer,
    TransactionLineSerializer,
    apply_post,
    apply_void,
)
from .reports import profit_loss, revenue_expense_trend


class ReportViewSet(viewsets.ViewSet):
    """
    Read-only Financial Reports (Core) -- Profit & Loss and the monthly
    Revenue & Expense trend.

    Both are computed server-side over POSTED journal lines only (DRAFT is
    never booked; VOIDED is reversed by a separate correction). All sums are
    aggregated in the database; the client never downloads the ledger.

    GET /api/accounting/reports/profit-loss/?date_from=&date_to=&project=
    GET /api/accounting/reports/trend/?date_from=&date_to=&project=
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='profit-loss')
    def profit_loss(self, request):
        return Response(profit_loss(request.query_params))

    @action(detail=False, methods=['get'], url_path='trend')
    def trend(self, request):
        return Response(revenue_expense_trend(request.query_params))


class AccountViewSet(viewsets.ModelViewSet):
    """CRUD API for the chart of accounts."""

    queryset = Account.objects.select_related('parent_account').all()
    serializer_class = AccountSerializer
    search_fields = ['code', 'name']
    ordering_fields = ['code', 'name']

    def get_queryset(self):
        queryset = super().get_queryset()
        account_type = self.request.query_params.get('account_type')
        if account_type:
            queryset = queryset.filter(account_type__iexact=account_type)
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() in ('true', '1'))
        return queryset


class FinancialTransactionViewSet(viewsets.ModelViewSet):
    """
    CRUD + status-transition API for journal entry headers.

    Header fields stay editable via the normal update route while DRAFT;
    status itself is changed only through the post/void actions below,
    never a raw PATCH (status is read-only on the serializer).
    """

    queryset = FinancialTransaction.objects.select_related(
        'project', 'client', 'supplier',
    ).prefetch_related('lines').all()
    serializer_class = FinancialTransactionSerializer
    search_fields = ['transaction_number', 'description', 'reference']
    ordering_fields = ['transaction_date', 'created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        status_param = params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param.upper())

        project_id = params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        client_id = params.get('client')
        if client_id:
            queryset = queryset.filter(client_id=client_id)

        supplier_id = params.get('supplier')
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)

        source_type = params.get('source_type')
        if source_type:
            queryset = queryset.filter(source_type=source_type.upper())

        source_id = params.get('source_id')
        if source_id:
            queryset = queryset.filter(source_id=source_id)

        queryset = filter_date_range(queryset, params, 'transaction_date')

        return queryset

    def _require_draft(self, financial_transaction):
        if financial_transaction.status != FinancialTransaction.Status.DRAFT:
            raise PermissionDenied(
                f"Cannot edit a financial transaction once it is {financial_transaction.get_status_display()}."
            )

    def perform_update(self, serializer):
        self._require_draft(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_draft(instance)
        instance.delete()

    @action(detail=True, methods=['post'])
    def post_entry(self, request, pk=None):
        """
        POST /api/accounting/financial-transactions/{id}/post_entry/ --
        DRAFT -> POSTED, only if Sum(debit) == Sum(credit) across lines
        (BR 12.7). Named post_entry rather than "post" to avoid colliding
        with DRF's own HTTP-method-named routing conventions.
        """
        financial_transaction = apply_post(self.get_object())
        return Response(self.get_serializer(financial_transaction).data)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        """POST /api/accounting/financial-transactions/{id}/void/ -- DRAFT/POSTED -> VOIDED."""
        financial_transaction = apply_void(self.get_object())
        return Response(self.get_serializer(financial_transaction).data)


class TransactionLineViewSet(viewsets.ModelViewSet):
    """
    CRUD API for journal entry lines.

    Filterable by ?transaction=<uuid>. Create/update/destroy are all
    blocked once the parent transaction has left DRAFT -- same reasoning
    as PurchaseOrderItemViewSet (CPMAS-30): a posted entry's lines are
    exactly what got balance-checked and posted, so editing them
    afterward would let the ledger silently drift out of balance.
    """

    queryset = TransactionLine.objects.select_related('transaction', 'account', 'project').all()
    serializer_class = TransactionLineSerializer
    search_fields = ['account__code', 'account__name', 'description']

    def get_queryset(self):
        queryset = super().get_queryset()
        transaction_id = self.request.query_params.get('transaction')
        if transaction_id:
            queryset = queryset.filter(transaction_id=transaction_id)
        return queryset

    def _require_draft(self, financial_transaction):
        if financial_transaction.status != FinancialTransaction.Status.DRAFT:
            raise PermissionDenied(
                f"Cannot modify lines on a financial transaction once it is {financial_transaction.get_status_display()}."
            )

    def perform_create(self, serializer):
        self._require_draft(serializer.validated_data['transaction'])
        serializer.save()

    def perform_update(self, serializer):
        self._require_draft(serializer.instance.transaction)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_draft(instance.transaction)
        instance.delete()
