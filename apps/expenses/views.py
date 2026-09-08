"""
DRF viewsets for the ``expenses`` app -- Expense Management slice
(CPMAS-33).
"""
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Expense, ExpenseCategory
from .serializers import ExpenseCategorySerializer, ExpenseSerializer, apply_transition


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    """CRUD API for expense categories -- simple reference-data maintenance."""

    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    search_fields = ['name']
    ordering_fields = ['name']


class ExpenseViewSet(viewsets.ModelViewSet):
    """
    CRUD + status-transition API for expenses.

    Header fields stay editable via the normal update route while the
    expense is not yet paid (unlike PurchaseOrder/SupplierInvoice, a
    PENDING/APPROVED expense has no child line items whose totals could
    drift out of sync, so there's no DRAFT-style edit lock); once an
    expense is PAID -- a state that recognizes it in the general ledger
    via book_expense -- the header is locked: updating any field or
    deleting the row would leave the ledger recording money the record
    no longer describes. Status itself is changed only through the
    approve/mark_paid/reject actions below.
    """

    queryset = Expense.objects.select_related('project', 'category', 'supplier').all()
    serializer_class = ExpenseSerializer
    search_fields = ['description', 'project__name', 'project__code']
    ordering_fields = ['expense_date', 'amount', 'created_at']

    def _reject_if_paid(self) -> None:
        """A PAID expense (already booked in the GL) must not be edited or
        deleted -- doing so would desync the general ledger, which this
        codebase treats as immutable history (same reasoning as the
        invoicing/payments paid-lock rules)."""
        expense = self.get_object()
        if expense.status == Expense.Status.PAID:
            raise serializers.ValidationError(
                {"status": "A paid expense is locked and cannot be modified or deleted."}
            )

    def update(self, request, *args, **kwargs):
        self._reject_if_paid()
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._reject_if_paid()
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._reject_if_paid()
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        project_id = params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        category_id = params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        status_param = params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param.upper())

        supplier_id = params.get('supplier')
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)

        date_from = params.get('date_from')
        if date_from:
            queryset = queryset.filter(expense_date__gte=date_from)

        date_to = params.get('date_to')
        if date_to:
            queryset = queryset.filter(expense_date__lte=date_to)

        return queryset

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """POST /api/expenses/expenses/{id}/approve/ -- PENDING -> APPROVED."""
        expense = apply_transition(self.get_object(), Expense.Status.APPROVED)
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """POST /api/expenses/expenses/{id}/mark_paid/ -- APPROVED -> PAID."""
        expense = apply_transition(self.get_object(), Expense.Status.PAID)
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """POST /api/expenses/expenses/{id}/reject/ -- PENDING/APPROVED -> REJECTED."""
        expense = apply_transition(self.get_object(), Expense.Status.REJECTED)
        return Response(self.get_serializer(expense).data)
