"""
Serializers for the ``employees`` app -- Employee Management API.

Field definitions follow ``database/construction_management_supabase.sql``
exactly (employees, project_employees).
"""
from rest_framework import serializers

from projects.models import Project

from .models import Employee, EmployeeProjectAssignment


class EmployeeListSerializer(serializers.ModelSerializer):
    """Compact row used for the list view."""

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_number",
            "name",
            "phone",
            "email",
            "position",
            "department",
            "labor_rate",
            "employment_status",
            "labor_rate",
        ]


class EmployeeSerializer(serializers.ModelSerializer):
    """Full read/write representation of an employee record."""

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_number",
            "name",
            "phone",
            "email",
            "position",
            "department",
            "employment_status",
            "labor_rate",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_email(self, value):
        # EmailField already enforces format; only non-empty values reach here.
        return value

    def validate_labor_rate(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Labor rate cannot be negative.")
        return value


class EmployeeProjectSerializer(serializers.ModelSerializer):
    """One row of ``project_employees`` with the project summarized inline."""

    project = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeProjectAssignment
        fields = [
            "id",
            "project",
            "assigned_at",
            "released_at",
            "role_on_project",
        ]

    def get_project(self, obj):
        return {
            "id": str(obj.project_id),
            "code": obj.project.code,
            "name": obj.project.name,
            "status": obj.project.status,
        }


class EmployeeAssignSerializer(serializers.Serializer):
    """Input for assigning an employee to a project (POST .../projects/).

    ``project_id`` is taken explicitly so the effective
    (employee_id, project_id) pair drives the duplicate check. There is no
    assignment-status column on ``project_employees`` -- an assignment is
    active while ``released_at`` is null and an explicit release happens via
    PATCH.
    """

    project_id = serializers.UUIDField()
    assigned_at = serializers.DateField()
    role_on_project = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=150
    )

    def validate(self, attrs):
        # Confirm the referenced project exists (project_employees has a real
        # FK to projects), surfacing a clean 400 rather than a DB error or a
        # broken serialization.
        try:
            Project.objects.get(id=attrs["project_id"])
        except Project.DoesNotExist:
            raise serializers.ValidationError(
                {"project_id": "Project does not exist."}
            )
        # The schema has UNIQUE(project_id, employee_id) on project_employees,
        # but we surface a clean error here rather than a raw 500 from the
        # DB constraint.
        employee = self.context["employee"]
        duplicate = EmployeeProjectAssignment.objects.filter(
            employee_id=employee.id, project_id=attrs["project_id"]
        ).exists()
        if duplicate:
            raise serializers.ValidationError(
                {"project_id": "This employee is already assigned to the project."}
            )
        return attrs


class EmployeeAssignmentUpdateSerializer(serializers.ModelSerializer):
    """Update/release of an existing assignment (PATCH .../projects/{id}/).

    The assignment's project and employee are immutable once created; only
    the release date and role may change.
    """

    class Meta:
        model = EmployeeProjectAssignment
        fields = ["released_at", "role_on_project"]

    def validate(self, attrs):
        released_at = attrs.get("released_at")
        if released_at and released_at < self.instance.assigned_at:
            raise serializers.ValidationError(
                {"released_at": "Release date cannot be earlier than the assignment date."}
            )
        return attrs
