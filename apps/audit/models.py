"""
Models for the ``audit`` app -- Immutable Audit Trail.

Provides ``AuditLog``, an append-only record of user actions across the
system, backed by the existing ``audit_logs`` table in the canonical
schema (see docs/schema/README.md). Records who did what, to which
entity, when, and the previous/new JSON state of the affected record.

Immutability contract
---------------------
* Entries are created via the recording service (``audit.services``)
  which only ever performs INSERTs.
* The API layer exposes read-only list/retrieve only (no create/update/
  delete endpoints) -- see ``audit.views``.
* The table is owned by the schema (``managed = False``), mirroring how
  ``users.User`` keeps its lifecycle with the SQL source of truth, so no
  Django migration can ever silently alter or drop it.
"""
import uuid

from django.db import models


class AuditAction(models.TextChoices):
    """Normalised action verbs stored in ``action`` (VARCHAR(100))."""

    CREATE = 'CREATE', 'Created'
    UPDATE = 'UPDATE', 'Updated'
    DELETE = 'DELETE', 'Deleted'
    ACTIVATE = 'ACTIVATE', 'Activated'
    DEACTIVATE = 'DEACTIVATE', 'Deactivated'
    LOGIN = 'LOGIN', 'Logged in'
    LOGOUT = 'LOGOUT', 'Logged out'


class AuditLog(models.Model):
    """A single immutable audit entry for one user action."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        related_name='audit_logs',
        null=True,
        blank=True,
        db_column='user_id',
    )
    action = models.CharField(max_length=100, choices=AuditAction.choices)
    entity_type = models.CharField(max_length=100)
    entity_id = models.UUIDField()
    old_values = models.JSONField(blank=True, null=True)
    new_values = models.JSONField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'audit_logs'
        ordering = ['-created_at']
        verbose_name = 'Audit log entry'
        verbose_name_plural = 'Audit log entries'
        indexes = [
            models.Index(fields=['user'], name='idx_audit_logs_user'),
            models.Index(fields=['entity_type', 'entity_id'], name='idx_audit_logs_entity'),
        ]

    def __str__(self):
        who = self.user.username if self.user_id else 'system'
        return f'{self.created_at:%Y-%m-%d %H:%M:%S} {who} {self.action} {self.entity_type}'