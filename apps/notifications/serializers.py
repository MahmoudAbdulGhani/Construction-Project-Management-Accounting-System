"""
DRF serializers for the ``notifications`` app (CPMAS-22).
"""
from rest_framework import serializers

from .models import (
    ALERT_TYPE_DESCRIPTION,
    ALERT_TYPE_ROLE,
    Notification,
    NotificationPreference,
    NotificationType,
)


class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer for Notification CRUD.

    ``is_read`` is read-only here: it only ever changes through the
    viewset's mark_read/mark_all_read actions, never a raw PATCH -- same
    read-only-status pattern used for every other state field in this
    codebase (PurchaseOrder.status, Expense.status, etc).
    """

    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'notification_type', 'title', 'message',
            'entity_type', 'entity_id', 'is_read', 'created_at',
        ]
        read_only_fields = ['is_read', 'created_at']


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for a single BRD 9 alert-type preference (the Notifications
    settings tab). ``label``/``role``/``description`` are read-only display
    metadata derived from the fixed alert-type catalog; ``window_days`` is
    only meaningful for the types that have a time horizon, so the UI shows
    it accordingly.
    """

    label = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()

    class Meta:
        model = NotificationPreference
        fields = [
            'notification_type', 'label', 'role', 'description',
            'is_enabled', 'window_days',
        ]

    def get_label(self, obj):
        return NotificationType(obj.notification_type).label

    def get_role(self, obj):
        return ALERT_TYPE_ROLE.get(obj.notification_type, 'OWNER')

    def get_description(self, obj):
        return ALERT_TYPE_DESCRIPTION.get(obj.notification_type, '')
