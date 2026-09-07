"""
DRF viewsets for the ``invoicing`` app.

Handles client, supplier, and contractor invoices and their line items.
"""

from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from construction.filtering import filter_date_range

from .models import (
    ClientInvoice,
    ClientInvoiceItem,
    ContractorInvoice,
    ContractorInvoiceItem,
    SupplierInvoice,
    SupplierInvoiceItem,
)
from .serializers import (
    ClientInvoiceItemSerializer,
    ClientInvoiceSerializer,
    ContractorInvoiceItemSerializer,
    ContractorInvoiceSerializer,
    SupplierInvoiceItemSerializer,
    SupplierInvoiceSerializer,
    apply_client_transition,
    apply_contractor_transition,
    apply_transition,
)
from .services import (
    generate_invoice_number,
    recalculate_client_invoice_totals,
    recalculate_contractor_invoice_totals,
    recalculate_invoice_totals,
    sync_overdue_statuses,
)


# =========================================================
# Supplier Invoices
# =========================================================

class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    queryset = (
        SupplierInvoice.objects
        .select_related("supplier", "purchase_order")
        .prefetch_related("items")
        .all()
    )
    serializer_class = SupplierInvoiceSerializer
    search_fields = ["invoice_number", "supplier__name"]
    ordering_fields = [
        "invoice_date",
        "due_date",
        "total_amount",
        "created_at",
    ]

    def get_queryset(self):
        sync_overdue_statuses()

        queryset = super().get_queryset()
        params = self.request.query_params

        supplier_id = params.get("supplier")
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)

        status_param = params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param.upper())

        purchase_order_id = params.get("purchase_order")
        if purchase_order_id:
            queryset = queryset.filter(
                purchase_order_id=purchase_order_id
            )

        queryset = filter_date_range(
            queryset,
            params,
            "invoice_date",
        )

        return queryset

    def _require_draft(self, invoice):
        if invoice.status != SupplierInvoice.Status.DRAFT:
            raise PermissionDenied(
                f"Cannot edit a supplier invoice once it is "
                f"{invoice.get_status_display()}."
            )

    def perform_update(self, serializer):
        self._require_draft(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_draft(instance)
        instance.delete()

    @action(detail=True, methods=["post"])
    def mark_sent(self, request, pk=None):
        invoice = apply_transition(
            self.get_object(),
            SupplierInvoice.Status.SENT,
        )
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        invoice = apply_transition(
            self.get_object(),
            SupplierInvoice.Status.CANCELLED,
        )
        return Response(self.get_serializer(invoice).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="next-number",
    )
    def next_number(self, request):
        return Response({
            "invoice_number": generate_invoice_number(SupplierInvoice)
        })


# =========================================================
# Supplier Invoice Items
# =========================================================

class SupplierInvoiceItemViewSet(viewsets.ModelViewSet):
    queryset = (
        SupplierInvoiceItem.objects
        .select_related(
            "material",
            "tax_rate",
            "supplier_invoice",
        )
        .all()
    )
    serializer_class = SupplierInvoiceItemSerializer
    search_fields = ["description", "material__name"]

    def get_queryset(self):
        queryset = super().get_queryset()

        invoice_id = self.request.query_params.get(
            "supplier_invoice"
        )

        if invoice_id:
            queryset = queryset.filter(
                supplier_invoice_id=invoice_id
            )

        return queryset

    def _require_draft(self, invoice):
        if invoice.status != SupplierInvoice.Status.DRAFT:
            raise PermissionDenied(
                f"Cannot modify items on a supplier invoice once "
                f"it is {invoice.get_status_display()}."
            )

    @transaction.atomic
    def perform_create(self, serializer):
        invoice = serializer.validated_data["supplier_invoice"]

        self._require_draft(invoice)

        serializer.save()

        # Recalculate the parent invoice immediately.
        recalculate_invoice_totals(invoice)

    @transaction.atomic
    def perform_update(self, serializer):
        invoice = serializer.instance.supplier_invoice

        self._require_draft(invoice)

        serializer.save()

        # Recalculate after changing an item.
        recalculate_invoice_totals(invoice)

    @transaction.atomic
    def perform_destroy(self, instance):
        invoice = instance.supplier_invoice

        self._require_draft(invoice)

        instance.delete()

        # Recalculate after deleting an item.
        recalculate_invoice_totals(invoice)


# =========================================================
# Client Invoices
# =========================================================

class ClientInvoiceViewSet(viewsets.ModelViewSet):
    queryset = (
        ClientInvoice.objects
        .select_related("client", "project")
        .prefetch_related("items")
        .all()
    )
    serializer_class = ClientInvoiceSerializer
    search_fields = ["invoice_number", "client__name"]
    ordering_fields = [
        "invoice_date",
        "due_date",
        "total_amount",
        "created_at",
    ]

    def get_queryset(self):
        sync_overdue_statuses()

        queryset = super().get_queryset()
        params = self.request.query_params

        client_id = params.get("client")
        if client_id:
            queryset = queryset.filter(client_id=client_id)

        status_param = params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param.upper())

        project_id = params.get("project")
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        queryset = filter_date_range(
            queryset,
            params,
            "invoice_date",
        )

        return queryset

    def _require_draft(self, invoice):
        if invoice.status != ClientInvoice.Status.DRAFT:
            raise PermissionDenied(
                f"Cannot edit a client invoice once it is "
                f"{invoice.get_status_display()}."
            )

    def perform_update(self, serializer):
        self._require_draft(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_draft(instance)
        instance.delete()

    @action(detail=True, methods=["post"])
    def mark_sent(self, request, pk=None):
        invoice = apply_client_transition(
            self.get_object(),
            ClientInvoice.Status.SENT,
        )
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        invoice = apply_client_transition(
            self.get_object(),
            ClientInvoice.Status.CANCELLED,
        )
        return Response(self.get_serializer(invoice).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="next-number",
    )
    def next_number(self, request):
        return Response({
            "invoice_number": generate_invoice_number(ClientInvoice)
        })


# =========================================================
# Client Invoice Items
# =========================================================

class ClientInvoiceItemViewSet(viewsets.ModelViewSet):
    queryset = (
        ClientInvoiceItem.objects
        .select_related(
            "tax_rate",
            "client_invoice",
        )
        .all()
    )
    serializer_class = ClientInvoiceItemSerializer
    search_fields = ["description"]

    def get_queryset(self):
        queryset = super().get_queryset()

        invoice_id = self.request.query_params.get(
            "client_invoice"
        )

        if invoice_id:
            queryset = queryset.filter(
                client_invoice_id=invoice_id
            )

        return queryset

    def _require_draft(self, invoice):
        if invoice.status != ClientInvoice.Status.DRAFT:
            raise PermissionDenied(
                "Cannot modify items on a client invoice "
                "once it has left DRAFT."
            )

    @transaction.atomic
    def perform_create(self, serializer):
        invoice = serializer.validated_data["client_invoice"]

        self._require_draft(invoice)

        serializer.save()

        # Recalculate the parent invoice immediately.
        recalculate_client_invoice_totals(invoice)

    @transaction.atomic
    def perform_update(self, serializer):
        invoice = serializer.instance.client_invoice

        self._require_draft(invoice)

        serializer.save()

        # Recalculate after changing an item.
        recalculate_client_invoice_totals(invoice)

    @transaction.atomic
    def perform_destroy(self, instance):
        invoice = instance.client_invoice

        self._require_draft(invoice)

        instance.delete()

        # Recalculate after deleting an item.
        recalculate_client_invoice_totals(invoice)


# =========================================================
# Contractor Invoices
# =========================================================

class ContractorInvoiceViewSet(viewsets.ModelViewSet):
    queryset = (
        ContractorInvoice.objects
        .prefetch_related("items")
        .all()
    )
    serializer_class = ContractorInvoiceSerializer
    search_fields = ["invoice_number"]
    ordering_fields = [
        "invoice_date",
        "due_date",
        "total_amount",
        "created_at",
    ]

    def get_queryset(self):
        sync_overdue_statuses()

        queryset = super().get_queryset()
        params = self.request.query_params

        contractor_id = params.get("contractor")
        if contractor_id:
            queryset = queryset.filter(
                contractor_id=contractor_id
            )

        status_param = params.get("status")
        if status_param:
            queryset = queryset.filter(
                status=status_param.upper()
            )

        queryset = filter_date_range(
            queryset,
            params,
            "invoice_date",
        )

        return queryset

    def _require_draft(self, invoice):
        if invoice.status != ContractorInvoice.Status.DRAFT:
            raise PermissionDenied(
                f"Cannot edit a contractor invoice once it is "
                f"{invoice.get_status_display()}."
            )

    def perform_update(self, serializer):
        self._require_draft(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_draft(instance)
        instance.delete()

    @action(detail=True, methods=["post"])
    def mark_sent(self, request, pk=None):
        invoice = apply_contractor_transition(
            self.get_object(),
            ContractorInvoice.Status.SENT,
        )
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        invoice = apply_contractor_transition(
            self.get_object(),
            ContractorInvoice.Status.CANCELLED,
        )
        return Response(self.get_serializer(invoice).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="next-number",
    )
    def next_number(self, request):
        return Response({
            "invoice_number": generate_invoice_number(
                ContractorInvoice
            )
        })


# =========================================================
# Contractor Invoice Items
# =========================================================

class ContractorInvoiceItemViewSet(viewsets.ModelViewSet):
    queryset = (
        ContractorInvoiceItem.objects
        .select_related(
            "tax_rate",
            "contractor_invoice",
        )
        .all()
    )
    serializer_class = ContractorInvoiceItemSerializer
    search_fields = ["description"]

    def get_queryset(self):
        queryset = super().get_queryset()

        invoice_id = self.request.query_params.get(
            "contractor_invoice"
        )

        if invoice_id:
            queryset = queryset.filter(
                contractor_invoice_id=invoice_id
            )

        return queryset

    def _require_draft(self, invoice):
        if invoice.status != ContractorInvoice.Status.DRAFT:
            raise PermissionDenied(
                "Cannot modify items on a contractor invoice "
                "once it has left DRAFT."
            )

    @transaction.atomic
    def perform_create(self, serializer):
        invoice = serializer.validated_data["contractor_invoice"]

        self._require_draft(invoice)

        serializer.save()

        # Recalculate the parent invoice immediately.
        recalculate_contractor_invoice_totals(invoice)

    @transaction.atomic
    def perform_update(self, serializer):
        invoice = serializer.instance.contractor_invoice

        self._require_draft(invoice)

        serializer.save()

        # Recalculate after changing an item.
        recalculate_contractor_invoice_totals(invoice)

    @transaction.atomic
    def perform_destroy(self, instance):
        invoice = instance.contractor_invoice

        self._require_draft(invoice)

        instance.delete()

        # Recalculate after deleting an item.
        recalculate_contractor_invoice_totals(invoice)