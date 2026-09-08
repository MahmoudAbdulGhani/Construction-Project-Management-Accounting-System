"""
Test-only utility for the ``contractors`` app.

``Contractor`` and ``ContractorProjectAssignment`` are ``managed = False``
(they reflect existing Supabase tables owned elsewhere -- see models.py),
so Django's normal test-database setup never creates ``contractors`` or
``project_contractors``. Any test that needs to persist real rows must
create those tables for the duration of the test class -- the same
pattern as ``users.testing.WithUsersTableMixin`` and
``projects.testing.WithProjectsTableMixin``.

``ContractorDocument`` maps onto the shared ``documents`` table, which
(since CPMAS-25) the ``documents`` app owns as a real managed table --
its own migrations already create it once, up front, before any test
class's setUpClass runs. So this mixin checks for existence before
creating/dropping any of its three tables, same as
``WithProjectsTableMixin`` -- harmless for the still-genuinely-unmanaged
``contractors``/``project_contractors`` tables (each test class gets and
loses its own), and correct for the now-shared ``documents`` table
(leave it for whoever/whatever created it first).

Tests that also create Project rows should mix ``WithProjectsTableMixin`` in
BEFORE this mixin so the ``projects`` table (referenced by
``ContractorProjectAssignment.project``) exists first.
"""
from django.db import connection

from .models import Contractor, ContractorDocument, ContractorProjectAssignment


class WithContractorsTableMixin:
    """
    Mix into any Django TestCase subclass that needs to persist real
    Contractor / ContractorProjectAssignment / ContractorDocument rows.

    Usage: ``class MyTests(WithContractorsTableMixin, TestCase): ...`` --
    must come first in the MRO so its setUpClass/tearDownClass wrap (not
    get wrapped by) TestCase's own.
    """

    _contractors_created_tables = ()

    @classmethod
    def setUpClass(cls):
        existing = connection.introspection.table_names()
        to_create = [
            model for model in (Contractor, ContractorProjectAssignment, ContractorDocument)
            if model._meta.db_table not in existing
        ]
        with connection.schema_editor() as editor:
            for model in to_create:
                editor.create_model(model)
        cls._contractors_created_tables = to_create
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for model in reversed(cls._contractors_created_tables):
                editor.delete_model(model)