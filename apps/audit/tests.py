"""
Tests for the ``audit`` app -- immutable Audit Trail.

Covers the recording service (CREATE/UPDATE/DELETE actions via signals,
before/after JSON snapshots, secrets never logged, system actor outside a
request, no-op saves producing no noise) and the read-only Owner-only API
(list/detail, search, filters, ordering) plus the absence of write endpoints.
"""
import datetime
import uuid
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import models as djmodels
from django.db.models import signals
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from django.utils import timezone

from audit.registry import entity_type_for, label_for
from users.testing import WithUsersTableMixin

from .models import AuditAction, AuditLog
from .services import reset_current_request, set_current_request
from .testing import WithAuditLogsTableMixin

from company.testing import WithCompanyDetailsTableMixin
from clients.testing import WithClientsTableMixin
from projects.testing import WithProjectsTableMixin
from contractors.testing import WithContractorsTableMixin
from employees.testing import WithEmployeesTableMixin


class _Request:
    """Minimal stand-in for the request object stashed by the middleware."""

    def __init__(self, user, remote_addr='127.0.0.1'):
        self.user = user
        self.META = {'REMOTE_ADDR': remote_addr}


def _make_user(username, role='OWNER'):
    from users.models import User as AppUser

    user = AppUser.objects.create(
        username=username, email=f"{username}@example.com",
        password_hash="x", first_name=username, last_name="T",
        role=role,
    )
    user.set_password("pass-1234")
    user.save(update_fields=["password_hash"])
    return user


class AuditServiceTests(WithUsersTableMixin, WithAuditLogsTableMixin, TestCase):
    """Signal-driven recording: who/when/what, old+new values, no secrets."""

    def test_create_records_entry_with_actor(self):
        owner = _make_user('owner')
        token = set_current_request(_Request(owner))
        try:
            created = _make_user('created_user', 'ACCOUNTANT')
        finally:
            reset_current_request(token)

        entry = AuditLog.objects.filter(
            action=AuditAction.CREATE, entity_id=created.id).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.entity_type, 'user')
        self.assertEqual(entry.user, owner)
        self.assertEqual(entry.ip_address, '127.0.0.1')
        self.assertIsNone(entry.old_values)
        self.assertEqual(entry.new_values['username'], 'created_user')
        self.assertNotIn('password_hash', entry.new_values)

    def test_update_records_old_and_new_values(self):
        actor = _make_user('actor')
        target = _make_user('target')

        token = set_current_request(_Request(actor))
        try:
            target.first_name = 'Renamed'
            target.save(update_fields=['first_name'])
        finally:
            reset_current_request(token)

        entry = AuditLog.objects.filter(
            action=AuditAction.UPDATE, entity_id=target.id).latest('created_at')
        self.assertEqual(entry.user, actor)
        self.assertEqual(entry.old_values['first_name'], 'target')
        self.assertEqual(entry.new_values['first_name'], 'Renamed')
        self.assertNotIn('password_hash', entry.old_values)
        self.assertNotIn('password_hash', entry.new_values)

    def test_no_op_save_produces_no_entry(self):
        user = _make_user('stable')
        before = AuditLog.objects.count()
        user.save()
        user.save(update_fields=['last_name'])
        self.assertEqual(AuditLog.objects.count(), before)

    def test_delete_records_entry(self):
        from taxes.models import TaxRate

        actor = _make_user('actor')
        doomed = TaxRate.objects.create(
            name='VAT', rate=Decimal('15'), tax_type='VAT',
            effective_date='2026-01-01', is_active=True,
        )

        token = set_current_request(_Request(actor))
        try:
            doomed_id = doomed.id  # Django clears pk after delete()
            doomed.delete()
        finally:
            reset_current_request(token)

        entry = AuditLog.objects.filter(
            action=AuditAction.DELETE, entity_id=doomed_id).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.entity_type, 'tax_rate')
        self.assertEqual(entry.user, actor)
        self.assertEqual(entry.old_values['name'], 'VAT')
        self.assertIsNone(entry.new_values)

    def test_tax_rate_create_and_status_actions(self):
        from taxes.models import TaxRate

        actor = _make_user('actor')
        token = set_current_request(_Request(actor))
        try:
            tax = TaxRate.objects.create(
                name='VAT', rate=Decimal('15'), tax_type='VAT',
                effective_date='2026-01-01', is_active=True,
            )
            tax._audit_action = AuditAction.DEACTIVATE
            tax.is_active = False
            tax.save(update_fields=['is_active'])
        finally:
            reset_current_request(token)

        created = AuditLog.objects.filter(
            action=AuditAction.CREATE, entity_id=tax.id).first()
        self.assertEqual(created.entity_type, 'tax_rate')
        self.assertEqual(created.new_values['name'], 'VAT')
        self.assertEqual(created.user, actor)

        deactivated = AuditLog.objects.filter(
            action=AuditAction.DEACTIVATE, entity_id=tax.id).first()
        self.assertIsNotNone(deactivated)
        self.assertTrue(deactivated.old_values['is_active'])
        self.assertFalse(deactivated.new_values['is_active'])

    def test_system_actor_outside_request(self):
        user = _make_user('system_actor')
        entry = AuditLog.objects.filter(
            action=AuditAction.CREATE, entity_id=user.id).first()
        self.assertIsNone(entry.user)
        self.assertIsNone(entry.ip_address)

    def test_registry_mappings(self):
        from taxes.models import TaxRate
        from users.models import User

        self.assertEqual(entity_type_for(User), 'user')
        self.assertEqual(label_for('user'), 'User')
        self.assertEqual(entity_type_for(TaxRate), 'tax_rate')
        self.assertEqual(label_for('tax_rate'), 'Tax rate')

        from projects.models import Project
        from purchasing.models import PurchaseOrder
        from invoicing.models import ClientInvoice
        self.assertEqual(entity_type_for(Project), 'project')
        self.assertEqual(entity_type_for(PurchaseOrder), 'purchase_order')
        self.assertEqual(entity_type_for(ClientInvoice), 'client_invoice')
        self.assertEqual(label_for('project'), 'Project')
        self.assertEqual(label_for('purchase_order'), 'Purchase order')


class AuditLogApiTests(WithUsersTableMixin, WithAuditLogsTableMixin, TestCase):
    """Read-only Owner-only audit API at /api/audit/audit-logs/."""

    def setUp(self):
        self.client = APIClient()
        self.owner = _make_user('owner')
        self.accountant = _make_user('accountant', 'ACCOUNTANT')

    def _login(self, user):
        """Bearer-token login (the proven DRF test pattern)."""
        resp = self.client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "pass-1234"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_owner_lists_entries_with_actor_from_cookie_auth(self):
        self._login(self.owner)
        created = self.client.post(
            "/api/taxes/tax-rates/",
            {"name": "VAT", "rate": "15.0000", "tax_type": "VAT",
             "effective_date": "2026-01-01"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        listing = self.client.get("/api/audit/audit-logs/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        results = listing.data.get("results") or listing.data
        entry = next(
            (r for r in results if r["entity_type"] == "tax_rate"
             and r["entity_id"] == created.data["id"]),
            None,
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["action"], "CREATE")
        self.assertEqual(entry["user"], self.owner.id)
        self.assertEqual(entry["user_name"], "owner")
        self.assertEqual(entry["new_values"]["name"], "VAT")
        self.assertIsNone(entry["old_values"])

    def test_owner_can_retrieve_detail(self):
        self._login(self.owner)
        user = _make_user('detail_target')
        entry = AuditLog.objects.filter(entity_id=user.id).first()
        response = self.client.get(f"/api/audit/audit-logs/{entry.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(entry.id))

    def test_accountant_cannot_read_audit_logs(self):
        self._login(self.accountant)
        response = self.client.get("/api/audit/audit-logs/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_cannot_read_audit_logs(self):
        response = self.client.get("/api/audit/audit-logs/")
        self.assertIn(response.status_code,
                      (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_entities_endpoint_lists_registered_types(self):
        self._login(self.owner)
        response = self.client.get("/api/audit/entities/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entities = response.data
        types = [e["entity_type"] for e in entities]
        self.assertEqual(len(types), 18)
        self.assertIn("user", types)
        self.assertIn("tax_rate", types)
        self.assertIn("project", types)
        self.assertIn("purchase_order", types)
        self.assertIn("employee", types)
        self.assertIn("expense", types)
        self.assertIn("account", types)
        self.assertIn("financial_transaction", types)
        labels = {e["entity_type"]: e["label"] for e in entities}
        self.assertEqual(labels["user"], "User")
        self.assertEqual(labels["project"], "Project")
        cats = {e["entity_type"]: e.get("category") for e in entities}
        self.assertTrue(cats["user"])
        self.assertTrue(cats["supplier_invoice"])
        # Sorted by (category, label) so the UI groups render contiguously.
        keyed = [(e["category"], e["label"]) for e in entities]
        self.assertEqual(keyed, sorted(keyed, key=lambda k: (k[0].lower(), k[1].lower())))

    def test_accountant_cannot_read_entities(self):
        self._login(self.accountant)
        response = self.client.get("/api/audit/entities/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_no_write_endpoints(self):
        self._login(self.owner)
        post = self.client.post("/api/audit/audit-logs/", {"action": "CREATE"},
                                format="json")
        put = self.client.put("/api/audit/audit-logs/%s/" % uuid.uuid4(),
                              {"action": "UPDATE"}, format="json")
        patch = self.client.patch("/api/audit/audit-logs/%s/" % uuid.uuid4(),
                                  {"action": "UPDATE"}, format="json")
        delete = self.client.delete("/api/audit/audit-logs/%s/" % uuid.uuid4())
        self.assertEqual(post.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(put.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(patch.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(delete.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_filters_search_and_ordering(self):
        self._login(self.owner)
        # Owner-attributed entry via the cookie-authenticated API.
        tax = self.client.post(
            "/api/taxes/tax-rates/",
            {"name": "VAT", "rate": "15.0000", "tax_type": "VAT",
             "effective_date": "2026-01-01"},
            format="json",
        )
        self.assertEqual(tax.status_code, status.HTTP_201_CREATED)

        alpha = _make_user('alpha_user', 'ACCOUNTANT')
        beta = _make_user('beta_user', 'ACCOUNTANT')
        token = set_current_request(_Request(alpha))
        try:
            beta.first_name = 'Renamed'
            beta.save(update_fields=['first_name'])
        finally:
            reset_current_request(token)
        # A delete-path entry (on TaxRate: deleting a User row itself would
        # pull ChangeOrder collectors onto the missing change_orders table in
        # this SQLite test DB, which is a pre-existing test-env landmine).
        from taxes.models import TaxRate
        deleted = TaxRate.objects.create(
            name='Old rate', rate=Decimal('7'), tax_type='VAT',
            effective_date='2025-01-01', is_active=True,
        )
        deleted.delete()

        by_entity = self.client.get("/api/audit/audit-logs/?entity_type=user")
        results = by_entity.data.get("results") or by_entity.data
        self.assertTrue(results)
        self.assertTrue(all(r["entity_type"] == "user" for r in results))

        by_user = self.client.get(f"/api/audit/audit-logs/?user={self.owner.id}")
        results = by_user.data.get("results") or by_user.data
        self.assertTrue(results, "expected owner-attributed entries")
        self.assertTrue(all(r["user"] == self.owner.id for r in results))

        search = self.client.get("/api/audit/audit-logs/?search=alpha")
        self.assertEqual(search.status_code, status.HTTP_200_OK)
        results = search.data.get("results") or search.data
        self.assertTrue(any(r["entity_id"] == str(beta.id) for r in results))

        ordered = self.client.get("/api/audit/audit-logs/?ordering=created_at")
        results = ordered.data.get("results") or ordered.data
        stamps = [r["created_at"] for r in results]
        self.assertEqual(stamps, sorted(stamps))


def _minimal_kwargs(model, seen):
    """Build kwargs that satisfy every required, non-defaulted concrete field."""
    kwargs = {}
    for field in model._meta.concrete_fields:
        if field.primary_key or not field.editable:
            continue
        # Fields that can stay empty (nullable or have a default) are left
        # alone so the model's own defaults apply.
        if field.null or field.has_default():
            continue
        if isinstance(field, (djmodels.ForeignKey, djmodels.OneToOneField)):
            target = field.related_model
            related = seen.get(target)
            if related is None:
                related = _create_minimal(target, seen)
                seen[target] = related
            kwargs[field.name] = related
        elif isinstance(field, djmodels.BooleanField):
            kwargs[field.name] = False
        elif isinstance(field, djmodels.IntegerField):
            kwargs[field.name] = 0
        elif isinstance(field, djmodels.DecimalField):
            kwargs[field.name] = Decimal("1")
        elif isinstance(field, djmodels.FloatField):
            kwargs[field.name] = 1.0
        elif isinstance(field, djmodels.DateField):
            kwargs[field.name] = datetime.date.today()
        elif isinstance(field, djmodels.DateTimeField):
            kwargs[field.name] = timezone.now()
        elif isinstance(field, djmodels.TimeField):
            kwargs[field.name] = datetime.time(9, 0)
        elif isinstance(field, djmodels.DurationField):
            kwargs[field.name] = datetime.timedelta(days=1)
        elif isinstance(field, djmodels.EmailField):
            kwargs[field.name] = "audit-" + uuid.uuid4().hex[:8] + "@example.com"
        elif isinstance(field, djmodels.UUIDField):
            kwargs[field.name] = uuid.uuid4()
        elif isinstance(field, (djmodels.FileField, djmodels.ImageField)):
            kwargs[field.name] = ContentFile(b"audit", name="audit.bin")
        elif isinstance(field, djmodels.JSONField):
            kwargs[field.name] = {}
        else:
            value = "audit-" + uuid.uuid4().hex[:20]
            if isinstance(field, djmodels.CharField) and field.max_length:
                value = value[: field.max_length]
            kwargs[field.name] = value
    return kwargs


def _create_minimal(model, seen):
    """Create one instance of ``model``, recursing into required FK targets."""
    existing = seen.get(model)
    if existing is not None:
        return existing
    instance = model.objects.create(**_minimal_kwargs(model, seen))
    seen[model] = instance
    return instance


class AuditAllRegisteredModelsTests(WithCompanyDetailsTableMixin,
                                    WithProjectsTableMixin,
                                    WithClientsTableMixin,
                                    WithContractorsTableMixin,
                                    WithEmployeesTableMixin,
                                    WithUsersTableMixin,
                                    WithAuditLogsTableMixin,
                                    TestCase):
    """Every registered entity actually writes CREATE audit entries."""

    def test_all_registered_models_record_create(self):
        from audit.registry import AUDITABLE_MODELS

        self.assertGreaterEqual(len(AUDITABLE_MODELS), 14)
        for model, info in AUDITABLE_MODELS.items():
            with self.subTest(model=model.__name__, entity=info["entity_type"]):
                obj = _create_minimal(model, {})
                entry = AuditLog.objects.filter(
                    action=AuditAction.CREATE,
                    entity_type=info["entity_type"],
                    entity_id=obj.pk,
                ).first()
                self.assertIsNotNone(
                    entry,
                    f"no CREATE audit entry for {model.__name__} "
                    f"(entity_type={info['entity_type']!r})",
                )

    def test_signals_connected_for_all_registered_models(self):
        from audit.registry import AUDITABLE_MODELS

        for model in AUDITABLE_MODELS:
            with self.subTest(model=model.__name__):
                self.assertTrue(signals.pre_save.has_listeners(sender=model))
                self.assertTrue(signals.post_save.has_listeners(sender=model))
                self.assertTrue(signals.pre_delete.has_listeners(sender=model))
                self.assertTrue(signals.post_delete.has_listeners(sender=model))
