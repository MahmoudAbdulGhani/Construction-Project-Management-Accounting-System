"""
Test-only utility for the ``audit`` app.

``AuditLog.Meta.managed = False`` (see models.py) means Django's normal
migration/test-database setup never creates ``audit_logs`` -- it assumes the
table already exists (created by the SQL schema), which is true against the
live Supabase DB but not against a fresh, empty test database. Any test that
wants to *assert* audit entries exists must create the table first.

``WithAuditLogsTableMixin`` does this before Django's ``TestCase`` wraps the
class in its own transaction (so the CREATE TABLE is a plain, separately
committed statement), and drops it when the wrapping closes -- mirroring
``users.testing.WithUsersTableMixin``.

Note: suites that do NOT opt in keep working because the recording service
skips writes silently when the table is missing; see ``audit.services``.
"""
from django.db import connection

from .models import AuditLog
from .services import reset_audit_table_cache


class WithAuditLogsTableMixin:
    """
    Mix into any Django TestCase subclass that asserts audit entries.

    Usage: ``class MyTests(WithAuditLogsTableMixin, TestCase): ...`` --
    WithAuditLogsTableMixin must come first in the MRO so its setUpClass/
    tearDownClass wrap (not get wrapped by) TestCase's own.
    """

    @classmethod
    def setUpClass(cls):
        reset_audit_table_cache()
        with connection.schema_editor() as editor:
            editor.create_model(AuditLog)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            editor.delete_model(AuditLog)
        reset_audit_table_cache()