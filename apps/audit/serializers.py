"""
Read-only serializers for the Audit Trail API.

Entries are never written through the API -- the recording service
(``audit.services``) is the only writer. ``user_name`` is a flattened
convenience for the UI (``null`` = system entry).
"""
from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'user_name', 'action', 'entity_type',
            'entity_id', 'old_values', 'new_values', 'ip_address',
            'created_at',
        ]
        read_only_fields = fields