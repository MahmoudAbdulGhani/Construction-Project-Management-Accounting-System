"""
DRF viewsets for the ``payments`` app -- Accounts Receivable & Accounts
Payable (CPMAS-35) and Receipts (CPMAS-21) slices.
"""
from uuid import UUID

from django.http import HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from construction.filtering import filter_date_range
from users.permissions import IsOwnerOrAccountant

from .models import Payment, PaymentAllocation, Receipt
from .pdf import render_receipt_pdf
from .serializers import PaymentAllocationSerializer, PaymentSerializer, ReceiptSerializer
from .services import issue_receipt_for_payment


def _validated_uuid(params, name):
    """Return a valid UUID filter value or raise a controlled API 400."""
    value = params.get(name)
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError({name: "Must be a valid UUID."})


class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    Append-only ledger API for payments -- list/retrieve/create only, no
    update/destroy, same reasoning as
    inventory.views.StockMovementViewSet: a recorded payment is history,
    not something edited in place.

    Filterable by party, direction, and payment date.
    """

    # receipts/ through the reverse OneToOne for serializer.has_receipt.
    queryset = Payment.objects.select_related('client', 'supplier', 'created_by', 'receipt').prefetch_related('allocations').all()
    serializer_class = PaymentSerializer
    permission_classes = [IsOwnerOrAccountant]
    search_fields = ['payment_number', 'reference', 'client__name', 'supplier__name']
    ordering_fields = ['payment_date', 'amount', 'created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        direction = params.get('direction')
        if direction:
            queryset = queryset.filter(direction=direction.upper())

        client_id = _validated_uuid(params, 'client')
        if client_id:
            queryset = queryset.filter(client_id=client_id)

        supplier_id = _validated_uuid(params, 'supplier')
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)

        employee_id = _validated_uuid(params, 'employee')
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        contractor_id = _validated_uuid(params, 'contractor')
        if contractor_id:
            queryset = queryset.filter(contractor_id=contractor_id)

        queryset = filter_date_range(queryset, params, 'payment_date')

        return queryset

    def perform_create(self, serializer):
        # Auto-issue the payment's receipt, in either direction: money
        # received from a client and money paid out to a supplier/
        # employee/contractor are each receipted at record time (a
        # payment is a ledger entry -- the receipt comes with it, not as
        # a separate afterthought). issue_receipt_for_payment is a no-op
        # if a receipt somehow already exists.
        payment = serializer.save(created_by=self.request.user)
        issue_receipt_for_payment(payment)


class PaymentAllocationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                                mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    Append-only ledger API for payment allocations -- list/retrieve/
    create only. Creating one is how a payment gets applied to an
    invoice and how that invoice's status advances (see
    payments.services.allocate_payment); there is no "unallocate" -- a
    mistaken allocation is corrected the same way a mis-posted
    accounting entry is, with an explicit offsetting record, not an
    in-place edit.

    Filterable by ?payment=, ?client_invoice=, ?supplier_invoice=,
    ?contractor_invoice=.
    """

    queryset = PaymentAllocation.objects.select_related(
        'payment', 'client_invoice', 'supplier_invoice', 'contractor_invoice',
    ).all()
    serializer_class = PaymentAllocationSerializer
    permission_classes = [IsOwnerOrAccountant]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        payment_id = _validated_uuid(params, 'payment')
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)

        client_invoice_id = _validated_uuid(params, 'client_invoice')
        if client_invoice_id:
            queryset = queryset.filter(client_invoice_id=client_invoice_id)

        supplier_invoice_id = _validated_uuid(params, 'supplier_invoice')
        if supplier_invoice_id:
            queryset = queryset.filter(supplier_invoice_id=supplier_invoice_id)

        contractor_invoice_id = _validated_uuid(params, 'contractor_invoice')
        if contractor_invoice_id:
            queryset = queryset.filter(contractor_invoice_id=contractor_invoice_id)

        return queryset


class ReceiptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    Append-only API for receipts -- list/retrieve/create only, same
    immutability reasoning as PaymentViewSet.

    Filterable by ?client=/?supplier=/?payment= (BRD 5.3/5.4: a client's
    or supplier's profile should be able to list their receipts) -- all
    three filter through the receipt's payment, since Receipt itself has
    no client/supplier column of its own.
    """

    queryset = Receipt.objects.select_related('payment', 'payment__client', 'payment__supplier').all()
    serializer_class = ReceiptSerializer
    permission_classes = [IsOwnerOrAccountant]
    search_fields = ['receipt_number', 'reference', 'payment__payment_number']
    ordering_fields = ['receipt_date', 'created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        payment_id = _validated_uuid(params, 'payment')
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)

        client_id = _validated_uuid(params, 'client')
        if client_id:
            queryset = queryset.filter(payment__client_id=client_id)

        supplier_id = _validated_uuid(params, 'supplier')
        if supplier_id:
            queryset = queryset.filter(payment__supplier_id=supplier_id)

        queryset = filter_date_range(queryset, params, 'receipt_date')

        return queryset

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """
        GET /api/payments/receipts/{id}/download/ -- BRD 5.19
        "printable/downloadable receipts": returns the receipt as a PDF
        file attachment.
        """
        receipt = self.get_object()
        pdf_bytes = render_receipt_pdf(receipt)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{receipt.receipt_number}.pdf"'
        return response
