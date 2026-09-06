import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from clients.models import Client

# Real Expense Management app
from expenses.models import Expense


class Project(models.Model):
    """
    Maps onto the existing `projects` table in Supabase.

    Employee relationships:
        manager -> employees.Employee
        buyer   -> clients.Client

    The manager relationship uses the existing `manager_id` database column.
    """

    STATUS_PLANNING = "PLANNING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_ON_HOLD = "ON_HOLD"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_PLANNING, "Planning"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_ON_HOLD, "On Hold"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    ALLOWED_TRANSITIONS = {
        STATUS_PLANNING: {STATUS_ACTIVE, STATUS_CANCELLED},
        STATUS_ACTIVE: {STATUS_ON_HOLD, STATUS_COMPLETED, STATUS_CANCELLED},
        STATUS_ON_HOLD: {STATUS_ACTIVE, STATUS_CANCELLED},
        STATUS_COMPLETED: set(),
        STATUS_CANCELLED: set(),
    }

    TYPE_WHOLE_BUILDING = "WHOLE_BUILDING"
    TYPE_MULTI_UNIT = "MULTI_UNIT"

    TYPE_CHOICES = [
        (TYPE_WHOLE_BUILDING, "Whole Building"),
        (TYPE_MULTI_UNIT, "Multi Unit"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # ------------------------------------------------------------------
    # Manager
    # ------------------------------------------------------------------
    # This is now a real Django FK to the existing employees table.
    #
    # The physical database column remains `manager_id`, so existing
    # database data and API payloads remain compatible.
    manager = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        db_column="manager_id",
        null=True,
        blank=True,
        related_name="managed_projects",
    )

    # ------------------------------------------------------------------
    # Buyer
    # ------------------------------------------------------------------
    buyer = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        db_column="buyer_id",
        null=True,
        blank=True,
        related_name="projects",
    )

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True)
    location = models.TextField(blank=True, null=True)
    project_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
    )

    estimated_sale_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    actual_sale_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    start_date = models.DateField()

    expected_completion_date = models.DateField(
        null=True,
        blank=True,
    )

    actual_completion_date = models.DateField(
        null=True,
        blank=True,
    )

    contract_value = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PLANNING,
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    is_archived = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "projects"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class ProjectEmployee(models.Model):
    """
    Maps onto `project_employees`.

    This is the project's view of the employee/project relationship.

    `employee` is a real FK to employees.Employee while preserving
    the existing physical `employee_id` column.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        db_column="project_id",
        related_name="employee_assignments",
    )

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        db_column="employee_id",
        related_name="project_employee_records",
    )

    assigned_at = models.DateField()

    released_at = models.DateField(
        null=True,
        blank=True,
    )

    role_on_project = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "project_employees"
        unique_together = (("project", "employee"),)

    def __str__(self):
        return f"{self.employee.name} on {self.project.code}"



class ProjectDocument(models.Model):
    """
    Read-mostly mapping onto the shared `documents` table.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    uploaded_by = models.UUIDField()

    file_name = models.CharField(
        max_length=255,
    )

    file_path = models.CharField(
        max_length=500,
    )

    file_type = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    file_size = models.BigIntegerField(
        null=True,
        blank=True,
    )

    document_type = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    entity_type = models.CharField(
        max_length=100,
    )

    entity_id = models.UUIDField()

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        managed = False
        db_table = "documents"

    def __str__(self):
        return self.file_name


class Phase(models.Model):
    """
    Project Planning — maps onto `project_phases`.
    """

    STATUS_NOT_STARTED = "NOT_STARTED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_ON_HOLD = "ON_HOLD"

    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, "Not Started"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_ON_HOLD, "On Hold"),
    ]

    ALLOWED_TRANSITIONS = {
        STATUS_NOT_STARTED: {STATUS_IN_PROGRESS},
        STATUS_IN_PROGRESS: {STATUS_ON_HOLD, STATUS_COMPLETED},
        STATUS_ON_HOLD: {STATUS_IN_PROGRESS},
        STATUS_COMPLETED: set(),
    }

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        db_column="project_id",
        related_name="phases",
    )

    name = models.CharField(
        max_length=255,
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    start_date = models.DateField(
        null=True,
        blank=True,
    )

    end_date = models.DateField(
        null=True,
        blank=True,
    )

    # ------------------------------------------------------------------
    # Responsible employee
    # ------------------------------------------------------------------
    # Existing database column remains responsible_emp_id.
    responsible_emp = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        db_column="responsible_emp_id",
        null=True,
        blank=True,
        related_name="responsible_phases",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_STARTED,
    )

    progress_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
    )

    sequence_number = models.IntegerField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "project_phases"
        ordering = ["project_id", "sequence_number"]

    def __str__(self):
        return f"{self.project_id} · {self.sequence_number}. {self.name}"


# ---------------------------------------------------------------------------
# Project Budgeting
# ---------------------------------------------------------------------------

class Budget(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_APPROVED = "APPROVED"
    STATUS_REVISED = "REVISED"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REVISED, "Revised"),
        (STATUS_CLOSED, "Closed"),
    ]

    ALLOWED_TRANSITIONS = {
        STATUS_DRAFT: {STATUS_APPROVED},
        STATUS_APPROVED: {STATUS_REVISED, STATUS_CLOSED},
        STATUS_REVISED: {STATUS_APPROVED, STATUS_CLOSED},
        STATUS_CLOSED: set(),
    }

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        db_column="project_id",
        related_name="budgets",
    )

    name = models.CharField(
        max_length=255,
    )

    total_budget = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "project_budgets"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.project_id})"


class BudgetItem(models.Model):
    CATEGORY_MATERIALS = "MATERIALS"
    CATEGORY_LABOR = "LABOR"
    CATEGORY_CONTRACTORS = "CONTRACTORS"
    CATEGORY_EQUIPMENT = "EQUIPMENT"
    CATEGORY_OTHER = "OTHER"

    CATEGORY_CHOICES = [
        (CATEGORY_MATERIALS, "Materials"),
        (CATEGORY_LABOR, "Labor"),
        (CATEGORY_CONTRACTORS, "Contractors"),
        (CATEGORY_EQUIPMENT, "Equipment"),
        (CATEGORY_OTHER, "Other"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    budget = models.ForeignKey(
        Budget,
        on_delete=models.CASCADE,
        db_column="budget_id",
        related_name="items",
    )

    phase = models.ForeignKey(
        Phase,
        on_delete=models.SET_NULL,
        db_column="phase_id",
        null=True,
        blank=True,
        related_name="budget_items",
    )

    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
    )

    description = models.TextField(
        blank=True,
        null=True,
    )

    budgeted_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        db_table = "budget_items"

    def __str__(self):
        return f"{self.category} — {self.budgeted_amount}"


def normalize_category_name(name):
    return (name or "").strip().upper().replace(" ", "_")


def get_active_budget(project_id):
    qs = Budget.objects.filter(project_id=project_id)

    active = qs.filter(
        status__in=[
            Budget.STATUS_APPROVED,
            Budget.STATUS_REVISED,
        ]
    ).first()

    return active or qs.first()


def get_budget_summary(budget):
    from decimal import Decimal

    from django.db.models import F, Sum

    items = BudgetItem.objects.filter(budget=budget)

    budgeted_by_category = {
        row["category"]: row["total"]
        for row in items.values("category").annotate(
            total=Sum("budgeted_amount")
        )
    }

    actual_rows = (
        Expense.objects.filter(
            project_id=budget.project_id,
            status__in=[
                Expense.Status.APPROVED,
                Expense.Status.PAID,
            ],
        )
        .values("category__name")
        .annotate(
            total=Sum(
                F("amount") + F("tax_amount")
            )
        )
    )

    actual_by_category = {}

    for row in actual_rows:
        key = normalize_category_name(row["category__name"])

        actual_by_category[key] = (
            actual_by_category.get(
                key,
                Decimal("0.00"),
            )
            + (row["total"] or Decimal("0.00"))
        )

    categories = []

    all_keys = (
        set(budgeted_by_category)
        | set(actual_by_category)
    )

    all_keys |= {
        c[0]
        for c in BudgetItem.CATEGORY_CHOICES
    }

    category_labels = dict(
        BudgetItem.CATEGORY_CHOICES
    )

    total_budgeted = Decimal("0.00")
    total_actual = Decimal("0.00")

    for key in sorted(all_keys):
        budgeted = budgeted_by_category.get(
            key,
            Decimal("0.00"),
        )

        actual = actual_by_category.get(
            key,
            Decimal("0.00"),
        )

        variance = actual - budgeted
        remaining = budgeted - actual

        total_budgeted += budgeted
        total_actual += actual

        categories.append(
            {
                "category": key,
                "category_display": category_labels.get(
                    key,
                    key.title(),
                ),
                "budgeted": budgeted,
                "actual": actual,
                "variance": variance,
                "remaining": remaining,
                "percent_used": (
                    float(actual / budgeted * 100)
                    if budgeted
                    else None
                ),
            }
        )

    return {
        "budget_id": str(budget.id),
        "project_id": str(budget.project_id),
        "budget_name": budget.name,
        "budget_status": budget.status,
        "total_budget_header": budget.total_budget,
        "unallocated_budget": (
            budget.total_budget - total_budgeted
        ),
        "categories": categories,
        "totals": {
            "budgeted": total_budgeted,
            "actual": total_actual,
            "variance": total_actual - total_budgeted,
            "remaining": total_budgeted - total_actual,
        },
    }


# ---------------------------------------------------------------------------
# Change Order Management
# ---------------------------------------------------------------------------

class ChangeOrder(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    ALLOWED_TRANSITIONS = {
        STATUS_PENDING: {
            STATUS_APPROVED,
            STATUS_REJECTED,
            STATUS_CANCELLED,
        },
        STATUS_APPROVED: {
            STATUS_CANCELLED,
        },
        STATUS_REJECTED: set(),
        STATUS_CANCELLED: set(),
    }

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        db_column="project_id",
        related_name="change_orders",
    )

    number = models.CharField(
        max_length=100,
    )

    description = models.TextField()

    reason = models.TextField(
        blank=True,
        null=True,
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    requested_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="requested_by",
        related_name="change_orders_requested",
    )

    approved_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="approved_by",
        related_name="change_orders_approved",
    )

    date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "change_orders"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.number} — {self.project_id}"


def apply_change_order_to_contract(change_order):
    from django.db.models import F

    Project.objects.filter(
        pk=change_order.project_id
    ).update(
        contract_value=F("contract_value")
        + change_order.amount
    )


def reverse_change_order_from_contract(change_order):
    from django.db.models import F

    Project.objects.filter(
        pk=change_order.project_id
    ).update(
        contract_value=F("contract_value")
        - change_order.amount
    )