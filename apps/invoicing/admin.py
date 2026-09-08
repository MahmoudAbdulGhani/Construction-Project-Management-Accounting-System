"""
Django admin registration for the ``invoicing`` app -- Supplier Invoices
(CPMAS-32), Client Invoices (CPMAS-35), and Contractor Invoices.
"""
from django.contrib import admin

from .models import (
    ClientInvoice,
    ClientInvoiceItem,
    ContractorInvoice,
    ContractorInvoiceItem,
    SupplierInvoice,
    SupplierInvoiceItem,
)


class SupplierInvoiceItemInline(admin.TabularInline):
    """Inline editing of line items on the SupplierInvoice admin page."""

    model = SupplierInvoiceItem
    extra = 0
    autocomplete_fields = ('material', 'tax_rate')
    readonly_fields = ('tax_amount', 'total_amount')


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    """
    Admin view for SupplierInvoice. subtotal/tax_amount/total_amount are
    read-only -- derived from line items (see invoicing.services), never
    hand-edited, even in the admin.
    """

    list_display = ('invoice_number', 'supplier', 'status', 'invoice_date', 'due_date', 'total_amount')
    list_filter = ('status', 'supplier')
    search_fields = ('invoice_number', 'supplier__name')
    autocomplete_fields = ('supplier', 'purchase_order')
    readonly_fields = ('subtotal', 'tax_amount', 'total_amount', 'created_at', 'updated_at')
    inlines = [SupplierInvoiceItemInline]


@admin.register(SupplierInvoiceItem)
class SupplierInvoiceItemAdmin(admin.ModelAdmin):
    """Standalone admin view for SupplierInvoiceItem (in addition to the inline above)."""

    list_display = ('supplier_invoice', 'description', 'quantity', 'unit_price', 'total_amount')
    list_filter = ('supplier_invoice__status',)
    search_fields = ('supplier_invoice__invoice_number', 'description', 'material__name')
    autocomplete_fields = ('supplier_invoice', 'material', 'tax_rate')
    readonly_fields = ('tax_amount', 'total_amount')


class ClientInvoiceItemInline(admin.TabularInline):
    """Inline editing of line items on the ClientInvoice admin page."""

    model = ClientInvoiceItem
    extra = 0
    autocomplete_fields = ('tax_rate',)
    readonly_fields = ('tax_amount', 'total_amount')


@admin.register(ClientInvoice)
class ClientInvoiceAdmin(admin.ModelAdmin):
    """
    Admin view for ClientInvoice. subtotal/discount_amount/tax_amount/
    total_amount are read-only -- derived from line items, never
    hand-edited, even in the admin.
    """

    list_display = ('invoice_number', 'client', 'status', 'invoice_date', 'due_date', 'total_amount')
    list_filter = ('status', 'client')
    search_fields = ('invoice_number', 'client__name')
    autocomplete_fields = ('client', 'project')
    readonly_fields = ('subtotal', 'discount_amount', 'tax_amount', 'total_amount', 'created_at', 'updated_at')
    inlines = [ClientInvoiceItemInline]


@admin.register(ClientInvoiceItem)
class ClientInvoiceItemAdmin(admin.ModelAdmin):
    """Standalone admin view for ClientInvoiceItem (in addition to the inline above)."""

    list_display = ('client_invoice', 'description', 'quantity', 'unit_price', 'total_amount')
    list_filter = ('client_invoice__status',)
    search_fields = ('client_invoice__invoice_number', 'description')
    autocomplete_fields = ('client_invoice', 'tax_rate')
    readonly_fields = ('tax_amount', 'total_amount')


class ContractorInvoiceItemInline(admin.TabularInline):
    """Inline editing of line items on the ContractorInvoice admin page."""

    model = ContractorInvoiceItem
    extra = 0
    autocomplete_fields = ('tax_rate',)
    readonly_fields = ('tax_amount', 'total_amount')


@admin.register(ContractorInvoice)
class ContractorInvoiceAdmin(admin.ModelAdmin):
    """
    Admin view for ContractorInvoice. subtotal/tax_amount/total_amount
    are read-only -- derived from line items (see invoicing.services),
    never hand-edited, even in the admin.
    """

    list_display = ('invoice_number', 'contractor_id', 'status', 'invoice_date', 'due_date', 'total_amount')
    list_filter = ('status',)
    search_fields = ('invoice_number',)
    readonly_fields = ('contractor_id', 'subtotal', 'tax_amount', 'total_amount', 'created_at', 'updated_at')
    inlines = [ContractorInvoiceItemInline]


@admin.register(ContractorInvoiceItem)
class ContractorInvoiceItemAdmin(admin.ModelAdmin):
    """Standalone admin view for ContractorInvoiceItem (in addition to the inline above)."""

    list_display = ('contractor_invoice', 'description', 'quantity', 'unit_price', 'total_amount')
    list_filter = ('contractor_invoice__status',)
    search_fields = ('contractor_invoice__invoice_number', 'description')
    autocomplete_fields = ('contractor_invoice', 'tax_rate')
    readonly_fields = ('tax_amount', 'total_amount')
