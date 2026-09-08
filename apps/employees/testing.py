"""
Test-only utility for the ``employees`` app.

``Employee`` is ``managed = False`` (it reflects an existing Supabase
table owned elsewhere -- see models.py), so Django's normal test-database
setup never creates ``employees``. Any test that needs to persist real
rows must create that table for the duration of the test class -- the
same pattern as ``users.testing.WithUsersTableMixin`` and
``projects.testing.WithProjectsTableMixin``.

``EmployeeProjectAssignment`` maps onto ``project_employees``, which
(since CPMAS-25's migration cleanup) ``projects.ProjectEmployee`` owns as
a real managed table -- its migrations already create it once, up front,
before any test class's setUpClass runs. So this mixin checks for
existence before creating/dropping either of its tables, same as
``WithProjectsTableMixin``.

Tests that also create Project rows should mix ``WithProjectsTableMixin``
(and ``WithClientsTableMixin``, since Project references ``clients`` via
``buyer_id``) in BEFORE this mixin so the ``projects`` / ``clients`` tables
(referenced by the assignment) exist first.
"""
from django.db import connection

from .models import Employee, EmployeeProjectAssignment


class WithEmployeesTableMixin:
    """
    Mix into any Django TestCase subclass that needs to persist real
    Employee / EmployeeProjectAssignment rows.

    Usage: ``class MyTests(WithEmployeesTableMixin, TestCase): ...`` --
    must come first in the MRO so its setUpClass/tearDownClass wrap (not
    get wrapped by) TestCase's own.
    """

    _employees_created_tables = ()

    @classmethod
    def setUpClass(cls):
        existing = connection.introspection.table_names()
        to_create = [
            model for model in (Employee, EmployeeProjectAssignment)
            if model._meta.db_table not in existing
        ]
        with connection.schema_editor() as editor:
            for model in to_create:
                editor.create_model(model)
        cls._employees_created_tables = to_create
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for model in reversed(cls._employees_created_tables):
                editor.delete_model(model)
