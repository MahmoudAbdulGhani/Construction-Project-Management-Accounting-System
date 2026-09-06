"""
Alert-generation logic for the ``notifications`` app (CPMAS-22, BRD 9).

One function per BRD 9 alert type, each a plain query over another
app's models that creates ``Notification`` rows for whatever currently
matches. ``generate_all_notifications`` runs all six and is meant to be
invoked periodically -- see the ``generate_notifications`` management
command -- this project has no cron/task-queue infrastructure, so
actually scheduling that call is a deployment decision, not something
wired in here.

Every generator is deduplicating: it won't create a second notification
for the same (user, notification_type, entity_type, entity_id) while an
earlier one is still unread, so re-running this on a schedule doesn't
spam the same still-outstanding condition every time it runs.

Recipients follow the BRD 4.1/4.2 role split: Accountant owns invoices/
payments, Owner owns projects/purchasing/inventory.
"""
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from invoicing.models import ClientInvoice, SupplierInvoice
from inventory.models import Stock
from projects.models import Project, get_active_budget, get_budget_summary
from purchasing.models import PurchaseOrder
from users.models import Role, User

from .models import Notification, NotificationPreference, NotificationType

# How many days ahead "payment due" / "deadline approaching" look.
DUE_SOON_WINDOW_DAYS = 3
DEADLINE_WINDOW_DAYS = 7


def _pref_enabled(notification_type):
    """Whether an alert type is enabled. A missing row means enabled (True)."""
    return NotificationPreference.objects.filter(
        notification_type=notification_type, is_enabled=True
    ).exists() or not NotificationPreference.objects.filter(
        notification_type=notification_type
    ).exists()


def _pref_window(notification_type, default_days):
    """Look-ahead window for a type, falling back to ``default_days`` when
    no row or no override exists."""
    row = NotificationPreference.objects.filter(notification_type=notification_type).first()
    if row is not None and row.window_days is not None:
        return row.window_days
    return default_days

# Invoice statuses that are still owed money -- BRD 5.23/5.24's
# "outstanding" set. DRAFT is excluded: it hasn't been sent, so it
# carries no real due-date obligation yet.
_OUTSTANDING_INVOICE_STATUSES = [
    ClientInvoice.Status.SENT, ClientInvoice.Status.PARTIALLY_PAID, ClientInvoice.Status.OVERDUE,
]


def _recipients(role):
    return User.objects.filter(role=role, is_active=True)


def _notify(user, notification_type, title, message, entity_type=None, entity_id=None):
    """
    Create a Notification unless an unread one already exists for the
    same (user, notification_type, entity_type, entity_id) -- see
    module docstring on why this is deduplicated.
    """
    already_pending = Notification.objects.filter(
        user=user, notification_type=notification_type,
        entity_type=entity_type, entity_id=entity_id, is_read=False,
    ).exists()
    if already_pending:
        return None
    return Notification.objects.create(
        user=user, notification_type=notification_type, title=title, message=message,
        entity_type=entity_type, entity_id=entity_id,
    )


def _invoice_alerts(notification_type, title_fmt, message_fmt, invoice_querysets_and_types):
    """Shared loop for overdue_invoice_alerts/payment_due_alerts -- both walk the same two invoice models."""
    created = []
    accountants = list(_recipients(Role.ACCOUNTANT))
    for queryset, entity_type in invoice_querysets_and_types:
        for invoice in queryset:
            for user in accountants:
                notification = _notify(
                    user, notification_type,
                    title_fmt.format(invoice=invoice),
                    message_fmt.format(invoice=invoice),
                    entity_type=entity_type, entity_id=invoice.id,
                )
                if notification:
                    created.append(notification)
    return created


def overdue_invoice_alerts(today=None):
    """BRD 9 "Overdue invoices": due_date has passed and it's still outstanding."""
    if not _pref_enabled(NotificationType.OVERDUE_INVOICE):
        return []
    today = today or timezone.now().date()
    client_qs = ClientInvoice.objects.filter(due_date__lt=today, status__in=_OUTSTANDING_INVOICE_STATUSES)
    supplier_qs = SupplierInvoice.objects.filter(due_date__lt=today, status__in=_OUTSTANDING_INVOICE_STATUSES)
    return _invoice_alerts(
        NotificationType.OVERDUE_INVOICE,
        "Invoice {invoice.invoice_number} is overdue",
        "Invoice {invoice.invoice_number} was due on {invoice.due_date} and is still outstanding.",
        [(client_qs, 'client_invoice'), (supplier_qs, 'supplier_invoice')],
    )


def payment_due_alerts(today=None, window_days=DUE_SOON_WINDOW_DAYS):
    """BRD 9 "Payment due": due soon, not yet overdue."""
    if not _pref_enabled(NotificationType.PAYMENT_DUE):
        return []
    today = today or timezone.now().date()
    window_days = _pref_window(NotificationType.PAYMENT_DUE, window_days)
    horizon = today + timedelta(days=window_days)
    client_qs = ClientInvoice.objects.filter(due_date__gte=today, due_date__lte=horizon, status__in=_OUTSTANDING_INVOICE_STATUSES)
    supplier_qs = SupplierInvoice.objects.filter(due_date__gte=today, due_date__lte=horizon, status__in=_OUTSTANDING_INVOICE_STATUSES)
    return _invoice_alerts(
        NotificationType.PAYMENT_DUE,
        "Invoice {invoice.invoice_number} is due soon",
        "Invoice {invoice.invoice_number} is due on {invoice.due_date}.",
        [(client_qs, 'client_invoice'), (supplier_qs, 'supplier_invoice')],
    )


def low_inventory_alerts():
    """BRD 9 "Low inventory" -- same condition as inventory.views.StockViewSet.low_stock (CPMAS-29)."""
    if not _pref_enabled(NotificationType.LOW_INVENTORY):
        return []
    created = []
    owners = list(_recipients(Role.OWNER))
    low_stocks = Stock.objects.filter(quantity__lt=F('material__minimum_stock_level')).select_related('material', 'warehouse')
    for stock in low_stocks:
        for user in owners:
            notification = _notify(
                user, NotificationType.LOW_INVENTORY,
                f"Low stock: {stock.material.name}",
                f"{stock.material.name} at {stock.warehouse.name} is at {stock.quantity}, "
                f"below the minimum of {stock.material.minimum_stock_level}.",
                entity_type='stock', entity_id=stock.id,
            )
            if notification:
                created.append(notification)
    return created


def po_awaiting_approval_alerts():
    """BRD 9 "PO/Change order awaiting approval" -- the PO half; Change Orders aren't built yet in this codebase."""
    if not _pref_enabled(NotificationType.PO_AWAITING_APPROVAL):
        return []
    created = []
    owners = list(_recipients(Role.OWNER))
    submitted = PurchaseOrder.objects.filter(status=PurchaseOrder.Status.SUBMITTED)
    for po in submitted:
        for user in owners:
            notification = _notify(
                user, NotificationType.PO_AWAITING_APPROVAL,
                f"PO {po.po_number} awaiting approval",
                f"Purchase order {po.po_number} was submitted on {po.order_date} and is waiting for approval.",
                entity_type='purchase_order', entity_id=po.id,
            )
            if notification:
                created.append(notification)
    return created


def budget_overrun_alerts():
    """BRD 9 "Budget overruns" -- reuses CPMAS-47's get_budget_summary; overrun = actual > budgeted, project-wide."""
    if not _pref_enabled(NotificationType.BUDGET_OVERRUN):
        return []
    created = []
    owners = list(_recipients(Role.OWNER))
    for project in Project.objects.filter(status=Project.STATUS_ACTIVE):
        budget = get_active_budget(project.id)
        if not budget:
            continue
        totals = get_budget_summary(budget)['totals']
        if totals['variance'] <= 0:
            continue
        for user in owners:
            notification = _notify(
                user, NotificationType.BUDGET_OVERRUN,
                f"Budget overrun on {project.name}",
                f"{project.name} has spent {totals['actual']} against a budget of {totals['budgeted']} "
                f"({totals['variance']} over).",
                entity_type='project', entity_id=project.id,
            )
            if notification:
                created.append(notification)
    return created


def deadline_approaching_alerts(today=None, window_days=DEADLINE_WINDOW_DAYS):
    """BRD 9 "Deadline approaches" -- an active project's expected completion date is coming up."""
    if not _pref_enabled(NotificationType.DEADLINE_APPROACHING):
        return []
    today = today or timezone.now().date()
    window_days = _pref_window(NotificationType.DEADLINE_APPROACHING, window_days)
    horizon = today + timedelta(days=window_days)
    created = []
    owners = list(_recipients(Role.OWNER))
    projects = Project.objects.filter(
        status=Project.STATUS_ACTIVE, expected_completion_date__gte=today, expected_completion_date__lte=horizon,
    )
    for project in projects:
        for user in owners:
            notification = _notify(
                user, NotificationType.DEADLINE_APPROACHING,
                f"{project.name} deadline approaching",
                f"{project.name} is expected to complete on {project.expected_completion_date}.",
                entity_type='project', entity_id=project.id,
            )
            if notification:
                created.append(notification)
    return created


def generate_all_notifications():
    """Run every BRD 9 alert generator once; returns the flat list of newly-created Notifications."""
    created = []
    for generator in (
        overdue_invoice_alerts, payment_due_alerts, low_inventory_alerts,
        po_awaiting_approval_alerts, budget_overrun_alerts, deadline_approaching_alerts,
    ):
        created.extend(generator())
    return created
