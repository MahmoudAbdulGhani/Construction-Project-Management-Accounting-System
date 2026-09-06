from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from clients.models import Client
from employees.models import Employee

from .models import (
    Budget,
    BudgetItem,
    ChangeOrder,
    Phase,
    Project,
    ProjectDocument,
    ProjectEmployee,
)


class EmployeeSummarySerializer(serializers.ModelSerializer):
    """
    Small employee representation used inside project responses.

    This avoids returning the entire employee record every time.
    """

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_number",
            "name",
            "position",
            "department",
            "employment_status",
        ]
        read_only_fields = fields


class ProjectListSerializer(serializers.ModelSerializer):
    """Lightweight representation for the project list/table view."""

    manager = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "code",
            "name",
            "status",
            "project_type",
            "contract_value",
            "start_date",
            "expected_completion_date",
            "is_archived",
            "manager",
        ]


class ProjectEmployeeSerializer(serializers.ModelSerializer):
    """
    Employee assignment representation.

    `employee_id` remains the API field used for writes, while `employee`
    provides the actual employee information for the frontend.
    """

    employee_id = serializers.PrimaryKeyRelatedField(
        source="employee",
        queryset=Employee.objects.all(),
    )

    employee = EmployeeSummarySerializer(
        read_only=True,
    )

    class Meta:
        model = ProjectEmployee
        fields = [
            "id",
            "employee_id",
            "employee",
            "assigned_at",
            "released_at",
            "role_on_project",
        ]
        read_only_fields = [
            "id",
            "employee",
        ]


class ProjectDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectDocument
        fields = [
            "id",
            "file_name",
            "file_path",
            "file_type",
            "file_size",
            "document_type",
            "uploaded_by",
            "uploaded_at",
        ]
        read_only_fields = fields


class PhaseSerializer(serializers.ModelSerializer):
    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.all(),
    )

    responsible_emp_id = serializers.PrimaryKeyRelatedField(
        source="responsible_emp",
        queryset=Employee.objects.all(),
        allow_null=True,
        required=False,
    )

    responsible_employee = EmployeeSummarySerializer(
        source="responsible_emp",
        read_only=True,
    )

    class Meta:
        model = Phase
        fields = [
            "id",
            "project_id",
            "name",
            "description",
            "start_date",
            "end_date",
            "responsible_emp_id",
            "responsible_employee",
            "status",
            "progress_percentage",
            "sequence_number",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "responsible_employee",
        ]

    def validate_status(self, value):
        if self.instance is None:
            return value

        current = self.instance.status

        if value == current:
            return value

        allowed = Phase.ALLOWED_TRANSITIONS.get(
            current,
            set(),
        )

        if value not in allowed:
            allowed_display = (
                sorted(allowed)
                or "none — this is a final status"
            )

            raise serializers.ValidationError(
                f"Cannot move a phase from '{current}' to '{value}'. "
                f"Allowed next status(es): {allowed_display}."
            )

        return value

    def validate(self, attrs):
        start_date = attrs.get(
            "start_date",
            getattr(
                self.instance,
                "start_date",
                None,
            ),
        )

        end_date = attrs.get(
            "end_date",
            getattr(
                self.instance,
                "end_date",
                None,
            ),
        )

        if (
            start_date
            and end_date
            and end_date < start_date
        ):
            raise serializers.ValidationError(
                {
                    "end_date": (
                        "Cannot be earlier than the start date."
                    )
                }
            )

        if (
            attrs.get("status")
            == Phase.STATUS_COMPLETED
            and "progress_percentage" not in attrs
        ):
            attrs["progress_percentage"] = Decimal(
                "100.00"
            )

        return attrs


class ProjectSerializer(serializers.ModelSerializer):
    """
    Full read/write representation used for create, retrieve and update.

    Manager:
        manager_id -> accepts an employee UUID
        manager    -> returns employee details

    Employees:
        employees -> returns project employee assignments
    """

    manager_id = serializers.PrimaryKeyRelatedField(
        source="manager",
        queryset=Employee.objects.all(),
        allow_null=True,
        required=False,
    )

    manager = EmployeeSummarySerializer(
        read_only=True,
    )

    employees = ProjectEmployeeSerializer(
        source="employee_assignments",
        many=True,
        read_only=True,
    )

    phases = PhaseSerializer(
        many=True,
        read_only=True,
    )

    buyer_id = serializers.PrimaryKeyRelatedField(
        source="buyer",
        queryset=Client.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Project
        fields = [
            "id",
            "code",
            "name",
            "location",
            "project_type",

            # Manager
            "manager_id",
            "manager",

            # Buyer
            "buyer_id",

            "estimated_sale_price",
            "actual_sale_price",
            "start_date",
            "expected_completion_date",
            "actual_completion_date",
            "contract_value",
            "status",
            "description",
            "is_archived",
            "created_at",
            "updated_at",

            # Relations
            "employees",
            "phases",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "is_archived",
            "manager",
        ]

    def validate_status(self, value):
        if self.instance is None:
            return value

        current = self.instance.status

        if value == current:
            return value

        allowed = Project.ALLOWED_TRANSITIONS.get(
            current,
            set(),
        )

        if value not in allowed:
            allowed_display = (
                sorted(allowed)
                or "none — this is a final status"
            )

            raise serializers.ValidationError(
                f"Cannot move a project from '{current}' to '{value}'. "
                f"Allowed next status(es): {allowed_display}."
            )

        return value

    def validate(self, attrs):
        start_date = attrs.get(
            "start_date",
            getattr(
                self.instance,
                "start_date",
                None,
            ),
        )

        expected = attrs.get(
            "expected_completion_date",
            getattr(
                self.instance,
                "expected_completion_date",
                None,
            ),
        )

        if (
            start_date
            and expected
            and expected < start_date
        ):
            raise serializers.ValidationError(
                {
                    "expected_completion_date": (
                        "Cannot be earlier than the start date."
                    )
                }
            )

        return attrs


class BudgetItemSerializer(serializers.ModelSerializer):
    budget_id = serializers.PrimaryKeyRelatedField(
        source="budget",
        queryset=Budget.objects.all(),
    )

    phase_id = serializers.PrimaryKeyRelatedField(
        source="phase",
        queryset=Phase.objects.all(),
        allow_null=True,
        required=False,
    )

    category = serializers.CharField(
        max_length=50,
    )

    class Meta:
        model = BudgetItem
        fields = [
            "id",
            "budget_id",
            "phase_id",
            "category",
            "description",
            "budgeted_amount",
        ]

        read_only_fields = ["id"]

    def validate(self, attrs):
        budget = attrs.get(
            "budget",
            getattr(
                self.instance,
                "budget",
                None,
            ),
        )

        amount = attrs.get(
            "budgeted_amount",
            getattr(
                self.instance,
                "budgeted_amount",
                None,
            ),
        )

        if budget is None or amount is None:
            return attrs

        if (
            self.instance is None
            and budget.status
            not in (
                Budget.STATUS_DRAFT,
                Budget.STATUS_REVISED,
            )
        ):
            raise serializers.ValidationError(
                {
                    "budget_id": (
                        f"Cannot add items to a budget in "
                        f"'{budget.status}' status — only DRAFT "
                        f"or REVISED budgets accept new items."
                    )
                }
            )

        existing = BudgetItem.objects.filter(
            budget=budget
        )

        if self.instance is not None:
            existing = existing.exclude(
                pk=self.instance.pk
            )

        allocated = (
            existing.aggregate(
                total=Sum("budgeted_amount")
            )["total"]
            or Decimal("0.00")
        )

        if allocated + amount > budget.total_budget:
            remaining = (
                budget.total_budget - allocated
            )

            raise serializers.ValidationError(
                {
                    "budgeted_amount": (
                        f"This would exceed the budget's "
                        f"total of {budget.total_budget}. "
                        f"Remaining unallocated: {remaining}."
                    )
                }
            )

        return attrs


class BudgetSerializer(serializers.ModelSerializer):
    items = BudgetItemSerializer(
        many=True,
        read_only=True,
    )

    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.all(),
    )

    class Meta:
        model = Budget

        fields = [
            "id",
            "project_id",
            "name",
            "total_budget",
            "status",
            "created_at",
            "updated_at",
            "items",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate_status(self, value):
        if self.instance is None:
            return value

        current = self.instance.status

        if value == current:
            return value

        allowed = Budget.ALLOWED_TRANSITIONS.get(
            current,
            set(),
        )

        if value not in allowed:
            allowed_display = (
                sorted(allowed)
                or "none — this is a final status"
            )

            raise serializers.ValidationError(
                f"Cannot move a budget from '{current}' to '{value}'. "
                f"Allowed next status(es): {allowed_display}."
            )

        return value

    def validate(self, attrs):
        total_budget = attrs.get("total_budget")

        if (
            self.instance is not None
            and total_budget is not None
        ):
            allocated = (
                self.instance.items.aggregate(
                    total=Sum("budgeted_amount")
                )["total"]
                or Decimal("0.00")
            )

            if total_budget < allocated:
                raise serializers.ValidationError(
                    {
                        "total_budget": (
                            f"Cannot set the total below "
                            f"{allocated}, which is already "
                            f"allocated to this budget's items."
                        )
                    }
                )

        return attrs


class ChangeOrderSerializer(serializers.ModelSerializer):
    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.all(),
    )

    class Meta:
        model = ChangeOrder

        fields = [
            "id",
            "project_id",
            "number",
            "description",
            "reason",
            "amount",
            "requested_by",
            "approved_by",
            "date",
            "status",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "status",
            "approved_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        number = attrs.get(
            "number",
            getattr(
                self.instance,
                "number",
                None,
            ),
        )

        project = attrs.get(
            "project",
            getattr(
                self.instance,
                "project",
                None,
            ),
        )

        if number and project:
            qs = ChangeOrder.objects.filter(
                project=project,
                number=number,
            )

            if self.instance is not None:
                qs = qs.exclude(
                    pk=self.instance.pk
                )

            if qs.exists():
                raise serializers.ValidationError(
                    {
                        "number": (
                            "A change order with this number "
                            "already exists on this project."
                        )
                    }
                )

        return attrs