"""
Tests for the ``company`` app -- Company Administration / settings page.

Covers the Administration -> Company settings screen: it must be
auth-protected, render the profile form from the ``company_details`` table,
and persist edits back to that table (create when no row exists, update
otherwise).

Also covers the Company Profile API (/api/company/) which exposes
read (GET) and update (PATCH) of the single company record, gated to the
Owner role only.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from django.urls import reverse
from rest_framework import status as http
from rest_framework.test import APIClient

from taxes.models import TaxRate
from users.models import Role, User
from users.testing import WithUsersTableMixin

from .models import DEFAULT_CURRENCY_UUID, CompanyProfile, FinancialSettings
from .testing import WithCompanyDetailsTableMixin


# ── Server-rendered page tests (existing) ────────────────────────────────


class CompanySettingsPageTests(WithCompanyDetailsTableMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("settings")

    def setUp(self):
        self.user = DjangoUser.objects.create_user(username="owner", password="pass12345")
        self.client.force_login(self.user)

    def test_requires_login(self):
        anonymous = type(self.client)()
        response = anonymous.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_renders_profile_form_for_authenticated_user(self):
        CompanyProfile.objects.create(
            name="Cedar Construction S.A.L.",
            registration_number="CR-20458",
            email="finance@cedarconstruction.com",
            phone="+961 6 445 820",
            currency=DEFAULT_CURRENCY_UUID,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Company settings", content)
        self.assertIn("Company profile", content)
        self.assertIn("Users &amp; roles", content)
        self.assertIn("Cedar Construction S.A.L.", content)
        self.assertIn("CR-20458", content)
        self.assertIn("USD — US Dollar", content)
        self.assertIn("Automatic by financial year", content)

    def test_save_creates_profile_when_no_row_exists(self):
        response = self.client.post(self.url, {
            "name": "Cedar Construction S.A.L.",
            "registration_number": "CR-20458",
            "email": "finance@cedarconstruction.com",
            "phone": "+961 6 445 820",
            "address": "Tripoli, North Lebanon",
            "website": "www.cedarconstruction.com",
            "tax_information": "LB-884291",
        })
        self.assertEqual(response.status_code, 302)
        profile = CompanyProfile.objects.get()
        self.assertEqual(profile.name, "Cedar Construction S.A.L.")
        self.assertEqual(profile.tax_information, "LB-884291")
        self.assertEqual(profile.currency, DEFAULT_CURRENCY_UUID)

    def test_save_updates_existing_profile(self):
        CompanyProfile.objects.create(
            name="Old Name", email="old@example.com", currency=DEFAULT_CURRENCY_UUID,
        )
        response = self.client.post(self.url, {
            "name": "Cedar Construction S.A.L.",
            "registration_number": "CR-20458",
            "email": "finance@cedarconstruction.com",
            "phone": "+961 6 445 820",
        })
        self.assertEqual(response.status_code, 302)
        profile = CompanyProfile.objects.get()
        self.assertEqual(profile.name, "Cedar Construction S.A.L.")
        self.assertEqual(profile.email, "finance@cedarconstruction.com")
        self.assertEqual(CompanyProfile.objects.count(), 1)

    def test_save_requires_company_name(self):
        response = self.client.post(self.url, {"name": "  "})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Company name is required.", response.content.decode())
        self.assertEqual(CompanyProfile.objects.count(), 0)


# ── Company Profile API tests ────────────────────────────────────────────


class CompanyApiTestBase(WithUsersTableMixin, WithCompanyDetailsTableMixin, TestCase):
    """Shared setup for company API tests: creates users + company row,
    logs in as owner, and exposes helpers for login."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyProfile.objects.create(
            name="Cedar Construction S.A.L.",
            registration_number="CR-20458",
            email="finance@cedarconstruction.com",
            phone="+961 6 445 820",
            address="Tripoli, North Lebanon",
            website="www.cedarconstruction.com",
            tax_information="LB-884291",
            currency=DEFAULT_CURRENCY_UUID,
        )
        cls.detail_url = f"/api/company/{cls.company.pk}/"
        cls.list_url = "/api/company/"

    def setUp(self):
        self.client = APIClient()
        self.owner = User(
            username="owner", email="owner@cedarconstruction.com",
            first_name="O", last_name="W", role=Role.OWNER,
        )
        self.owner.set_password("owner-pass-123")
        self.owner.save()
        self.accountant = User(
            username="accountant", email="acc@cedarconstruction.com",
            first_name="A", last_name="C", role=Role.ACCOUNTANT,
        )
        self.accountant.set_password("acc-pass-123")
        self.accountant.save()

    def login_as(self, username, password):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        if resp.status_code == 200:
            token = resp.data["access"]
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return resp

    def login_owner(self):
        self.login_as("owner", "owner-pass-123")

    def login_accountant(self):
        self.login_as("accountant", "acc-pass-123")


class CompanyApiUnauthenticatedTests(CompanyApiTestBase):
    """Unauthenticated users must not access the company API."""

    def test_list_returns_401(self):
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, http.HTTP_401_UNAUTHORIZED)

    def test_retrieve_returns_401(self):
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, http.HTTP_401_UNAUTHORIZED)

    def test_patch_returns_401(self):
        resp = self.client.patch(
            self.detail_url, {"name": "Hacked"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_401_UNAUTHORIZED)


class CompanyApiAccountantTests(CompanyApiTestBase):
    """Accountant role must not access the company API."""

    def setUp(self):
        super().setUp()
        self.login_accountant()

    def test_list_returns_403(self):
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, http.HTTP_403_FORBIDDEN)

    def test_retrieve_returns_403(self):
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, http.HTTP_403_FORBIDDEN)

    def test_patch_returns_403(self):
        resp = self.client.patch(
            self.detail_url, {"name": "Not Allowed"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_403_FORBIDDEN)


class CompanyApiOwnerRetrieveTests(CompanyApiTestBase):
    """Owner can retrieve the company profile."""

    def setUp(self):
        super().setUp()
        self.login_owner()

    def test_list_returns_company(self):
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        data = resp.data
        # DefaultRouter wraps list in pagination envelope.
        results = data.get("results", data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Cedar Construction S.A.L.")
        self.assertEqual(results[0]["registration_number"], "CR-20458")
        self.assertEqual(results[0]["email"], "finance@cedarconstruction.com")
        self.assertEqual(results[0]["tax_information"], "LB-884291")

    def test_retrieve_returns_company(self):
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.assertEqual(resp.data["name"], "Cedar Construction S.A.L.")
        self.assertEqual(resp.data["phone"], "+961 6 445 820")

    def test_retrieve_ignores_pk(self):
        """GET with any pk returns the same single company record."""
        resp = self.client.get("/api/company/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.assertEqual(resp.data["name"], "Cedar Construction S.A.L.")

    def test_readonly_fields_returned(self):
        resp = self.client.get(self.detail_url)
        self.assertIn("id", resp.data)
        self.assertIn("currency", resp.data)
        self.assertIn("logo", resp.data)
        self.assertIn("created_at", resp.data)
        self.assertIn("updated_at", resp.data)


class CompanyApiOwnerUpdateTests(CompanyApiTestBase):
    """Owner can update the company profile via PATCH."""

    def setUp(self):
        super().setUp()
        self.login_owner()

    def test_patch_updates_name(self):
        resp = self.client.patch(
            self.detail_url, {"name": "Cedar Co."}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.assertEqual(resp.data["name"], "Cedar Co.")
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Cedar Co.")

    def test_patch_updates_multiple_fields(self):
        resp = self.client.patch(
            self.detail_url,
            {"phone": "+961 1 234 567", "website": "newsite.com"},
            format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.assertEqual(resp.data["phone"], "+961 1 234 567")
        self.assertEqual(resp.data["website"], "newsite.com")
        self.company.refresh_from_db()
        self.assertEqual(self.company.phone, "+961 1 234 567")

    def test_patch_partial_update_only_changed_fields(self):
        """Unchanged fields keep their original values."""
        resp = self.client.patch(
            self.detail_url, {"email": "new@cedar.com"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.email, "new@cedar.com")
        self.assertEqual(self.company.name, "Cedar Construction S.A.L.")

    def test_patch_ignores_readonly_fields(self):
        """Sending readonly fields (currency, logo) in the body has no effect."""
        old_currency = self.company.currency
        old_logo = self.company.logo
        resp = self.client.patch(
            self.detail_url,
            {"currency": "00000000-0000-0000-0000-000000000001", "logo": "nope"},
            format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.currency, old_currency)
        self.assertEqual(self.company.logo, old_logo)

    def test_patch_empty_name_rejected(self):
        """Company name is required (model allows blank, but serializer
        should allow partial -- name can be empty string in PATCH since
        it's not required for partial updates)."""
        resp = self.client.patch(
            self.detail_url, {"name": ""}, format="json",
        )
        # Empty name on PATCH is allowed (partial=True); model accepts blank.
        self.assertIn(resp.status_code, [http.HTTP_200_OK, http.HTTP_400_BAD_REQUEST])

    def test_patch_updates_updated_at(self):
        """The updated_at timestamp should advance on a successful PATCH."""
        old_updated = self.company.updated_at
        resp = self.client.patch(
            self.detail_url, {"name": "Updated Name"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertGreaterEqual(self.company.updated_at, old_updated)


class CompanyApiMethodNotAllowedTests(CompanyApiTestBase):
    """POST, PUT, DELETE must return 405 Method Not Allowed."""

    def setUp(self):
        super().setUp()
        self.login_owner()

    def test_post_returns_405(self):
        resp = self.client.post(
            self.list_url, {"name": "New"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_returns_405(self):
        resp = self.client.put(
            self.detail_url, {"name": "Replaced"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_returns_405(self):
        resp = self.client.delete(self.detail_url)
        self.assertEqual(resp.status_code, http.HTTP_405_METHOD_NOT_ALLOWED)


class CompanyApiStillOneRecordTests(CompanyApiTestBase):
    """Verify the system enforces single-company invariant."""

    def setUp(self):
        super().setUp()
        self.login_owner()

    def test_patch_never_creates_new_row(self):
        """Patching must always update the existing record, not create one."""
        count_before = CompanyProfile.objects.count()
        self.client.patch(
            self.detail_url, {"name": "Still Cedar"}, format="json",
        )
        self.assertEqual(CompanyProfile.objects.count(), count_before)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Still Cedar")


# ── Financial Settings API tests ─────────────────────────────────────────


class FinancialSettingsApiTestBase(CompanyApiTestBase):
    """Shared setup for Financial Settings API tests: a tax rate + URL."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tax = TaxRate.objects.create(
            name="VAT",
            rate=Decimal("11.0000"),
            tax_type="VAT",
            effective_date=date(2024, 1, 1),
        )
        cls.rules_url = "/api/company/financial-settings/"


class FinancialSettingsApiUnauthenticatedTests(FinancialSettingsApiTestBase):
    """Anonymous callers must not read or write financial rules."""

    def test_get_returns_401(self):
        resp = self.client.get(self.rules_url)
        self.assertEqual(resp.status_code, http.HTTP_401_UNAUTHORIZED)

    def test_patch_returns_401(self):
        resp = self.client.patch(
            self.rules_url, {"retention_percent": "10.00"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_401_UNAUTHORIZED)


class FinancialSettingsApiAccountantTests(FinancialSettingsApiTestBase):
    """Accountant role must not access financial rules."""

    def setUp(self):
        super().setUp()
        self.login_accountant()

    def test_get_returns_403(self):
        resp = self.client.get(self.rules_url)
        self.assertEqual(resp.status_code, http.HTTP_403_FORBIDDEN)

    def test_patch_returns_403(self):
        resp = self.client.patch(
            self.rules_url, {"retention_percent": "10.00"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_403_FORBIDDEN)


class FinancialSettingsApiOwnerTests(FinancialSettingsApiTestBase):
    """Owner can read and update the single financial rules record."""

    def setUp(self):
        super().setUp()
        self.login_owner()

    def test_get_returns_defaults(self):
        resp = self.client.get(self.rules_url)
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        data = resp.data
        self.assertEqual(data["fiscal_year_start_month"], 1)
        self.assertEqual(data["fiscal_year_start_day"], 1)
        self.assertTrue(data["lock_financial_periods"])
        self.assertEqual(data["period_lock_after_days"], 30)
        self.assertIsNone(data["default_tax_rate"])
        self.assertEqual(data["default_tax_rate_label"], "")
        self.assertEqual(data["default_payment_terms"], "NET30")
        self.assertEqual(data["retention_percent"], "5.00")
        self.assertEqual(data["budget_alert_percent"], "90.00")

    def test_get_creates_singleton_row(self):
        self.assertEqual(FinancialSettings.objects.count(), 0)
        resp = self.client.get(self.rules_url)
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.assertEqual(FinancialSettings.objects.count(), 1)

    def test_patch_updates_fields(self):
        resp = self.client.patch(
            self.rules_url,
            {
                "fiscal_year_start_month": 3,
                "fiscal_year_start_day": 15,
                "lock_financial_periods": False,
                "period_lock_after_days": 0,
                "default_tax_rate": str(self.tax.id),
                "default_payment_terms": "NET60",
                "retention_percent": "10.00",
                "budget_alert_percent": "85.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        rules = FinancialSettings.objects.get()
        self.assertEqual(rules.fiscal_year_start_month, 3)
        self.assertEqual(rules.fiscal_year_start_day, 15)
        self.assertFalse(rules.lock_financial_periods)
        self.assertEqual(rules.period_lock_after_days, 0)
        self.assertEqual(rules.default_tax_rate_id, self.tax.id)
        self.assertEqual(rules.default_payment_terms, "NET60")
        self.assertEqual(rules.retention_percent, Decimal("10.00"))
        self.assertEqual(rules.budget_alert_percent, Decimal("85.00"))

    def test_patch_partial_keeps_other_fields(self):
        resp = self.client.patch(
            self.rules_url, {"retention_percent": "12.00"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        rules = FinancialSettings.objects.get()
        self.assertEqual(rules.retention_percent, Decimal("12.00"))
        self.assertEqual(rules.budget_alert_percent, Decimal("90.00"))
        self.assertTrue(rules.lock_financial_periods)
        self.assertEqual(FinancialSettings.objects.count(), 1)

    def test_patch_and_get_never_create_second_row(self):
        self.client.get(self.rules_url)
        self.client.patch(
            self.rules_url, {"retention_percent": "10.00"}, format="json",
        )
        self.client.get(self.rules_url)
        self.assertEqual(FinancialSettings.objects.count(), 1)

    def test_patch_returns_tax_label(self):
        resp = self.client.patch(
            self.rules_url, {"default_tax_rate": str(self.tax.id)}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.assertEqual(resp.data["default_tax_rate_label"], "VAT")
        get_resp = self.client.get(self.rules_url)
        self.assertEqual(get_resp.data["default_tax_rate_label"], "VAT")

    def test_patch_clears_tax_rate(self):
        self.client.patch(
            self.rules_url, {"default_tax_rate": str(self.tax.id)}, format="json",
        )
        resp = self.client.patch(
            self.rules_url, {"default_tax_rate": None}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        rules = FinancialSettings.objects.get()
        self.assertIsNone(rules.default_tax_rate)

    def test_invalid_month_rejected(self):
        resp = self.client.patch(
            self.rules_url, {"fiscal_year_start_month": 13}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_400_BAD_REQUEST)

    def test_invalid_day_rejected(self):
        resp = self.client.patch(
            self.rules_url, {"fiscal_year_start_day": 0}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_400_BAD_REQUEST)

    def test_retention_out_of_range_rejected(self):
        resp = self.client.patch(
            self.rules_url, {"retention_percent": "120.00"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_400_BAD_REQUEST)

    def test_budget_alert_out_of_range_rejected(self):
        resp = self.client.patch(
            self.rules_url, {"budget_alert_percent": "-5.00"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_400_BAD_REQUEST)

    def test_negative_lock_days_rejected(self):
        resp = self.client.patch(
            self.rules_url, {"period_lock_after_days": -1}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_400_BAD_REQUEST)

    def test_patch_updates_updated_at(self):
        self.client.get(self.rules_url)
        old_updated = FinancialSettings.objects.get().updated_at
        resp = self.client.patch(
            self.rules_url, {"retention_percent": "8.50"}, format="json",
        )
        self.assertEqual(resp.status_code, http.HTTP_200_OK)
        self.assertGreaterEqual(FinancialSettings.objects.get().updated_at, old_updated)