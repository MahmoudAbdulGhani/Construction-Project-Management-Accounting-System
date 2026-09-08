"""API views for the ``taxes`` app (Tax Rates configuration)."""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from users.permissions import IsOwner, IsOwnerOrAccountant

from .models import TaxRate
from .serializers import TaxRateSerializer


class TaxRateViewSet(mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     mixins.CreateModelMixin,
                     mixins.UpdateModelMixin,
                     mixins.DestroyModelMixin,
                     viewsets.GenericViewSet):
    """
    Tax rate configuration API (Tax Management).

    Reads (list/retrieve) are available to any authenticated finance user
    (Owner or Accountant) -- tax rates are referenced across invoices,
    purchases, and materials, so both roles need to see them. Mutations
    (create/update/delete, activate/deactivate) are Owner-only, matching
    the administrative nature of the Tax Rates tab in Company settings.
    """

    queryset = TaxRate.objects.all()
    serializer_class = TaxRateSerializer
    search_fields = ['name', 'tax_type']
    ordering_fields = ['name', 'rate', 'tax_type', 'effective_date', 'is_active']
    ordering = ['name', '-effective_date']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy',
                           'activate', 'deactivate'):
            return [IsOwner()]
        return [IsOwnerOrAccountant()]

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        tax = self.get_object()
        tax._audit_action = 'ACTIVATE'
        tax.is_active = True
        tax.save(update_fields=['is_active'])
        return Response(self.get_serializer(tax).data)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        tax = self.get_object()
        tax._audit_action = 'DEACTIVATE'
        tax.is_active = False
        tax.save(update_fields=['is_active'])
        return Response(self.get_serializer(tax).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)