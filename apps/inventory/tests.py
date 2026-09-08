"""
Tests for the ``inventory`` app -- Material Management (CPMAS-28) and
Inventory & Warehouse Management (CPMAS-29).

Organized into:
- Model-level tests: constraints (unique SKU/category name, unique
  warehouse+material stock row) and on_delete behavior (PROTECT/
  SET_NULL), run directly against the ORM.
- Service tests: apply_stock_movement, the single function allowed to
  change Stock.quantity (BR 12.6).
- API tests: authentication enforcement, computed fields, filtering,
  the low_stock and transfer actions, and ledger immutability on
  StockMovement -- exercised through the real DRF endpoints, not just
  the underlying Python functions, so a regression in urls.py/views.py
  wiring would be caught too.
"""
from decimal import Decimal

from django.contrib.auth.models import User as DjangoUser
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from suppliers.models import Supplier
from taxes.models import TaxRate
from users.models import User
from users.testing import WithUsersTableMixin

from .models import Material, MaterialCategory, Stock, StockMovement, Warehouse
from .services import apply_stock_movement


class MaterialModelTests(TestCase):
    def setUp(self):
        self.category = MaterialCategory.objects.create(name="Cement")

    def test_sku_must_be_unique(self):
        Material.objects.create(category=self.category, name="A", sku="DUP-1", unit="bag")
        with self.assertRaises(Exception):
            Material.objects.create(category=self.category, name="B", sku="DUP-1", unit="bag")

    def test_category_name_must_be_unique(self):
        with self.assertRaises(Exception):
            MaterialCategory.objects.create(name="Cement")

    def test_category_delete_is_protected_while_materials_reference_it(self):
        Material.objects.create(category=self.category, name="A", sku="SKU-1", unit="bag")
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_tax_rate_deletion_sets_material_tax_rate_to_null(self):
        tax = TaxRate.objects.create(name="VAT", rate=Decimal("15"), tax_type="VAT", effective_date="2026-01-01")
        material = Material.objects.create(category=self.category, name="A", sku="SKU-2", unit="bag", tax_rate=tax)
        tax.delete()
        material.refresh_from_db()
        self.assertIsNone(material.tax_rate)

    def test_default_supplier_deletion_sets_material_supplier_to_null(self):
        supplier = Supplier.objects.create(name="ACME")
        material = Material.objects.create(category=self.category, name="A", sku="SKU-3", unit="bag", default_supplier=supplier)
        supplier.delete()
        material.refresh_from_db()
        self.assertIsNone(material.default_supplier)


class StockModelTests(TestCase):
    def setUp(self):
        category = MaterialCategory.objects.create(name="Steel")
        self.material = Material.objects.create(category=category, name="Rebar", sku="REBAR-1", unit="ton")
        self.warehouse = Warehouse.objects.create(name="Main Warehouse")

    def test_one_stock_row_per_warehouse_and_material(self):
        Stock.objects.create(warehouse=self.warehouse, material=self.material, quantity=Decimal("10"))
        with self.assertRaises(Exception):
            Stock.objects.create(warehouse=self.warehouse, material=self.material, quantity=Decimal("5"))

    def test_same_material_can_have_stock_in_multiple_warehouses(self):
        # Regression guard for the false-alarm "one warehouse per material"
        # bug briefly suspected during CPMAS-29 development (see the Stock
        # model's docstring) -- the live schema always supported this.
        other_warehouse = Warehouse.objects.create(name="Site B")
        Stock.objects.create(warehouse=self.warehouse, material=self.material, quantity=Decimal("10"))
        Stock.objects.create(warehouse=other_warehouse, material=self.material, quantity=Decimal("5"))
        self.assertEqual(Stock.objects.filter(material=self.material).count(), 2)


class ApplyStockMovementServiceTests(WithUsersTableMixin, TestCase):
    """
    Tests for inventory.services.apply_stock_movement -- the sole code
    path allowed to change Stock.quantity (BR 12.6).
    """

    def setUp(self):
        category = MaterialCategory.objects.create(name="Cement")
        self.material = Material.objects.create(category=category, name="Portland Cement", sku="CEM-1", unit="bag")
        self.warehouse = Warehouse.objects.create(name="Main Warehouse")
        self.user = User.objects.create(
            username="mover", email="mover@example.com", password_hash="x",
            first_name="M", last_name="V", role="owner",
        )

    def _movement(self, quantity, movement_type=StockMovement.MovementType.IN):
        movement = StockMovement(
            material=self.material, warehouse=self.warehouse, quantity=quantity,
            movement_type=movement_type, user=self.user,
        )
        movement.save()
        return movement

    def test_first_in_movement_creates_stock_row(self):
        apply_stock_movement(self._movement(Decimal("100")))
        stock = Stock.objects.get(warehouse=self.warehouse, material=self.material)
        self.assertEqual(stock.quantity, Decimal("100"))

    def test_out_movement_decreases_existing_stock(self):
        apply_stock_movement(self._movement(Decimal("100")))
        apply_stock_movement(self._movement(Decimal("-30"), StockMovement.MovementType.OUT))
        stock = Stock.objects.get(warehouse=self.warehouse, material=self.material)
        self.assertEqual(stock.quantity, Decimal("70"))

    def test_multiple_movements_accumulate_correctly(self):
        apply_stock_movement(self._movement(Decimal("50")))
        apply_stock_movement(self._movement(Decimal("25")))
        apply_stock_movement(self._movement(Decimal("-10"), StockMovement.MovementType.OUT))
        stock = Stock.objects.get(warehouse=self.warehouse, material=self.material)
        self.assertEqual(stock.quantity, Decimal("65"))


class InventoryAPITests(WithUsersTableMixin, TestCase):
    def setUp(self):
        self.category = MaterialCategory.objects.create(name="Cement")
        self.material = Material.objects.create(
            category=self.category, name="Portland Cement", sku="CEM-API-1", unit="bag",
            minimum_stock_level=Decimal("50"),
        )
        self.warehouse_a = Warehouse.objects.create(name="Warehouse A")
        self.warehouse_b = Warehouse.objects.create(name="Warehouse B")
        self.movement_user = User.objects.create(
            username="apimover", email="apimover@example.com", password_hash="x",
            first_name="A", last_name="M", role="owner",
        )

        self.django_user = DjangoUser.objects.create_user(username="apitester", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=self.django_user)

    def test_anonymous_request_is_rejected(self):
        anon = APIClient()
        response = anon.get("/api/inventory/materials/")
        # 401 (not 403): with the auth ticket in place, unauthenticated
        # requests are challenged to authenticate before access is denied.
        self.assertEqual(response.status_code, 401)

    def test_material_list_is_reachable_when_authenticated(self):
        response = self.client.get("/api/inventory/materials/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_material_search_by_name(self):
        response = self.client.get("/api/inventory/materials/?search=Portland")
        self.assertEqual(response.json()["count"], 1)
        response = self.client.get("/api/inventory/materials/?search=Nonexistent")
        self.assertEqual(response.json()["count"], 0)

    def test_filter_by_supplier(self):
        supplier = Supplier.objects.create(name="ACME Building Supplies")
        Material.objects.create(category=self.category, name="Rebar", sku="REBAR-API-1", unit="ton", default_supplier=supplier)

        response = self.client.get(f"/api/inventory/materials/?supplier={supplier.id}")
        skus = [m["sku"] for m in response.json()["results"]]
        self.assertEqual(skus, ["REBAR-API-1"])

    def test_material_duplicate_sku_rejected_via_api(self):
        response = self.client.post("/api/inventory/materials/", {
            "category": str(self.category.id), "name": "Dup", "sku": "CEM-API-1", "unit": "bag",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_stocks_endpoint_is_read_only(self):
        response = self.client.post("/api/inventory/stocks/", {
            "warehouse": str(self.warehouse_a.id), "material": str(self.material.id), "quantity": "9999",
        }, format="json")
        self.assertEqual(response.status_code, 405)

    def test_stock_movement_create_updates_stock_via_api(self):
        response = self.client.post("/api/inventory/stock-movements/", {
            "material": str(self.material.id), "warehouse": str(self.warehouse_a.id),
            "quantity": "80", "movement_type": "IN", "user": str(self.movement_user.id),
        }, format="json")
        self.assertEqual(response.status_code, 201)

        stock_response = self.client.get(f"/api/inventory/stocks/?warehouse={self.warehouse_a.id}")
        self.assertEqual(stock_response.json()["results"][0]["quantity"], "80.000")

    def test_out_movement_with_positive_quantity_rejected(self):
        response = self.client.post("/api/inventory/stock-movements/", {
            "material": str(self.material.id), "warehouse": str(self.warehouse_a.id),
            "quantity": "10", "movement_type": "OUT", "user": str(self.movement_user.id),
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_stock_movement_is_immutable_after_creation(self):
        create_response = self.client.post("/api/inventory/stock-movements/", {
            "material": str(self.material.id), "warehouse": str(self.warehouse_a.id),
            "quantity": "10", "movement_type": "IN", "user": str(self.movement_user.id),
        }, format="json")
        movement_id = create_response.json()["id"]

        patch_response = self.client.patch(f"/api/inventory/stock-movements/{movement_id}/", {"notes": "edited"}, format="json")
        self.assertEqual(patch_response.status_code, 405)
        delete_response = self.client.delete(f"/api/inventory/stock-movements/{movement_id}/")
        self.assertEqual(delete_response.status_code, 405)

    def test_low_stock_action_finds_material_below_minimum(self):
        self.client.post("/api/inventory/stock-movements/", {
            "material": str(self.material.id), "warehouse": str(self.warehouse_a.id),
            "quantity": "10", "movement_type": "IN", "user": str(self.movement_user.id),
        }, format="json")  # below the 50 minimum set in setUp

        response = self.client.get("/api/inventory/stocks/low_stock/")
        skus = [row["material_sku"] for row in response.json()["results"]]
        self.assertIn("CEM-API-1", skus)

    def test_low_stock_action_excludes_material_at_or_above_minimum(self):
        self.client.post("/api/inventory/stock-movements/", {
            "material": str(self.material.id), "warehouse": str(self.warehouse_a.id),
            "quantity": "80", "movement_type": "IN", "user": str(self.movement_user.id),
        }, format="json")  # above the 50 minimum

        response = self.client.get("/api/inventory/stocks/low_stock/")
        skus = [row["material_sku"] for row in response.json()["results"]]
        self.assertNotIn("CEM-API-1", skus)

    def test_transfer_action_moves_stock_between_warehouses(self):
        self.client.post("/api/inventory/stock-movements/", {
            "material": str(self.material.id), "warehouse": str(self.warehouse_a.id),
            "quantity": "100", "movement_type": "IN", "user": str(self.movement_user.id),
        }, format="json")

        response = self.client.post("/api/inventory/stock-movements/transfer/", {
            "material": str(self.material.id), "from_warehouse": str(self.warehouse_a.id),
            "to_warehouse": str(self.warehouse_b.id), "quantity": "30",
            "user": str(self.movement_user.id),
        }, format="json")
        self.assertEqual(response.status_code, 201)

        stock_a = Stock.objects.get(warehouse=self.warehouse_a, material=self.material)
        stock_b = Stock.objects.get(warehouse=self.warehouse_b, material=self.material)
        self.assertEqual(stock_a.quantity, Decimal("70"))
        self.assertEqual(stock_b.quantity, Decimal("30"))

    def test_transfer_action_rejects_same_source_and_destination(self):
        response = self.client.post("/api/inventory/stock-movements/transfer/", {
            "material": str(self.material.id), "from_warehouse": str(self.warehouse_a.id),
            "to_warehouse": str(self.warehouse_a.id), "quantity": "10",
            "user": str(self.movement_user.id),
        }, format="json")
        self.assertEqual(response.status_code, 400)


class StockReadApiTests(WithUsersTableMixin, TestCase):
    """
    Read-contract tests for GET /api/inventory/stocks/ -- the exact
    queries inventory.js sends for the Inventory page (1B-1): warehouse
    filter, material filter, free-text search across material name/SKU
    and warehouse name, the quantity/minimum/is_low_stock fields that
    drive the table and metrics, the PageNumberPagination contract, the
    warehouses endpoint behind the store dropdown, and the
    movement_type + date-range filters used for the "transfers today"
    tile (distinct references among today's TRANSFER rows).
    """

    def setUp(self):
        self.category = MaterialCategory.objects.create(name="Cement")
        self.material = Material.objects.create(
            category=self.category, name="Portland Cement", sku="CEM-READ-1", unit="bag",
            minimum_stock_level=Decimal("50"),
        )
        self.warehouse_a = Warehouse.objects.create(name="Warehouse A")
        self.warehouse_b = Warehouse.objects.create(name="Warehouse B")
        self.movement_user = User.objects.create(
            username="readmover", email="readmover@example.com", password_hash="x",
            first_name="R", last_name="M", role="owner",
        )
        self.django_user = DjangoUser.objects.create_user(username="readtester", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=self.django_user)

    def _post_movement(self, material, warehouse, quantity, movement_type="IN",
                       movement_date=None, reference=None):
        payload = {
            "material": str(material.id), "warehouse": str(warehouse.id),
            "quantity": quantity, "movement_type": movement_type,
            "user": str(self.movement_user.id),
        }
        if movement_date:
            payload["movement_date"] = movement_date
        if reference:
            payload["reference"] = reference
        return self.client.post("/api/inventory/stock-movements/", payload, format="json")

    def test_stocks_list_filtered_by_warehouse(self):
        self._post_movement(self.material, self.warehouse_a, "100")
        self._post_movement(self.material, self.warehouse_b, "50")

        response = self.client.get(f"/api/inventory/stocks/?warehouse={self.warehouse_a.id}")
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["warehouse_name"], "Warehouse A")

    def test_stocks_list_filtered_by_material(self):
        other = Material.objects.create(
            category=self.category, name="Rebar", sku="REBAR-READ-1", unit="ton",
        )
        self._post_movement(self.material, self.warehouse_a, "100")
        self._post_movement(other, self.warehouse_a, "50")

        response = self.client.get(f"/api/inventory/stocks/?material={other.id}")
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["material_sku"], "REBAR-READ-1")

    def test_stocks_search_matches_material_name_sku_and_warehouse(self):
        self._post_movement(self.material, self.warehouse_a, "100")
        site = Warehouse.objects.create(name="Site Alpha")
        self._post_movement(self.material, site, "50")

        self.assertEqual(self.client.get("/api/inventory/stocks/?search=Portland").json()["count"], 2)
        self.assertEqual(self.client.get("/api/inventory/stocks/?search=CEM-READ-1").json()["count"], 2)
        self.assertEqual(self.client.get("/api/inventory/stocks/?search=Alpha").json()["count"], 1)
        self.assertEqual(self.client.get("/api/inventory/stocks/?search=Bogus").json()["count"], 0)

    def test_stocks_list_includes_quantity_minimum_and_is_low_stock_flag(self):
        self._post_movement(self.material, self.warehouse_a, "10")  # below the 50 minimum

        row = self.client.get("/api/inventory/stocks/").json()["results"][0]
        self.assertEqual(row["quantity"], "10.000")
        self.assertEqual(row["minimum_stock_level"], "50.000")
        self.assertIs(row["is_low_stock"], True)
        self.assertEqual(row["material_name"], "Portland Cement")
        self.assertEqual(row["material_sku"], "CEM-READ-1")
        self.assertEqual(row["warehouse_name"], "Warehouse A")

    def test_stocks_pagination_contract_25_per_page(self):
        for i in range(26):
            warehouse = Warehouse.objects.create(name=f"Bulk Warehouse {i:02d}")
            Stock.objects.create(warehouse=warehouse, material=self.material, quantity=Decimal("1"))

        first = self.client.get("/api/inventory/stocks/")
        body = first.json()
        self.assertEqual(body["count"], 26)
        self.assertEqual(len(body["results"]), 25)
        self.assertIsNotNone(body["next"])
        self.assertIsNone(body["previous"])
        self.assertIn("page=2", body["next"])

        second = self.client.get("/api/inventory/stocks/?page=2")
        body2 = second.json()
        self.assertEqual(len(body2["results"]), 1)
        self.assertIsNone(body2["next"])
        self.assertIsNotNone(body2["previous"])

    def test_movements_filter_by_movement_type_and_date_range(self):
        # USE_TZ=False: movement dates and the ?date_from=/?date_to= query
        # values are naive local datetimes (no "Z" suffix -- aware values
        # make the SQLite comparison raise).
        self._post_movement(self.material, self.warehouse_a, "100",
                            movement_type="IN", movement_date="2026-09-01T10:00:00")
        self._post_movement(self.material, self.warehouse_a, "-30",
                            movement_type="TRANSFER", movement_date="2026-09-03T12:00:00",
                            reference="transfer-abc")
        self._post_movement(self.material, self.warehouse_b, "30",
                            movement_type="TRANSFER", movement_date="2026-09-03T12:00:00",
                            reference="transfer-abc")
        self._post_movement(self.material, self.warehouse_b, "20",
                            movement_type="IN", movement_date="2026-09-05T09:00:00")

        # The tile-4 query: today's TRANSFER rows (its 2 legs) -- the JS
        # counts distinct references from these rows, i.e. 1 operation.
        day3 = "date_from=2026-09-03T00:00:00&date_to=2026-09-03T23:59:59.999999"
        transfers = self.client.get(f"/api/inventory/stock-movements/?movement_type=TRANSFER&{day3}")
        body = transfers.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual({m["reference"] for m in body["results"]}, {"transfer-abc"})

        # The same day without a type filter excludes the other days.
        all_day3 = self.client.get(f"/api/inventory/stock-movements/?{day3}").json()
        self.assertEqual(all_day3["count"], 2)

        day1 = "date_from=2026-09-01T00:00:00&date_to=2026-09-01T23:59:59.999999"
        all_day1 = self.client.get(f"/api/inventory/stock-movements/?{day1}").json()
        self.assertEqual(all_day1["count"], 1)

    def test_warehouses_list_is_reachable(self):
        response = self.client.get("/api/inventory/warehouses/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual({w["name"] for w in body["results"]}, {"Warehouse A", "Warehouse B"})


class StockMovementWorkflowApiTests(WithUsersTableMixin, TestCase):
    """
    Write-contract tests for the 1B-2 movement workflows: the exact signed-
    quantity and validation rules inventory.js relies on when posting
    IN/OUT/RETURN/ADJUSTMENT to the append-only ledger and TRANSFER to the
    transfer action, plus the composite material+warehouse history query
    behind the per-row "Movements" dialog.

    Covers the contract points the earlier test classes leave untested:
    IN/RETURN sign enforcement, ADJUSTMENT in both directions, the required
    `user`, the default movement_date, transfer input validation, the
    paired-ledger-row transfer response, and the material+warehouse
    composite history filter.
    """

    def setUp(self):
        self.category = MaterialCategory.objects.create(name="Cement")
        self.material = Material.objects.create(
            category=self.category, name="Portland Cement", sku="CEM-WORK-1", unit="bag",
            minimum_stock_level=Decimal("50"),
        )
        self.warehouse_a = Warehouse.objects.create(name="Warehouse A")
        self.warehouse_b = Warehouse.objects.create(name="Warehouse B")
        self.movement_user = User.objects.create(
            username="workmover", email="workmover@example.com", password_hash="x",
            first_name="W", last_name="M", role="owner",
        )
        self.django_user = DjangoUser.objects.create_user(username="worktester", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(user=self.django_user)

    def _post_movement(self, quantity, movement_type, warehouse=None, user=None,
                       movement_date=None, reference=None):
        payload = {
            "material": str(self.material.id),
            "warehouse": str((warehouse or self.warehouse_a).id),
            "quantity": quantity, "movement_type": movement_type,
            "user": str((user or self.movement_user).id),
        }
        if movement_date:
            payload["movement_date"] = movement_date
        if reference:
            payload["reference"] = reference
        return self.client.post("/api/inventory/stock-movements/", payload, format="json")

    def test_in_movement_with_negative_quantity_rejected(self):
        response = self._post_movement("-10", "IN")
        self.assertEqual(response.status_code, 400)

    def test_return_movement_with_positive_quantity_updates_stock(self):
        response = self._post_movement("5", "RETURN")
        self.assertEqual(response.status_code, 201)
        stock = Stock.objects.get(warehouse=self.warehouse_a, material=self.material)
        self.assertEqual(stock.quantity, Decimal("5"))

    def test_return_movement_with_negative_quantity_rejected(self):
        response = self._post_movement("-5", "RETURN")
        self.assertEqual(response.status_code, 400)

    def test_adjustment_with_positive_quantity_increases_stock(self):
        response = self._post_movement("40", "ADJUSTMENT")
        self.assertEqual(response.status_code, 201)
        stock = Stock.objects.get(warehouse=self.warehouse_a, material=self.material)
        self.assertEqual(stock.quantity, Decimal("40"))

    def test_adjustment_with_negative_quantity_decreases_stock(self):
        self._post_movement("100", "IN")
        response = self._post_movement("-30", "ADJUSTMENT")
        self.assertEqual(response.status_code, 201)
        stock = Stock.objects.get(warehouse=self.warehouse_a, material=self.material)
        self.assertEqual(stock.quantity, Decimal("70"))

    def test_movement_creation_requires_user(self):
        payload = {
            "material": str(self.material.id), "warehouse": str(self.warehouse_a.id),
            "quantity": "10", "movement_type": "IN",
        }
        response = self.client.post("/api/inventory/stock-movements/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_movement_creation_defaults_movement_date_to_now(self):
        # USE_TZ=False: the ledger stores naive local datetimes; omitting
        # movement_date falls back to timezone.now() on the model.
        response = self._post_movement("10", "IN")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["movement_date"])

    def test_movement_history_filter_by_material_and_warehouse(self):
        # The per-row "Movements" dialog queries a composite
        # ?material=<id>&warehouse=<id>.
        self._post_movement("100", "IN", movement_date="2026-09-01T08:00:00")
        self._post_movement("-30", "OUT", movement_date="2026-09-02T08:00:00")
        self._post_movement("20", "IN", warehouse=self.warehouse_b,
                            movement_date="2026-09-03T08:00:00")

        params = f"material={self.material.id}&warehouse={self.warehouse_a.id}"
        body = self.client.get(f"/api/inventory/stock-movements/?{params}").json()
        self.assertEqual(body["count"], 2)
        self.assertEqual({m["quantity"] for m in body["results"]}, {"100.000", "-30.000"})
        for movement in body["results"]:
            self.assertEqual(movement["material_name"], "Portland Cement")
            self.assertEqual(movement["warehouse_name"], "Warehouse A")

        other = self.client.get(
            f"/api/inventory/stock-movements/?material={self.material.id}&warehouse={self.warehouse_b.id}"
        ).json()
        self.assertEqual(other["count"], 1)

    def test_transfer_missing_required_fields_rejected(self):
        response = self.client.post("/api/inventory/stock-movements/transfer/", {
            "material": str(self.material.id),
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing required field(s)", response.json()["detail"])

    def test_transfer_non_positive_quantity_rejected(self):
        for quantity in ("0", "-5"):
            response = self.client.post("/api/inventory/stock-movements/transfer/", {
                "material": str(self.material.id),
                "from_warehouse": str(self.warehouse_a.id),
                "to_warehouse": str(self.warehouse_b.id),
                "quantity": quantity, "user": str(self.movement_user.id),
            }, format="json")
            self.assertEqual(response.status_code, 400)

    def test_transfer_invalid_source_and_destination_rejected(self):
        response = self.client.post("/api/inventory/stock-movements/transfer/", {
            "material": str(self.material.id),
            "from_warehouse": str(self.warehouse_a.id),
            "to_warehouse": str(self.warehouse_a.id),
            "quantity": "10", "user": str(self.movement_user.id),
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("must differ", response.json()["detail"])

    def test_transfer_returns_paired_ledger_rows_sharing_reference(self):
        self._post_movement("100", "IN")
        response = self.client.post("/api/inventory/stock-movements/transfer/", {
            "material": str(self.material.id),
            "from_warehouse": str(self.warehouse_a.id),
            "to_warehouse": str(self.warehouse_b.id),
            "quantity": "30", "user": str(self.movement_user.id),
        }, format="json")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["out"]["movement_type"], "TRANSFER")
        self.assertEqual(body["in"]["movement_type"], "TRANSFER")
        self.assertEqual(body["out"]["quantity"], "-30.000")
        self.assertEqual(body["in"]["quantity"], "30.000")
        self.assertTrue(body["out"]["reference"])
        self.assertEqual(body["out"]["reference"], body["in"]["reference"])
