from decimal import Decimal

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from clients.models import Client
from clients.testing import WithClientsTableMixin

from users.testing import WithUsersTableMixin

from .models import Budget, BudgetItem, ChangeOrder, Phase, Project, ProjectEmployee, normalize_category_name
from .testing import WithProjectsTableMixin


class ProjectModelTests(TestCase):
    """
    Model/serializer-level tests that don't require auth to be wired up
    yet (the users/auth app is still in progress). Once login exists,
    add ProjectAPITests using APIClient + force_authenticate.
    """

    def test_str_representation(self):
        project = Project(code="HVR-2024-018", name="Harbor View Residences")
        self.assertEqual(str(project), "HVR-2024-018 — Harbor View Residences")

    def test_default_status_is_planning(self):
        project = Project(
            code="TST-001",
            name="Test Project",
            project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-09-01",
            contract_value=1000000,
        )
        self.assertEqual(project.status, Project.STATUS_PLANNING)

    def test_allowed_transitions_from_planning(self):
        allowed = Project.ALLOWED_TRANSITIONS[Project.STATUS_PLANNING]
        self.assertIn(Project.STATUS_ACTIVE, allowed)
        self.assertIn(Project.STATUS_CANCELLED, allowed)
        self.assertNotIn(Project.STATUS_COMPLETED, allowed)

    def test_completed_is_a_final_status(self):
        self.assertEqual(Project.ALLOWED_TRANSITIONS[Project.STATUS_COMPLETED], set())


class ProjectSerializerStatusTransitionTests(TestCase):
    def test_rejects_invalid_transition(self):
        from .serializers import ProjectSerializer

        instance = Project(status=Project.STATUS_COMPLETED)
        serializer = ProjectSerializer(instance=instance, data={}, partial=True)
        serializer.instance = instance
        with self.assertRaises(Exception):
            serializer.run_validation({"status": Project.STATUS_ACTIVE})

    def test_allows_same_status(self):
        from .serializers import ProjectSerializer

        instance = Project(status=Project.STATUS_ACTIVE)
        serializer = ProjectSerializer()
        serializer.instance = instance
        result = serializer.validate_status(Project.STATUS_ACTIVE)
        self.assertEqual(result, Project.STATUS_ACTIVE)


class PhaseModelTests(TestCase):
    """Project Planning (Phases) — same managed=False testing constraints
    as ProjectModelTests above: model/serializer logic only, no DB hits."""

    def test_str_representation(self):
        phase = Phase(sequence_number=1, name="Foundation")
        self.assertIn("Foundation", str(phase))

    def test_default_status_is_not_started(self):
        phase = Phase(name="Foundation", sequence_number=1)
        self.assertEqual(phase.status, Phase.STATUS_NOT_STARTED)

    def test_allowed_transitions_from_not_started(self):
        allowed = Phase.ALLOWED_TRANSITIONS[Phase.STATUS_NOT_STARTED]
        self.assertEqual(allowed, {Phase.STATUS_IN_PROGRESS})

    def test_completed_is_final(self):
        self.assertEqual(Phase.ALLOWED_TRANSITIONS[Phase.STATUS_COMPLETED], set())


class PhaseSerializerTests(TestCase):
    def test_rejects_invalid_status_transition(self):
        from .serializers import PhaseSerializer

        instance = Phase(status=Phase.STATUS_COMPLETED)
        serializer = PhaseSerializer()
        serializer.instance = instance
        with self.assertRaises(Exception):
            serializer.validate_status(Phase.STATUS_IN_PROGRESS)

    def test_allows_same_status(self):
        from .serializers import PhaseSerializer

        instance = Phase(status=Phase.STATUS_IN_PROGRESS)
        serializer = PhaseSerializer()
        serializer.instance = instance
        self.assertEqual(
            serializer.validate_status(Phase.STATUS_IN_PROGRESS), Phase.STATUS_IN_PROGRESS
        )

    def test_end_date_before_start_date_rejected(self):
        from .serializers import PhaseSerializer

        serializer = PhaseSerializer()
        serializer.instance = None
        with self.assertRaises(Exception):
            serializer.validate({"start_date": "2026-09-10", "end_date": "2026-09-01"})

    def test_completing_a_phase_auto_sets_full_progress(self):
        from decimal import Decimal

        from .serializers import PhaseSerializer

        instance = Phase(status=Phase.STATUS_IN_PROGRESS, progress_percentage=Decimal("60.00"))
        serializer = PhaseSerializer()
        serializer.instance = instance
        result = serializer.validate({"status": Phase.STATUS_COMPLETED})
        self.assertEqual(result["progress_percentage"], Decimal("100.00"))

    def test_explicit_progress_not_overridden_when_completing(self):
        from decimal import Decimal

        from .serializers import PhaseSerializer

        instance = Phase(status=Phase.STATUS_IN_PROGRESS, progress_percentage=Decimal("60.00"))
        serializer = PhaseSerializer()
        serializer.instance = instance
        result = serializer.validate(
            {"status": Phase.STATUS_COMPLETED, "progress_percentage": Decimal("95.00")}
        )
        self.assertEqual(result["progress_percentage"], Decimal("95.00"))


class ProjectFilteringAPITests(WithProjectsTableMixin, WithClientsTableMixin, TestCase):
    """CPMAS-23: ?client=/?date_from=/?date_to= filtering on ProjectViewSet."""

    def setUp(self):
        self.client_obj = Client.objects.create(name="Jane Homeowner")
        self.other_client = Client.objects.create(name="Someone Else")
        django_user = DjangoUser.objects.create_user(username="apitester_projects", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=django_user)

    def make_project(self, **kwargs):
        defaults = dict(
            name="Tower A", code="TWR-FILTER-1", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-06-01", contract_value=Decimal("100000.00"), buyer=self.client_obj,
        )
        defaults.update(kwargs)
        return Project.objects.create(**defaults)

    def test_filter_by_client(self):
        matching = self.make_project(code="TWR-FILTER-2")
        self.make_project(code="TWR-FILTER-3", buyer=self.other_client)

        response = self.client.get(f"/api/projects/projects/?client={self.client_obj.id}")
        codes = [p["code"] for p in response.json()["results"]]
        self.assertEqual(codes, [matching.code])

    def test_filter_by_start_date_range(self):
        in_range = self.make_project(code="TWR-FILTER-4", start_date="2026-06-15")
        self.make_project(code="TWR-FILTER-5", start_date="2026-01-01")

        response = self.client.get("/api/projects/projects/?date_from=2026-06-01&date_to=2026-06-30")
        codes = [p["code"] for p in response.json()["results"]]
        self.assertEqual(codes, [in_range.code])


class BudgetModelTests(TestCase):
    """
    Model-level tests only — get_budget_summary()/get_active_budget() run
    real aggregate queries against managed=False tables and can't be unit
    tested against SQLite for the same reason noted in clients/SETUP.md.
    """

    def test_allowed_transitions_from_draft(self):
        self.assertEqual(Budget.ALLOWED_TRANSITIONS[Budget.STATUS_DRAFT], {Budget.STATUS_APPROVED})

    def test_closed_is_final(self):
        self.assertEqual(Budget.ALLOWED_TRANSITIONS[Budget.STATUS_CLOSED], set())

    def test_category_choices_match_task_spec(self):
        expected = {"MATERIALS", "LABOR", "CONTRACTORS", "EQUIPMENT", "OTHER"}
        actual = {value for value, _ in BudgetItem.CATEGORY_CHOICES}
        self.assertEqual(expected, actual)

    def test_normalize_category_name(self):
        self.assertEqual(normalize_category_name("Materials"), "MATERIALS")
        self.assertEqual(normalize_category_name("  labor "), "LABOR")
        self.assertEqual(normalize_category_name("Site Equipment"), "SITE_EQUIPMENT")


class BudgetSerializerTests(TestCase):
    def test_rejects_invalid_status_transition(self):
        from .serializers import BudgetSerializer

        instance = Budget(status=Budget.STATUS_CLOSED)
        serializer = BudgetSerializer()
        serializer.instance = instance
        with self.assertRaises(Exception):
            serializer.validate_status(Budget.STATUS_APPROVED)

    def test_allows_same_status(self):
        from .serializers import BudgetSerializer

        instance = Budget(status=Budget.STATUS_APPROVED)
        serializer = BudgetSerializer()
        serializer.instance = instance
        self.assertEqual(serializer.validate_status(Budget.STATUS_APPROVED), Budget.STATUS_APPROVED)


class ChangeOrderModelTests(TestCase):
    """
    Model-level tests only — apply_change_order_to_contract()/
    reverse_change_order_from_contract() do real DB writes and can't be
    unit tested against SQLite here (see clients/SETUP.md and the
    outstanding managed=False/test-runner notes elsewhere in this repo).
    """

    def test_str_representation(self):
        co = ChangeOrder(number="CO-01")
        self.assertIn("CO-01", str(co))

    def test_default_status_is_pending(self):
        co = ChangeOrder(number="CO-01")
        self.assertEqual(co.status, ChangeOrder.STATUS_PENDING)

    def test_allowed_transitions_from_pending(self):
        allowed = ChangeOrder.ALLOWED_TRANSITIONS[ChangeOrder.STATUS_PENDING]
        self.assertEqual(
            allowed, {ChangeOrder.STATUS_APPROVED, ChangeOrder.STATUS_REJECTED, ChangeOrder.STATUS_CANCELLED}
        )

    def test_approved_can_only_go_to_cancelled(self):
        self.assertEqual(
            ChangeOrder.ALLOWED_TRANSITIONS[ChangeOrder.STATUS_APPROVED], {ChangeOrder.STATUS_CANCELLED}
        )

    def test_rejected_and_cancelled_are_final(self):
        self.assertEqual(ChangeOrder.ALLOWED_TRANSITIONS[ChangeOrder.STATUS_REJECTED], set())
        self.assertEqual(ChangeOrder.ALLOWED_TRANSITIONS[ChangeOrder.STATUS_CANCELLED], set())


class ChangeOrderSerializerTests(TestCase):
    def test_status_and_approved_by_are_read_only(self):
        from .serializers import ChangeOrderSerializer

        read_only = ChangeOrderSerializer().Meta.read_only_fields
        self.assertIn("status", read_only)
        self.assertIn("approved_by", read_only)


class PortfolioBudgetSummaryAPITests(WithProjectsTableMixin, WithClientsTableMixin, TestCase):
    """GET /api/projects/budgets/portfolio-summary/ aggregation across projects."""

    def setUp(self):
        super().setUp()
        self.client_obj = Client.objects.create(name="Portfolio Corp")
        self.api = APIClient()
        self.api.force_authenticate(
            user=DjangoUser.objects.create_user(username="portfolio_tester", password="pass12345")
        )

    def test_empty_when_no_projects(self):
        response = self.api.get("/api/projects/budgets/portfolio-summary/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["totals"]["projects"], 0)

    def test_aggregates_across_projects_with_budgets(self):
        proj_a = Project.objects.create(
            code="PORT-A", name="Project Alpha", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("500000"), buyer=self.client_obj,
        )
        proj_b = Project.objects.create(
            code="PORT-B", name="Project Beta", project_type=Project.TYPE_MULTI_UNIT,
            start_date="2026-01-01", contract_value=Decimal("300000"), buyer=self.client_obj,
        )

        bud_a = Budget.objects.create(project=proj_a, name="Budget A", total_budget=Decimal("100000"), status=Budget.STATUS_APPROVED)
        BudgetItem.objects.create(budget=bud_a, category="MATERIALS", budgeted_amount=Decimal("50000"))
        BudgetItem.objects.create(budget=bud_a, category="LABOR", budgeted_amount=Decimal("30000"))

        bud_b = Budget.objects.create(project=proj_b, name="Budget B", total_budget=Decimal("80000"), status=Budget.STATUS_DRAFT)
        BudgetItem.objects.create(budget=bud_b, category="MATERIALS", budgeted_amount=Decimal("40000"))

        response = self.api.get("/api/projects/budgets/portfolio-summary/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["totals"]["projects"], 2)
        self.assertIn("budgeted", data["totals"])
        self.assertIn("actual", data["totals"])

    def test_project_filter_restricts_results(self):
        proj = Project.objects.create(
            code="PORT-C", name="Project Gamma", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("200000"), buyer=self.client_obj,
        )
        Budget.objects.create(project=proj, name="Budget C", total_budget=Decimal("60000"), status=Budget.STATUS_APPROVED)

        response = self.api.get(f"/api/projects/budgets/portfolio-summary/?project={proj.id}")
        data = response.json()
        self.assertEqual(data["totals"]["projects"], 1)


class DeleteReturnsMethodNotAllowedTests(
    WithUsersTableMixin, WithProjectsTableMixin, WithClientsTableMixin, TestCase
):
    """
    Projects and change orders carry financial/contract value, so hard DELETE
    is intentionally not exposed. These endpoints used to raise
    NotImplementedError inside perform_destroy (HTTP 500); they must now
    respond 405 Method Not Allowed instead, and leave the row untouched.
    """

    def setUp(self):
        super().setUp()
        self.client_obj = Client.objects.create(name="Delete Test Co")
        self.api = APIClient()
        self.api.force_authenticate(
            user=DjangoUser.objects.create_user(username="delete_tester", password="pass12345")
        )
        self.project = Project.objects.create(
            code="DEL-001", name="Delete Me", project_type=Project.TYPE_WHOLE_BUILDING,
            start_date="2026-01-01", contract_value=Decimal("100000"), buyer=self.client_obj,
        )
        self.change_order = ChangeOrder.objects.create(
            project=self.project,
            number="CO-001",
            description="Delete me",
            amount=Decimal("5000"),
            date="2026-01-15",
        )

    def test_delete_project_returns_405_not_500(self):
        response = self.api.delete(f"/api/projects/projects/{self.project.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Project.objects.filter(pk=self.project.id).exists())

    def test_delete_change_order_returns_405_not_500(self):
        response = self.api.delete(f"/api/projects/change-orders/{self.change_order.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(ChangeOrder.objects.filter(pk=self.change_order.id).exists())
