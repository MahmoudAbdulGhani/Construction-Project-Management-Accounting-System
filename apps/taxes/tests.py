"""
Tests for the ``taxes`` app (CPMAS-28: minimal TaxRate model + API).

Covers the schema-mandated shape of TaxRate (required fields, decimal
precision on ``rate``, default ordering) and the Tax Rates API: listing,
creation, edit, activate/deactivate, delete, and the Owner-vs-Accountant
permission split (Accountants can read rates, only Owners can edit).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from users.testing import WithUsersTableMixin

from .models import TaxRate


class TaxRateModelTests(TestCase):
    def test_create_with_required_fields(self):
        tax = TaxRate.objects.create(
            name="VAT 15%", rate=Decimal("15.0000"), tax_type="VAT",
            effective_date="2026-01-01",
        )
        self.assertTrue(tax.is_active)  # default=True per the schema
        self.assertEqual(str(tax), "VAT 15% (15.0000%)")

    def test_rate_precision_is_preserved(self):
        # DECIMAL(8,4) in the schema -- verify four decimal places survive
        # a round trip through the database, not just in memory.
        tax = TaxRate.objects.create(
            name="Fractional", rate=Decimal("7.2534"), tax_type="Sales Tax",
            effective_date="2026-01-01",
        )
        tax.refresh_from_db()
        self.assertEqual(tax.rate, Decimal("7.2534"))

    def test_default_ordering_is_name_then_effective_date_desc(self):
        old = TaxRate.objects.create(name="A", rate=Decimal("1"), tax_type="VAT", effective_date="2020-01-01")
        new = TaxRate.objects.create(name="A", rate=Decimal("2"), tax_type="VAT", effective_date="2026-01-01")
        other = TaxRate.objects.create(name="B", rate=Decimal("3"), tax_type="VAT", effective_date="2021-01-01")
        self.assertEqual(list(TaxRate.objects.all()), [new, old, other])


class TaxRateApiTests(WithUsersTableMixin, TestCase):
    """API tests for /api/taxes/tax-rates/ with DRF APIClient."""

    def setUp(self):
        self.client = APIClient()
        self.owner = TaxRateApiTests._make_user("owner", "OWNER")
        self.accountant = TaxRateApiTests._make_user("accountant", "ACCOUNTANT")

    @staticmethod
    def _make_user(username, role):
        from users.models import User as AppUser
        user = AppUser.objects.create(
            username=username, email=f"{username}@example.com",
            password_hash="x", first_name=username, last_name="T",
            role=role,
        )
        user.set_password("pass-1234")
        user.save(update_fields=["password_hash"])
        return user

    def _login(self, user):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "pass-1234"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        token = resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _tax(self, **overrides):
        data = {
            "name": "VAT", "rate": "15.0000", "tax_type": "Sales tax",
            "effective_date": "2026-01-01", "is_active": True,
        }
        data.update(overrides)
        return self.client.post("/api/taxes/tax-rates/", data, format="json")

    def test_anonymous_cannot_list_tax_rates(self):
        response = self.client.get("/api/taxes/tax-rates/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_owner_can_create_and_list_tax_rates(self):
        self._login(self.owner)
        created = self._tax()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        tax_id = created.data["id"]
        self.assertEqual(created.data["name"], "VAT")

        listing = self.client.get("/api/taxes/tax-rates/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        results = listing.data.get("results") or listing.data
        self.assertTrue(any(r["id"] == tax_id for r in results))

    def test_accountant_can_read_but_not_create(self):
        TaxRate.objects.create(
            name="VAT", rate=Decimal("15"), tax_type="Sales tax",
            effective_date="2026-01-01", is_active=True,
        )
        self._login(self.accountant)
        listing = self.client.get("/api/taxes/tax-rates/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)

        created = self._tax(name="Forbidden")
        self.assertIn(created.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_owner_can_update_tax_rate(self):
        self._login(self.owner)
        tax = TaxRate.objects.create(
            name="Old", rate=Decimal("5"), tax_type="VAT",
            effective_date="2026-01-01", is_active=True,
        )
        response = self.client.patch(
            f"/api/taxes/tax-rates/{tax.id}/",
            {"name": "New VAT", "rate": "18.2500"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tax.refresh_from_db()
        self.assertEqual(tax.name, "New VAT")
        self.assertEqual(tax.rate, Decimal("18.2500"))

    def test_owner_can_activate_and_deactivate(self):
        self._login(self.owner)
        tax = TaxRate.objects.create(
            name="Toggle", rate=Decimal("10"), tax_type="VAT",
            effective_date="2026-01-01", is_active=True,
        )
        deactiv = self.client.post(f"/api/taxes/tax-rates/{tax.id}/deactivate/")
        self.assertEqual(deactiv.status_code, status.HTTP_200_OK)
        tax.refresh_from_db()
        self.assertFalse(tax.is_active)

        activ = self.client.post(f"/api/taxes/tax-rates/{tax.id}/activate/")
        self.assertEqual(activ.status_code, status.HTTP_200_OK)
        tax.refresh_from_db()
        self.assertTrue(tax.is_active)

    def test_owner_can_delete_tax_rate(self):
        self._login(self.owner)
        tax = TaxRate.objects.create(
            name="Gone", rate=Decimal("7"), tax_type="VAT",
            effective_date="2026-01-01", is_active=True,
        )
        response = self.client.delete(f"/api/taxes/tax-rates/{tax.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TaxRate.objects.filter(id=tax.id).exists())

    def test_rate_cannot_be_negative(self):
        self._login(self.owner)
        response = self._tax(name="Bad", rate="-1")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
