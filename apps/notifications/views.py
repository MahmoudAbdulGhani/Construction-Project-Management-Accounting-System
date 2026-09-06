"""
DRF viewsets for the ``notifications`` app (CPMAS-22).

``NotificationViewSet`` exposes the per-user alert inbox;
``NotificationPreferenceView`` exposes the Notifications settings tab's
per-alert-type toggles (Owner only).
"""
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsOwner

from .models import Notification, NotificationPreference, NotificationType
from .serializers import NotificationPreferenceSerializer, NotificationSerializer


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    list/retrieve/create for notifications -- no generic update/destroy;
    ``is_read`` changes only through mark_read/mark_all_read below.

    Filterable by ?user=, ?is_read=, ?notification_type=.
    """

    queryset = Notification.objects.select_related('user').all()
    serializer_class = NotificationSerializer
    search_fields = ['title', 'message']
    ordering_fields = ['created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        user_id = params.get('user')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        is_read = params.get('is_read')
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() in ('true', '1'))

        notification_type = params.get('notification_type')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type.upper())

        return queryset

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """POST /api/notifications/notifications/{id}/mark_read/"""
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """
        POST /api/notifications/notifications/mark_all_read/?user=<uuid>
        Marks every unread notification in the current (filtered)
        queryset as read -- e.g. ?user=<uuid> to clear one user's inbox.
        """
        updated = self.filter_queryset(self.get_queryset()).filter(is_read=False).update(is_read=True)
        return Response({'marked_read': updated})


class NotificationPreferenceView(APIView):
    """
    GET / PATCH the per-alert-type notification preferences.

    - GET   /api/notifications/preferences/  -> keyed dict of all six BRD 9
              alert types, each with is_enabled / window_days plus read-only
              display metadata (label, role, description).
    - PATCH /api/notifications/preferences/  -> accepts a keyed subset, e.g.
              {"PAYMENT_DUE": {"is_enabled": false, "window_days": 5}},
              updating only the provided types.

    Security: Owner only, matching CompanyProfile/FinancialSettings (the
    Settings pages are only reachable by the Owner role).
    """

    permission_classes = [IsOwner]

    def _all(self):
        """
        Ensure every catalogued alert type has a preference row and return
        them as a {notification_type: preference} mapping.
        """
        existing = {p.notification_type: p for p in NotificationPreference.objects.all()}
        created_types = [
            t for t in NotificationType.values if t not in existing
        ]
        if created_types:
            NotificationPreference.objects.bulk_create(
                [NotificationPreference(notification_type=t) for t in created_types]
            )
            for p in NotificationPreference.objects.filter(notification_type__in=created_types):
                existing[p.notification_type] = p
        return existing

    def get(self, request):
        prefs = self._all()
        data = {
            t: NotificationPreferenceSerializer(prefs[t]).data
            for t in NotificationType.values
        }
        return Response(data)

    def patch(self, request):
        prefs = self._all()
        for key, updates in request.data.items():
            if key not in prefs or not isinstance(updates, dict):
                continue
            instance = prefs[key]
            serializer = NotificationPreferenceSerializer(instance, data=updates, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return self.get(request)
