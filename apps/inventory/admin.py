"""
Django admin registration for the ``inventory`` app -- Material Management
(CPMAS-28) and Inventory & Warehouse Management (CPMAS-29) slices.
"""
from django.contrib import admin
from django.db import transaction

from .models import Material, MaterialCategory, Stock, StockMovement, Warehouse
from .services import apply_stock_movement


@admin.register(MaterialCategory)
class MaterialCategoryAdmin(admin.ModelAdmin):
    """Admin list/search configuration for MaterialCategory."""

    list_display = ('name', 'description')
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    """Admin list/search/filter configuration for Material."""

    list_display = (
        'name', 'sku', 'category', 'unit', 'standard_cost',
        'minimum_stock_level', 'is_active',
    )
    list_filter = ('category', 'is_active', 'tax_rate', 'default_supplier')
    search_fields = ('name', 'sku')
    ordering = ('name',)
    autocomplete_fields = ('category', 'tax_rate', 'default_supplier')


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    """Admin list/search configuration for Warehouse."""

    list_display = ('name', 'location', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    """
    Admin view for Stock. Deliberately read-only (no add/change/delete
    permission) -- quantity must only ever change via StockMovement, per
    BR 12.6, so the admin shouldn't offer a way around that either.
    """

    list_display = ('material', 'warehouse', 'quantity', 'updated_at')
    list_filter = ('warehouse',)
    search_fields = ('material__name', 'material__sku', 'warehouse__name')
    autocomplete_fields = ('warehouse', 'material')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """
    Admin view for StockMovement. Add is allowed so a user can record a
    movement from the admin UI, but the resulting Stock balance must stay
    in sync (BR 12.6): a plain ORM save() would only create the ledger row
    without moving stock, so save_model applies the movement to Stock via
    inventory.services.apply_stock_movement -- the same function every other
    entry path uses -- so a movement recorded here updates the on-hand
    quantity exactly like one recorded through the API. Both the ledger row
    and the balance change are wrapped in one transaction. Change/delete are
    disabled: this is an append-only ledger.
    """

    list_display = (
        'movement_type', 'material', 'warehouse', 'quantity',
        'movement_date', 'user', 'reference',
    )
    list_filter = ('movement_type', 'warehouse')
    search_fields = ('material__name', 'material__sku', 'reference')
    autocomplete_fields = ('material', 'warehouse')
    ordering = ('-movement_date',)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        # A brand-new movement goes through the model's normal save() first,
        # then is applied to Stock -- mirroring StockMovementSerializer.create
        # and purchasing.services.receive_goods, which both create the ledger
        # row and call apply_stock_movement. This is what keeps the admin
        # entry path from creating a movement without moving stock (the bug
        # where Stock Movements updated but Stock Quantities did not).
        super().save_model(request, obj, form, change)
        apply_stock_movement(obj)
