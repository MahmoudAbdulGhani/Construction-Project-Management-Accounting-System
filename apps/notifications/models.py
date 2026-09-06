"""
Models for the ``notifications`` app -- System Notifications slice
(CPMAS-22, BRD 9: "Alerts for: Overdue invoices, Payment due, Low
inventory, PO/Change order awaiting approval, Budget overruns,
Deadline approaches").

Implements ``Notification``, matching the ``notifications`` table in
the approved schema, and ``NotificationPreference`` (the new
``notification_preferences`` table the Notifications settings tab
edits -- one row per BRD 9 alert type, used to enable/disable each
alert and tune its look-ahead window).

Notifications are created by ``notifications.services`` (one function
per BRD 9 alert type, run via the ``generate_notifications``
management command) -- there is no signal-based auto-generation wired
into other apps' write paths, so adding this app doesn't change any
existing app's behavior.
"""
import uuid

from django.db import models


class NotificationType(models.TextChoices):
    """
    The fixed set of alert types this app's own generators produce
    (BRD 9). ``notification_type`` on the model itself is a plain
    CharField, not constrained to this list at the DB layer -- the
    schema's column is a plain VARCHAR, and other future callers may
    reasonably want a type not enumerated here.
    """
    OVERDUE_INVOICE = 'OVERDUE_INVOICE', 'Overdue Invoice'
    PAYMENT_DUE = 'PAYMENT_DUE', 'Payment Due'
    LOW_INVENTORY = 'LOW_INVENTORY', 'Low Inventory'
    PO_AWAITING_APPROVAL = 'PO_AWAITING_APPROVAL', 'PO Awaiting Approval'
    BUDGET_OVERRUN = 'BUDGET_OVERRUN', 'Budget Overrun'
    DEADLINE_APPROACHING = 'DEADLINE_APPROACHING', 'Deadline Approaching'


class Notification(models.Model):
    """
    A single alert directed at one user. Matches the ``notifications``
    table exactly.

    ``entity_type``/``entity_id`` are a generic, non-FK pointer to
    whatever triggered the notification (e.g. entity_type=
    'client_invoice', entity_id=<uuid>) -- deliberately not a real
    ForeignKey, since one notifications table has to be able to point
    at many different kinds of entities across apps. Same pattern as
    the schema's own ``documents.entity_type``/``entity_id``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # PROTECT: the schema's plain REFERENCES users(id) with no ON DELETE
    # clause defaults to Postgres's NO ACTION (blocks the delete) --
    # same reasoning as every other required, clause-less FK in this
    # codebase (PurchaseOrder.created_by, Payment.created_by, etc).
    user = models.ForeignKey('users.User', on_delete=models.PROTECT, related_name='notifications')

    notification_type = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=255)
    message = models.TextField()

    entity_type = models.CharField(max_length=100, blank=True, null=True)
    entity_id = models.UUIDField(blank=True, null=True)

    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        return self.title


# Which role each BRD 9 alert type is generated for (BRD 4.1/4.2 split:
# Accountant owns invoices/payments, Owner owns projects/purchasing/inventory).
ALERT_TYPE_ROLE = {
    NotificationType.OVERDUE_INVOICE: 'ACCOUNTANT',
    NotificationType.PAYMENT_DUE: 'ACCOUNTANT',
    NotificationType.LOW_INVENTORY: 'OWNER',
    NotificationType.PO_AWAITING_APPROVAL: 'OWNER',
    NotificationType.BUDGET_OVERRUN: 'OWNER',
    NotificationType.DEADLINE_APPROACHING: 'OWNER',
}

# Look-ahead window (days) used when a type has a time horizon and no
# preference row overrides it. Types without a horizon are absent.
DEFAULT_WINDOW_DAYS = {
    NotificationType.PAYMENT_DUE: 3,
    NotificationType.DEADLINE_APPROACHING: 7,
}

# Human-friendly one-line descriptions for the settings UI.
ALERT_TYPE_DESCRIPTION = {
    NotificationType.OVERDUE_INVOICE: "Alert accountants when an invoice's due date has passed and it's still unpaid.",
    NotificationType.PAYMENT_DUE: "Alert accountants about invoices due within the look-ahead window (default 3 days).",
    NotificationType.LOW_INVENTORY: "Alert owners when a stock item drops below its minimum level.",
    NotificationType.PO_AWAITING_APPROVAL: "Alert owners when a purchase order is submitted and waiting for approval.",
    NotificationType.BUDGET_OVERRUN: "Alert owners when an active project's actual spend exceeds its budget.",
    NotificationType.DEADLINE_APPROACHING: "Alert owners when an active project's expected completion date nears (default 7 days).",
}


class NotificationPreference(models.Model):
    """
    Per-alert-type toggle for the Notifications settings tab.

    One row per BRD 9 alert type (``notification_type`` is the primary
    key). ``is_enabled`` controls whether that alert is generated at all;
    ``window_days`` overrides the look-ahead horizon for the types that
    have one (PAYMENT_DUE, DEADLINE_APPROACHING); it's null for types
    with no time horizon.

    Rows are created lazily (get_or_create) when the settings API first
    reads them, so a missing row simply means "enabled, default window"
    -- identical to the pre-preference behavior.
    """

    notification_type = models.CharField(max_length=100, primary_key=True)
    is_enabled = models.BooleanField(default=True)
    window_days = models.PositiveSmallIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_preferences'
        verbose_name = 'Notification preference'
        verbose_name_plural = 'Notification preferences'
        ordering = ['notification_type']

    def __str__(self):
        return f"{self.notification_type} ({'on' if self.is_enabled else 'off'})"
