from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from construction.filtering import filter_date_range
from contractors.serializers import ProjectContractorSerializer

from .models import (
    Budget,
    BudgetItem,
    ChangeOrder,
    Phase,
    Project,
    ProjectDocument,
    apply_change_order_to_contract,
    get_active_budget,
    get_budget_summary,
    reverse_change_order_from_contract,
)
from .serializers import (
    BudgetItemSerializer,
    BudgetSerializer,
    ChangeOrderSerializer,
    PhaseSerializer,
    ProjectDocumentSerializer,
    ProjectEmployeeSerializer,
    ProjectListSerializer,
    ProjectSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    """
    /api/v1/projects/                      GET (list), POST (create)
    /api/v1/projects/{id}/                 GET, PATCH, PUT, DELETE
    /api/v1/projects/{id}/archive/         POST
    /api/v1/projects/{id}/unarchive/       POST
    /api/v1/projects/{id}/employees/       GET (list assignments), POST (assign)
    /api/v1/projects/{id}/contractors/      GET (list contractor assignments)
    /api/v1/projects/{id}/release-employee/ POST  {"employee_id": "..."}
    /api/v1/projects/{id}/documents/       GET (linked documents)
    """

    permission_classes = [IsAuthenticated]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "project_type", "is_archived"]
    search_fields = ["name", "code", "location"]
    ordering_fields = ["created_at", "start_date", "contract_value", "name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Project.objects.all()
        params = self.request.query_params
        # Archived projects are hidden by default — pass ?include_archived=true
        # or filter explicitly with ?is_archived=true to see them.
        if "is_archived" not in params and params.get("include_archived") != "true":
            qs = qs.filter(is_archived=False)

        client_id = params.get("client")
        if client_id:
            qs = qs.filter(buyer_id=client_id)

        qs = filter_date_range(qs, params, "start_date")

        return qs

    def get_serializer_class(self):
        return ProjectListSerializer if self.action == "list" else ProjectSerializer

    def destroy(self, request, *args, **kwargs):
        # Hard delete is intentionally not exposed for a financial system —
        # archiving is the supported way to retire a project. Return 405
        # (client mistake) rather than a NotImplementedError/500.
        return Response(
            data={"detail": "Projects cannot be deleted. Use POST /archive/ instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        project = self.get_object()
        project.is_archived = True
        project.save(update_fields=["is_archived", "updated_at"])
        return Response(ProjectSerializer(project).data)

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        project = self.get_object()
        project.is_archived = False
        project.save(update_fields=["is_archived", "updated_at"])
        return Response(ProjectSerializer(project).data)

    @action(detail=True, methods=["get", "post"])
    def employees(self, request, pk=None):
        project = self.get_object()

        if request.method == "GET":
            qs = project.employee_assignments.filter(released_at__isnull=True)
            return Response(ProjectEmployeeSerializer(qs, many=True).data)

        serializer = ProjectEmployeeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(project=project, assigned_at=request.data.get("assigned_at") or timezone.localdate())
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="contractors")
    def contractors(self, request, pk=None):
        project = self.get_object()
        qs = project.contractor_assignments.filter(
            released_at__isnull=True
        ).select_related("contractor")
        return Response(ProjectContractorSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="release-employee")
    def release_employee(self, request, pk=None):
        project = self.get_object()
        employee_id = request.data.get("employee_id")
        if not employee_id:
            return Response(
                {"employee_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment = project.employee_assignments.filter(
            employee_id=employee_id, released_at__isnull=True
        ).first()
        if assignment is None:
            return Response(
                {"detail": "No active assignment found for this employee on this project."},
                status=status.HTTP_404_NOT_FOUND,
            )

        assignment.released_at = request.data.get("released_at") or timezone.localdate()
        assignment.save(update_fields=["released_at"])
        return Response(ProjectEmployeeSerializer(assignment).data)

    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        project = self.get_object()
        qs = ProjectDocument.objects.filter(entity_type="project", entity_id=project.id)
        return Response(ProjectDocumentSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="phases")
    def phases(self, request, pk=None):
        """Convenience read: same data as GET /phases/?project={id}."""
        project = self.get_object()
        qs = project.phases.all()
        return Response(PhaseSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="financial-summary")
    def financial_summary(self, request, pk=None):
        """
        Project financial roll-up derived from linked invoices and their
        payment allocations (not budgets): revenue (client invoices) and
        expenses (supplier + contractor invoices), each as billed /
        received-or-paid / outstanding, plus net accrual and cash
        positions. Changes the moment a payment allocation is recorded.
        """
        from .financial import get_project_financial_summary

        project = self.get_object()
        return Response(get_project_financial_summary(project))

    @action(detail=True, methods=["get"], url_path="budget-summary")
    def budget_summary(self, request, pk=None):
        """
        Budget vs Actual for this project's active budget (most recent
        APPROVED/REVISED budget, falling back to the most recent DRAFT).
        Pass ?budget={budget_id} to get the summary for a specific
        budget version instead of the auto-picked active one.
        """
        project = self.get_object()
        budget_id = request.query_params.get("budget")
        if budget_id:
            budget = Budget.objects.filter(id=budget_id, project=project).first()
            if budget is None:
                return Response(
                    {"detail": "No budget with that id on this project."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            budget = get_active_budget(project.id)
            if budget is None:
                return Response(
                    {"detail": "This project has no budget yet."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        return Response(get_budget_summary(budget))


class BudgetViewSet(viewsets.ModelViewSet):
    """
    Project Budgeting.

    /api/.../budgets/?project={id}       GET (list, filterable by project), POST (create)
    /api/.../budgets/{id}/                GET, PATCH, PUT, DELETE (includes itemized categories)
    /api/.../budgets/{id}/items/          GET (list), POST (add a category line)
    /api/.../budgets/{id}/summary/        GET — Budget vs Actual by category
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BudgetSerializer
    queryset = Budget.objects.all()

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["project", "status"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    @action(detail=True, methods=["get", "post"])
    def items(self, request, pk=None):
        budget = self.get_object()

        if request.method == "GET":
            return Response(BudgetItemSerializer(budget.items.all(), many=True).data)

        # budget_id is a required field on BudgetItemSerializer (it maps to
        # a NOT NULL FK), so it must be present before is_valid() rather
        # than injected afterward via .save(budget=...) — the URL already
        # tells us which budget, so fill it in from there.
        data = request.data.copy()
        data["budget_id"] = str(budget.id)
        serializer = BudgetItemSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        budget = self.get_object()
        return Response(get_budget_summary(budget))

    @action(detail=False, methods=["get"], url_path="portfolio-summary")
    def portfolio_summary(self, request):
        """
        GET /api/projects/budgets/portfolio-summary/?project={id}&status={status}

        Portfolio Budget vs Actual across projects -- one row per project
        (using each project's active budget via get_active_budget) plus an
        aggregate of budgeted/actual/variance/remaining. Optional ?project
        restricts to a single project; otherwise the whole (non-archived)
        portfolio is summarized.
        """
        from decimal import Decimal

        projects = Project.objects.all()
        project_id = request.query_params.get("project")
        if project_id:
            projects = projects.filter(id=project_id)
        else:
            projects = projects.filter(is_archived=False)

        rows = []
        totals = {
            "projects": 0,
            "budgeted": Decimal("0.00"),
            "actual": Decimal("0.00"),
            "variance": Decimal("0.00"),
            "remaining": Decimal("0.00"),
        }

        for project in projects:
            budget = get_active_budget(project.id)
            if budget is None:
                continue
            summary = get_budget_summary(budget)
            t = summary["totals"]
            rows.append(
                {
                    "project_id": str(project.id),
                    "project_name": project.name,
                    "project_code": project.code,
                    "budget_id": summary["budget_id"],
                    "budget_name": summary["budget_name"],
                    "budget_status": summary["budget_status"],
                    "total_budget_header": str(summary["total_budget_header"]),
                    "budgeted": str(t["budgeted"]),
                    "actual": str(t["actual"]),
                    "variance": str(t["variance"]),
                    "remaining": str(t["remaining"]),
                }
            )
            totals["projects"] += 1
            totals["budgeted"] += t["budgeted"]
            totals["actual"] += t["actual"]
            totals["variance"] += t["variance"]
            totals["remaining"] += t["remaining"]

        return Response(
            {
                "projects": rows,
                "totals": {
                    "projects": totals["projects"],
                    "budgeted": str(totals["budgeted"]),
                    "actual": str(totals["actual"]),
                    "variance": str(totals["variance"]),
                    "remaining": str(totals["remaining"]),
                },
            }
        )


class BudgetItemViewSet(viewsets.ModelViewSet):
    """
    Standalone CRUD for individual budget category lines — use this to
    edit/delete a line without re-fetching the whole budget.

    /api/.../budget-items/?budget={id}    GET, POST
    /api/.../budget-items/{id}/           GET, PATCH, PUT, DELETE
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BudgetItemSerializer
    queryset = BudgetItem.objects.all()

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["budget", "category", "phase"]


class PhaseViewSet(viewsets.ModelViewSet):
    """
    Project Planning (Phases).

    /api/v1/phases/?project={id}        GET (list, filterable by project), POST (create)
    /api/v1/phases/{id}/                GET, PATCH, PUT, DELETE
    /api/v1/phases/{id}/complete/       POST — shortcut: status=COMPLETED, progress=100
    /api/v1/phases/reorder/             POST — bulk-update sequence_number
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PhaseSerializer
    queryset = Phase.objects.all()

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["project", "status", "responsible_emp_id"]
    search_fields = ["name", "description"]
    ordering_fields = ["sequence_number", "start_date", "end_date"]
    ordering = ["project", "sequence_number"]

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        phase = self.get_object()
        serializer = self.get_serializer(
            phase, data={"status": Phase.STATUS_COMPLETED}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        """
        Body: {"phases": [{"id": "...", "sequence_number": 1}, {"id": "...", "sequence_number": 2}]}
        All-or-nothing: every id must belong to an existing phase, or nothing is changed.
        """
        items = request.data.get("phases")
        if not isinstance(items, list) or not items:
            return Response(
                {"phases": "Expected a non-empty list of {id, sequence_number}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ids = [str(item.get("id")) for item in items]
        phases_by_id = {str(p.id): p for p in Phase.objects.filter(id__in=ids)}
        missing = [i for i in ids if i not in phases_by_id]
        if missing:
            return Response(
                {"detail": f"Unknown phase id(s): {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            updated = []
            for item in items:
                phase = phases_by_id[str(item["id"])]
                phase.sequence_number = item["sequence_number"]
                phase.save(update_fields=["sequence_number", "updated_at"])
                updated.append(phase)

        updated.sort(key=lambda p: p.sequence_number)
        return Response(PhaseSerializer(updated, many=True).data)


class ChangeOrderViewSet(viewsets.ModelViewSet):
    """
    Change Order Management.

    /api/.../change-orders/?project={id}   GET (list, filterable by project/status), POST (create)
    /api/.../change-orders/{id}/           GET, PATCH, PUT (never changes status — see below), DELETE (blocked)
    /api/.../change-orders/{id}/approve/   POST — PENDING -> APPROVED, adds amount to Project.contract_value
    /api/.../change-orders/{id}/reject/    POST — PENDING -> REJECTED, no contract effect
    /api/.../change-orders/{id}/cancel/    POST — PENDING or APPROVED -> CANCELLED; reverses the
                                            contract_value effect if it was already APPROVED
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ChangeOrderSerializer
    queryset = ChangeOrder.objects.all()

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["project", "status"]
    ordering_fields = ["date", "created_at", "amount"]
    ordering = ["-date"]

    def destroy(self, request, *args, **kwargs):
        # Same reasoning as Project: a financial record with a contract-value
        # effect shouldn't disappear. Cancel it instead, for audit history.
        # Return 405 (client mistake) rather than a NotImplementedError/500.
        return Response(
            data={"detail": "Change orders cannot be deleted. Use POST /cancel/ instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        change_order = self.get_object()
        if change_order.status != ChangeOrder.STATUS_PENDING:
            return Response(
                {"detail": f"Cannot approve a change order in '{change_order.status}' status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            change_order.status = ChangeOrder.STATUS_APPROVED
            approved_by = request.data.get("approved_by")
            if approved_by:
                change_order.approved_by_id = approved_by
            change_order.save(update_fields=["status", "approved_by", "updated_at"])
            apply_change_order_to_contract(change_order)

        change_order.refresh_from_db()
        return Response(ChangeOrderSerializer(change_order).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        change_order = self.get_object()
        if change_order.status != ChangeOrder.STATUS_PENDING:
            return Response(
                {"detail": f"Cannot reject a change order in '{change_order.status}' status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        change_order.status = ChangeOrder.STATUS_REJECTED
        change_order.save(update_fields=["status", "updated_at"])
        return Response(ChangeOrderSerializer(change_order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        change_order = self.get_object()
        cancellable_from = {ChangeOrder.STATUS_PENDING, ChangeOrder.STATUS_APPROVED}
        if change_order.status not in cancellable_from:
            return Response(
                {"detail": f"Cannot cancel a change order in '{change_order.status}' status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            was_approved = change_order.status == ChangeOrder.STATUS_APPROVED
            change_order.status = ChangeOrder.STATUS_CANCELLED
            change_order.save(update_fields=["status", "updated_at"])
            if was_approved:
                reverse_change_order_from_contract(change_order)

        return Response(ChangeOrderSerializer(change_order).data)