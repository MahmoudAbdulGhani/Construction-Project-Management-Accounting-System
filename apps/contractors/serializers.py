"""
Serializers for the ``contractors`` app -- Contractor Management API.

Field definitions follow ``database/construction_management_supabase.sql``
exactly (contractors, project_contractors, documents).
"""
from rest_framework import serializers

from .models import Contractor, ContractorDocument, ContractorProjectAssignment


class ContractorListSerializer(serializers.ModelSerializer):
    """Compact row used for the list view."""

    class Meta:
        model = Contractor
        fields = [
            "id",
            "name",
            "company_name",
            "phone",
            "email",
            "specialization",
            "payment_terms",
            "rate",
            "status",
        ]


class ContractorSerializer(serializers.ModelSerializer):
    """Full read/write representation of a contractor record."""

    class Meta:
        model = Contractor
        fields = [
            "id",
            "name",
            "company_name",
            "phone",
            "email",
            "contract_details",
            "specialization",
            "payment_terms",
            "rate",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_email(self, value):
        # email isn't unique at the DB level on `contractors`, so this is
        # just a light sanity check, not a uniqueness constraint.
        return value

    def validate_rate(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Rate cannot be negative.")
        return value


class ContractorProjectSerializer(serializers.ModelSerializer):
    """One row of ``project_contractors`` with the project summarized inline."""

    project = serializers.SerializerMethodField()

    class Meta:
        model = ContractorProjectAssignment
        fields = [
            "id",
            "project",
            "contract_amount",
            "assigned_at",
            "released_at",
            "status",
        ]

    def get_project(self, obj):
        return {
            "id": str(obj.project_id),
            "code": obj.project.code,
            "name": obj.project.name,
            "status": obj.project.status,
        }


class ContractorAssignSerializer(serializers.Serializer):
    """Input for assigning a contractor to a project (POST .../projects/).

    ``project_id`` is taken explicitly here so the effective
    (contractor_id, project_id) pair drives the duplicate check instead of
    being smuggled through a nested relation on the model.
    """

    project_id = serializers.UUIDField()
    contract_amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0,
    )
    assigned_at = serializers.DateField()
    released_at = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(
        choices=ContractorProjectAssignment.Status.choices,
        required=False,
        default=ContractorProjectAssignment.Status.ASSIGNED,
    )

    def validate(self, attrs):
        released_at = attrs.get("released_at")
        if released_at and released_at < attrs["assigned_at"]:
            raise serializers.ValidationError(
                {"released_at": "Release date cannot be earlier than the assignment date."}
            )
        # The schema has no UNIQUE(project_id, contractor_id), so duplicates
        # are blocked here at the application/serializer level.
        contractor = self.context["contractor"]
        duplicate = ContractorProjectAssignment.objects.filter(
            contractor_id=contractor.id, project_id=attrs["project_id"]
        ).exists()
        if duplicate:
            raise serializers.ValidationError(
                {"project_id": "This contractor is already assigned to the project."}
            )
        return attrs


class ContractorAssignmentUpdateSerializer(serializers.ModelSerializer):
    """Update/release of an existing assignment (PATCH .../projects/{id}/).

    The assignment's project and contractor are immutable once created.
    """

    class Meta:
        model = ContractorProjectAssignment
        fields = ["contract_amount", "released_at", "status"]

    def validate(self, attrs):
        released_at = attrs.get("released_at")
        if released_at and released_at < self.instance.assigned_at:
            raise serializers.ValidationError(
                {"released_at": "Release date cannot be earlier than the assignment date."}
            )
        return attrs


class ProjectContractorSerializer(serializers.ModelSerializer):
    """One row of ``project_contractors`` served from the project side,
    with the contractor summarized inline (mirror of
    ``ContractorProjectSerializer``)."""

    contractor = ContractorListSerializer(read_only=True)

    class Meta:
        model = ContractorProjectAssignment
        fields = [
            "id",
            "contractor",
            "contract_amount",
            "assigned_at",
            "released_at",
            "status",
        ]


class ContractorDocumentSerializer(serializers.ModelSerializer):
    """Read-only metadata for one contractor document."""

    class Meta:
        model = ContractorDocument
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