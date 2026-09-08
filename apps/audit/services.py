"""
Audit recording service -- the only code path that writes to ``audit_logs``.

Design
------
* Signal handlers on registered models (``taxes.TaxRate``, ``users.User``)
  capture before/after JSON state and call the append-only ``record_audit()``.
* The acting user + IP are read from the current HTTP request, which
  ``AuditContextMiddleware`` stashes in a ``contextvars.ContextVar`` so the
  signal handlers (which hold no HTTP reference) can reach it. Outside a
  request (management commands, plain unit tests) the actor is ``None``,
  i.e. the entry is attributed to "system".
* Old values for UPDATEs come from a pre-save snapshot of the DB row taken
  by ``pre_save``; ``post_save`` then writes CREATE/UPDATE. Only genuine
  field changes are logged (auto bookkeeping like ``updated_at`` /
  ``last_login`` is excluded from snapshots), so incidental touches never
  spam the trail.
* Secrets (``users.User.password_hash``) are excluded from snapshots.
* If the ``audit_logs`` table is missing -- it is ``managed = False`` and
  created by the SQL schema, so a fresh test database won't have it unless a
  suite opts in via ``apps.audit.testing`` -- writes are skipped silently
  rather than taking the application (or unrelated tests) down.
"""
import json
import threading
from contextvars import ContextVar

from django.core.serializers.json import DjangoJSONEncoder
from django.db import OperationalError, ProgrammingError
from django.db.models import signals

from .models import AuditAction

# Fields never stored in audit snapshots: secrets and auto bookkeeping.
_EXCLUDED_FIELDS = {'password_hash', 'last_login', 'updated_at'}

_current_request = ContextVar('audit_current_request', default=None)
_local = threading.local()

# Cached existence of the audit_logs table. Cached because checking every
# save is wasteful in production (where the table always exists); invalidated
# by ``reset_audit_table_cache()`` when a test mixin creates/drops it.
_AUDIT_TABLE_PRESENT = None

_UNSET = object()


def reset_audit_table_cache():
    """Forget the cached audit_logs existence (used by test utilities)."""
    global _AUDIT_TABLE_PRESENT
    _AUDIT_TABLE_PRESENT = None


def _audit_table_available() -> bool:
    """Whether audit_logs exists. Never executes the INSERT-lite DDL check
    inside a transaction that could poison an atomic block -- just reads."""
    global _AUDIT_TABLE_PRESENT
    if _AUDIT_TABLE_PRESENT:
        return True
    from django.db import connection

    present = 'audit_logs' in connection.introspection.table_names()
    if present:
        _AUDIT_TABLE_PRESENT = True
    return present


def set_current_request(request):
    """Stash the active request; returns a token usable with reset."""
    return _current_request.set(request)


def reset_current_request(token):
    _current_request.reset(token)


def current_request():
    return _current_request.get()


def record_audit(*, action, entity_type, entity_id, old_values=None,
                 new_values=None, user=_UNSET, ip_address=_UNSET):
    """
    Append one audit entry. The only mutation primitive in the audit app.

    ``user`` / ``ip_address`` fall back to the actor captured from the active
    request (see ``AuditContextMiddleware``) when not given explicitly; pass
    ``user=None`` to force a system-attributed entry.
    """
    # Guard BEFORE anything else: on SQLite a failed INSERT inside an active
    # transaction poisons the whole transaction even when the exception is
    # caught, and resolving the actor would query tables that may not exist in
    # a test DB. Skips the whole write cleanly when this managed=False table is
    # absent (e.g. a fresh test database or a suite that didn't opt in).
    if not _audit_table_available():
        return

    if user is _UNSET or ip_address is _UNSET:
        request_user, request_ip = _capture_actor()
        if user is _UNSET:
            user = request_user
        if ip_address is _UNSET:
            ip_address = request_ip

    from .models import AuditLog

    try:
        AuditLog.objects.create(
            user=user,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
        )
    except (OperationalError, ProgrammingError):
        # Should not happen after the availability check; keep best-effort.
        pass


def _capture_actor():
    """Resolve the acting user + IP from the request stashed by the middleware."""
    request = _current_request.get()
    if request is None:
        return None, None

    user = getattr(request, 'user', None)
    if user is None or getattr(user, 'is_anonymous', True):
        user = None
    else:
        from users.models import User

        if not isinstance(user, User):
            try:
                user = User.objects.filter(pk=getattr(user, 'pk', None)).first()
            except (OperationalError, ProgrammingError):
                # The request carried a user of a different User model (e.g.
                # Django's auth.User) or the app `users` table is absent in a
                # test DB -- fall back to a system-attributed entry rather than
                # breaking the save that triggered this audit write.
                user = None

    # Bearer-token API clients don't reach AppUserSessionMiddleware (no cookie),
    # so resolve the actor from the Authorization header when nothing else did.
    if user is None:
        raw = (request.META.get('HTTP_AUTHORIZATION') or '').replace('Bearer', '', 1).strip()
        if raw:
            from users.authentication import _resolve_user_from_jwt_token

            user = _resolve_user_from_jwt_token(raw)

    ip_address = None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '') or ''
    source = (forwarded.split(',')[0].strip() if forwarded
              else request.META.get('REMOTE_ADDR', ''))
    if source:
        ip_address = source
    return user, ip_address


def _field_values(instance):
    """JSON-safe snapshot of a model row's concrete fields."""
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in _EXCLUDED_FIELDS:
            continue
        try:
            data[field.name] = getattr(instance, field.attname)
        except Exception:
            continue
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def _changed(old_values, new_values):
    if not old_values:
        return bool(new_values)
    return any(new_values.get(name) != value for name, value in old_values.items())


def _snapshots(name):
    snapshots = getattr(_local, name, None)
    if snapshots is None:
        snapshots = {}
        setattr(_local, name, snapshots)
    return snapshots


def _entity_type(model):
    from .registry import entity_type_for

    return entity_type_for(model)


def _action_override(instance, default):
    """Consume a one-shot ``_audit_action`` hint set by a view (e.g. activate)."""
    action = getattr(instance, '_audit_action', None)
    if action is not None:
        try:
            del instance._audit_action
        except AttributeError:
            pass
        return action
    return default


def _pre_save(sender, instance, **kwargs):
    # Fresh INSERTs have no pk yet; post_save handles the CREATE entry.
    if not instance.pk:
        return
    try:
        prior = sender.objects.filter(pk=instance.pk).first()
    except OperationalError:
        prior = None
    _snapshots('pre_save')[id(instance)] = _field_values(prior) if prior else None


def _post_save(sender, instance, created, **kwargs):
    new_values = _field_values(instance)
    if created:
        if not new_values:
            return
        record_audit(
            action=AuditAction.CREATE,
            entity_type=_entity_type(sender),
            entity_id=instance.pk,
            new_values=new_values,
        )
        return

    snapshots = _snapshots('pre_save')
    old_values = snapshots.pop(id(instance), None)
    if not _changed(old_values, new_values):
        return
    record_audit(
        action=_action_override(instance, AuditAction.UPDATE),
        entity_type=_entity_type(sender),
        entity_id=instance.pk,
        old_values=old_values,
        new_values=new_values,
    )


def _pre_delete(sender, instance, **kwargs):
    try:
        prior = sender.objects.filter(pk=instance.pk).first()
    except OperationalError:
        prior = None
    _snapshots('pre_delete')[id(instance)] = _field_values(prior) if prior else None


def _post_delete(sender, instance, **kwargs):
    snapshots = _snapshots('pre_delete')
    old_values = snapshots.pop(id(instance), None)
    record_audit(
        action=AuditAction.DELETE,
        entity_type=_entity_type(sender),
        entity_id=instance.pk,
        old_values=old_values,
    )


def connect_audit_signals(model):
    """Attach the recording handlers to one registered model."""
    signals.pre_save.connect(_pre_save, sender=model, weak=False)
    signals.post_save.connect(_post_save, sender=model, weak=False)
    signals.pre_delete.connect(_pre_delete, sender=model, weak=False)
    signals.post_delete.connect(_post_delete, sender=model, weak=False)