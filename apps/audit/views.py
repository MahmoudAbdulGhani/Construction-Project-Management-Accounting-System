"""
Read-only Audit Trail API.

Exposes list/retrieve only -- there are no create/update/delete endpoints,
so the trail cannot be tampered with through the HTTP surface. Visibility is
Owner-only: the trail documents administrative actions (user management, tax
rate changes), and the Settings page itself is Owner-only.
"""
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from users.permissions import IsOwner

from .models import AuditLog
from .serializers import AuditLogSerializer


@api_view(['GET'])
@permission_classes([IsOwner])
def audit_entities(request):
    """Owner-only metadata: the auditable entity types, for the UI dropdown."""
    from .registry import AUDITABLE_MODELS

    entities = [
        {
            'entity_type': info['entity_type'],
            'label': info['label'],
            'category': info.get('category') or 'Other',
        }
        for info in AUDITABLE_MODELS.values()
    ]
    entities.sort(key=lambda e: (e['category'].lower(), e['label'].lower()))
    return Response(entities, status=status.HTTP_200_OK)


class AuditLogFilter(django_filters.FilterSet):
    created_after = django_filters.IsoDateTimeFilter(
        field_name='created_at', lookup_expr='gte')
    created_before = django_filters.IsoDateTimeFilter(
        field_name='created_at', lookup_expr='lte')
    user = django_filters.UUIDFilter(field_name='user_id')

    class Meta:
        model = AuditLog
        fields = ['action', 'entity_type', 'entity_id']


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve audit entries, newest first."""

    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsOwner]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = AuditLogFilter
    search_fields = ['action', 'entity_type', 'user__username']
    ordering_fields = ['created_at', 'action', 'entity_type', 'user__username']
    ordering = ['-created_at']