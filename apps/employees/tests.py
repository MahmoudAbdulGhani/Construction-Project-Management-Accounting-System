"""
Tests for the ``employees`` app -- Employee Management API.

All employee models are ``managed=False``, so tests materialize the
``employees`` / ``project_employees`` tables via ``WithEmployeesTableMixin``
and the ``projects`` / ``clients`` tables via ``WithProjectsTableMixin`` /
``WithClientsTableMixin`` (exactly the pattern already used by the
suppliers/contractors suites).
"""
import uuid

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from clients.testing import WithClientsTableMixin
from projects.models import Project
from projects.testing import WithProjectsTableMixin

from .models import Employee, EmployeeProjectAssignment
from .testing import WithEmployeesTableMixin


def make_employee(**overrides):
    """Build + save an Employee row (requires the employees table)."""
    defaults = {
        "employee_number": f"EMP-{uuid.uuid4().hex[:8].upper()}",
        "name": "Nada Alali",
        "phone": "555-0101",
        "email": "nada.alali@example.com",
        "position": "Site Engineer",
        "department": "Engineering",
        "employment_status": Employee.EmploymentStatus.ACTIVE,
        "labor_rate": "45.00",
    }
    defaults.update(overrides)
    return Employee.objects.create(**defaults)


def make_project(**overrides):
    """Build + save a Project row (requires the projects table)."""
    defaults = {
        "name": "Riverside Villas",
        "code": f"PRJ-{uuid.uuid4().hex[:8].upper()}",
        "project_type": "MULTI_UNIT",
        "start_date": "2026-01-15",
        "contract_value": "2500000.00",
    }
    defaults.update(overrides)
    return Project.objects.create(**defaults)


class EmployeeModelTests(
    WithClientsTableMixin, WithProjectsTableMixin, WithEmployeesTableMixin, TestCase
):
    def test_create_with_required_fields_only(self):
        employee = Employee.objects.create(
            employee_number="EMP-0001", name="Kareem Musa"
        )
        self.assertEqual(employee.employment_status, Employee.EmploymentStatus.ACTIVE)
        self.assertIsNone(employee.labor_rate)
        self.assertEqual(str(employee), "Kareem Musa")

    def test_timestamps_are_set_on_create(self):
        employee = make_employee()
        self.assertIsNotNone(employee.created_at)
        self.assertIsNotNone(employee.updated_at)

    def test_assignment_holds_schema_fields(self):
        project = make_project()
        employee = make_employee()
        assignment = EmployeeProjectAssignment.objects.create(
            employee=employee,
            project=project,
            assigned_at="2026-02-01",
            role_on_project="Site Lead",
        )
        self.assertIsNone(assignment.released_at)
        self.assertEqual(assignment.project_id, project.id)
        self.assertEqual(assignment.employee_id, employee.id)

    def test_assignment_unique_per_employee_project(self):
        project = make_project()
        make_employee_to_project = make_employee
        employee = make_employee_to_project()
        EmployeeProjectAssignment.objects.create(
            employee=employee, project=project, assigned_at="2026-02-01"
        )
        with self.assertRaises(Exception):
            EmployeeProjectAssignment.objects.create(
                employee=employee, project=project, assigned_at="2026-02-10"
            )


class EmployeeAPITestBase(
    WithClientsTableMixin, WithProjectsTableMixin, WithEmployeesTableMixin, TestCase
):
    """Authenticated API client plus a project + employee fixture."""

    def setUp(self):
        self.django_user = DjangoUser.objects.create_user(
            username="owner", password="pass12345"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.django_user)
        self.project = make_project()
        self.employee = make_employee()

    def post_employee(self, data):
        return self.client.post("/api/employees/", data, format="json")

    def assign_project(self, employee=None, project=None, **overrides):
        employee = employee or self.employee
        project = project or self.project
        payload = {"project_id": str(project.id), "assigned_at": "2026-02-01"}
        payload.update(overrides)
        return self.client.post(
            f"/api/employees/{employee.id}/projects/", payload, format="json"
        )

    def assignment_url(self, employee, assignment_id):
        return f"/api/employees/{employee.id}/projects/{assignment_id}/"


class EmployeeAPIAuthTests(EmployeeAPITestBase):
    def test_list_requires_authentication(self):
        anonymous = APIClient()
        self.assertEqual(
            anonymous.get("/api/employees/").status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_create_requires_authentication(self):
        anonymous = APIClient()
        response = anonymous.post(
            "/api/employees/",
            {"employee_number": "EMP-X", "name": "No Auth"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_detail_requires_authentication(self):
        anonymous = APIClient()
        response = anonymous.get(f"/api/employees/{self.employee.id}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class EmployeeListCreateTests(EmployeeAPITestBase):
    def test_create_employee(self):
        response = self.post_employee(
            {
                "employee_number": "EMP-2001",
                "name": "Lina Haddad",
                "phone": "555-0199",
                "email": "lina.haddad@example.com",
                "position": "Quantity Surveyor",
                "department": "Costing",
                "labor_rate": "60.00",
            }
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.data
        self.assertEqual(body["employee_number"], "EMP-2001")
        self.assertEqual(body["name"], "Lina Haddad")
        self.assertEqual(body["position"], "Quantity Surveyor")
        self.assertEqual(body["department"], "Costing")
        self.assertEqual(body["labor_rate"], "60.00")
        self.assertEqual(body["employment_status"], Employee.EmploymentStatus.ACTIVE)
        self.assertIn("id", body)
        self.assertIn("created_at", body)

    def test_name_is_required(self):
        response = self.post_employee({"employee_number": "EMP-3001"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_employee_number_is_required(self):
        response = self.post_employee({"name": "No Number"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("employee_number", response.data)

    def test_duplicate_employee_number_rejected(self):
        existing = make_employee()
        response = self.post_employee(
            {"employee_number": existing.employee_number, "name": "Duplicate"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_email_rejected(self):
        response = self.post_employee(
            {"employee_number": "EMP-4001", "name": "Bad Email", "email": "not-an-email"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_negative_labor_rate_rejected(self):
        response = self.post_employee(
            {"employee_number": "EMP-5001", "name": "Bad Rate", "labor_rate": "-10.00"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("labor_rate", response.data)

    def test_invalid_employment_status_rejected(self):
        response = self.post_employee(
            {
                "employee_number": "EMP-6001",
                "name": "Bad Status",
                "employment_status": "GONE",
            }
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("employment_status", response.data)

    def test_list_employees(self):
        second = make_employee(name="Omar Khaled", employee_number="EMP-LIST-2")
        response = self.client.get("/api/employees/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        ids = {row["id"] for row in results}
        self.assertIn(str(self.employee.id), ids)
        self.assertIn(str(second.id), ids)

    def test_list_employee_includes_labor_rate(self):
        response = self.client.get("/api/employees/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(
            item
            for item in response.data["results"]
            if item["id"] == str(self.employee.id)
        )
        self.assertEqual(row["labor_rate"], "45.00")

    def test_search_employees_by_name(self):
        make_employee(
            name="Bravo Staff",
            employee_number="EMP-BRAVO",
            email="bravo.staff@example.com",
            position="Accountant",
            department="Finance",
        )
        response = self.client.get("/api/employees/?search=Nada")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data["results"]]
        self.assertEqual(names, ["Nada Alali"])

    def test_retrieve_employee_detail(self):
        response = self.client.get(f"/api/employees/{self.employee.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.data
        self.assertEqual(body["position"], "Site Engineer")
        self.assertEqual(body["department"], "Engineering")
        self.assertEqual(body["labor_rate"], "45.00")
        self.assertEqual(body["employment_status"], Employee.EmploymentStatus.ACTIVE)
        self.assertIn("created_at", body)
        self.assertIn("updated_at", body)

    def test_update_employee(self):
        response = self.client.patch(
            f"/api/employees/{self.employee.id}/",
            {"position": "Senior Site Engineer", "department": "Operations"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["position"], "Senior Site Engineer")
        self.assertEqual(response.data["department"], "Operations")

    def test_update_employment_status(self):
        response = self.client.patch(
            f"/api/employees/{self.employee.id}/",
            {"employment_status": Employee.EmploymentStatus.ON_LEAVE},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["employment_status"], Employee.EmploymentStatus.ON_LEAVE)

    def test_delete_employee_without_assignments(self):
        employee = make_employee(name="Disposable", employee_number="EMP-DEL-1")
        response = self.client.delete(f"/api/employees/{employee.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        get = self.client.get(f"/api/employees/{employee.id}/")
        self.assertEqual(get.status_code, status.HTTP_404_NOT_FOUND)


class EmployeeProjectAssignmentTests(EmployeeAPITestBase):
    def test_list_assignments_empty(self):
        response = self.client.get(f"/api/employees/{self.employee.id}/projects/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_assign_employee_to_project(self):
        response = self.assign_project(role_on_project="Site Lead")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.data
        self.assertEqual(body["project"]["id"], str(self.project.id))
        self.assertEqual(body["project"]["code"], self.project.code)
        self.assertEqual(body["project"]["name"], self.project.name)
        self.assertEqual(body["assigned_at"], "2026-02-01")
        self.assertEqual(body["role_on_project"], "Site Lead")
        self.assertIsNone(body["released_at"])
        self.assertEqual(EmployeeProjectAssignment.objects.count(), 1)

    def test_assignment_requires_assigned_at(self):
        response = self.assign_project(assigned_at=None)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_assignment_rejected(self):
        self.assertEqual(self.assign_project().status_code, status.HTTP_201_CREATED)
        response = self.assign_project()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EmployeeProjectAssignment.objects.count(), 1)

    def test_invalid_project_id_rejected(self):
        response = self.assign_project(project_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_release_update_assignment(self):
        created = self.assign_project()
        assignment_id = created.data["id"]
        response = self.client.patch(
            self.assignment_url(self.employee, assignment_id),
            {"released_at": "2026-05-01", "role_on_project": "PM"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["released_at"], "2026-05-01")
        self.assertEqual(response.data["role_on_project"], "PM")

    def test_update_release_before_assignment_rejected(self):
        created = self.assign_project(assigned_at="2026-04-01")
        assignment_id = created.data["id"]
        response = self.client.patch(
            self.assignment_url(self.employee, assignment_id),
            {"released_at": "2026-03-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("released_at", response.data)

    def test_unassign_deletes_assignment(self):
        created = self.assign_project()
        assignment_id = created.data["id"]
        response = self.client.delete(
            self.assignment_url(self.employee, assignment_id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(EmployeeProjectAssignment.objects.count(), 0)
        listing = self.client.get(f"/api/employees/{self.employee.id}/projects/")
        self.assertEqual(listing.data, [])

    def test_assignment_scoped_to_employee(self):
        other = make_employee(name="Other Staff", employee_number="EMP-OTHER-1")
        created = self.assign_project(employee=other)
        assignment_id = created.data["id"]
        # Trying to touch another employee's assignment 404s.
        response = self.client.delete(
            self.assignment_url(self.employee, assignment_id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(EmployeeProjectAssignment.objects.count(), 1)

    def test_unassign_unknown_assignment_404(self):
        response = self.client.delete(
            self.assignment_url(self.employee, uuid.uuid4())
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class EmployeePageRenderTests(TestCase):
    """The dashboard Employees page is server-rendered HTML + client-side JS
    that speaks to the /api/employees API. These tests confirm the page
    renders and the view is auth-protected; the JS itself is exercised in
    the browser against the API endpoints (covered by the API tests above)."""

    def test_page_requires_login(self):
        response = self.client.get("/employees/")
        self.assertEqual(response.status_code, 302)  # redirect to login

    def test_page_renders_for_authenticated_user(self):
        user = DjangoUser.objects.create_user(username="owner", password="pass12345")
        self.client.force_login(user)
        response = self.client.get("/employees/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Employees", content)
        self.assertIn("employees.js", content)
        self.assertIn("employees.css", content)
        self.assertIn("site-exact.css", content)
        self.assertIn("v3-fixes.css", content)
        self.assertIn("data-employee-rows", content)
        self.assertIn("module-stat-grid", content)
        self.assertIn('data-metric="assignments"', content)
        self.assertIn("data-employee-dialog", content)
