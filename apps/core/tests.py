"""
Tests for the ``core`` app -- Receipts page and the ``app_user`` bridge
(CPMAS-58).

Organized into:
- Page tests: the new /receipts/ view renders for an authenticated
  session and redirects an anonymous one, same pattern as the existing
  Suppliers page.
- Context processor tests: construction.context_processors.app_user's
  three cases -- anonymous (no bridge), a matching users.User by
  username (bridged), and no matching row (degrades to None rather
  than erroring).
"""
from django.conf import settings
from django.contrib.auth.models import User as DjangoUser
from django.test import RequestFactory, TestCase

from construction.context_processors import app_user
from users.authentication import ACCESS_COOKIE, REFRESH_COOKIE
from users.models import User as AppUser
from users.testing import WithUsersTableMixin


class LoginPageTests(WithUsersTableMixin, TestCase):
    """End-to-end tests for the server-rendered login page + middleware."""

    def setUp(self):
        self.owner = AppUser.objects.create(
            username="owner", email="owner@example.com", password_hash="x",
            first_name="O", last_name="W", role="OWNER",
        )
        self.owner.set_password("owner-pass-123")
        self.owner.save(update_fields=["password_hash"])

    def test_login_page_renders(self):
        response = self.client.get("/accounts/login/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")
        self.assertContains(response, "Username")

    def test_successful_login_redirects_and_grants_access(self):
        # Dashboard is @login_required -> anonymous is redirected first.
        protected = self.client.get("/dashboard/")
        self.assertEqual(protected.status_code, 302)
        self.assertIn("/accounts/login/", protected.url)

        response = self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "owner-pass-123"},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

        # After login the @login_required dashboard is reachable.
        dashboard = self.client.get("/dashboard/")
        self.assertEqual(dashboard.status_code, 200)

    def test_invalid_login_shows_error_and_stays_logged_out(self):
        response = self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your username or password is incorrect.")
        # Still anonymous -> dashboard redirects to login.
        dashboard = self.client.get("/dashboard/")
        self.assertEqual(dashboard.status_code, 302)
        self.assertIn("/accounts/login/", dashboard.url)

    def test_logout_clears_session(self):
        self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "owner-pass-123"},
        )
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)
        self.client.post("/accounts/logout/")
        # After logout the dashboard redirects to login again.
        dashboard = self.client.get("/dashboard/")
        self.assertEqual(dashboard.status_code, 302)
        self.assertIn("/accounts/login/", dashboard.url)

    def test_login_sets_jwt_httponly_cookies(self):
        response = self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "owner-pass-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(ACCESS_COOKIE, response.cookies)
        self.assertIn(REFRESH_COOKIE, response.cookies)
        # The JWT cookies must be HttpOnly (no JavaScript can read them).
        self.assertTrue(response.cookies[ACCESS_COOKIE]["httponly"])
        self.assertTrue(response.cookies[REFRESH_COOKIE]["httponly"])
        self.assertNotEqual(response.cookies[ACCESS_COOKIE].value, "")

    def test_dashboard_renders_from_jwt_cookie_after_session_cleared(self):
        # Log in normally (sets both session + JWT cookies).
        login = self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "owner-pass-123"},
        )
        self.assertEqual(login.status_code, 302)
        access_cookie = self.client.cookies[ACCESS_COOKIE].value
        self.assertNotEqual(access_cookie, "")

        # Drop ONLY the session so page protection must fall back to the JWT
        # cookie. Clearing the session cookie emulates an expired/missing
        # server session while the browser still holds the access token.
        self.client.cookies.pop("sessionid", None)
        self.client.cookies[ACCESS_COOKIE] = access_cookie

        dashboard = self.client.get("/dashboard/")
        self.assertEqual(dashboard.status_code, 200)

    def test_logout_clears_jwt_cookies(self):
        self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "owner-pass-123"},
        )
        self.assertIn(ACCESS_COOKIE, self.client.cookies)
        response = self.client.post("/accounts/logout/")
        self.assertIn(ACCESS_COOKIE, response.cookies)
        self.assertEqual(response.cookies[ACCESS_COOKIE].value, "")
        self.assertEqual(response.cookies[REFRESH_COOKIE].value, "")

    def test_me_api_authenticates_from_jwt_cookie(self):
        # Login, then drop the session cookie so the API must authenticate
        # purely from the JWT cookie (not the session).
        self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "owner-pass-123"},
        )
        self.client.cookies.pop("sessionid", None)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("username"), "owner")

    def test_silent_refresh_rotates_expired_access_cookie(self):
        # Login: browser gets session + JWT pair as cookies.
        self.client.post(
            "/accounts/login/",
            {"username": "owner", "password": "owner-pass-123"},
        )
        # Drop the session cookie and issue an expired/garbage access token
        # while keeping the valid refresh token -- simulating an expired access.
        self.client.cookies.pop("sessionid", None)
        self.assertNotEqual(self.client.cookies[REFRESH_COOKIE].value, "")
        self.client.cookies[ACCESS_COOKIE] = "garbage.invalid.token"
        old_access = self.client.cookies[ACCESS_COOKIE].value

        response = self.client.get("/dashboard/")

        # Page still renders, and a fresh access cookie was rotated in.
        self.assertEqual(response.status_code, 200)
        self.assertIn(ACCESS_COOKIE, response.cookies)
        new_access = response.cookies[ACCESS_COOKIE].value
        self.assertNotEqual(new_access, "")
        self.assertNotEqual(new_access, old_access)


class ReceiptsPageRenderTests(TestCase):
    """The Receipts page is server-rendered HTML whose table and metrics
    are filled at runtime by receipts.js from /api/payments/receipts/
    (CPMAS-58/CPMAS-21). These tests verify the rendered template
    structure and hooks only -- browser-side fetch/search/date-range
    behavior is covered by the API tests in
    apps.payments.tests.ReceiptDetailAndDownloadAPITests."""

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/receipts/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        DjangoUser.objects.create_user(username="apitester_core", password="pass12345")
        self.client.login(username="apitester_core", password="pass12345")
        response = self.client.get("/receipts/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/receipts.html")

    def test_page_has_required_hooks(self):
        DjangoUser.objects.create_user(username="apitester_receipts2", password="pass12345")
        self.client.login(username="apitester_receipts2", password="pass12345")
        response = self.client.get("/receipts/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for hook in [
            "receipts.js", "receipts.css", "data-receipt-rows",
            'data-metric="total"', 'data-metric="this-month"',
            "receipt-search-input", "data-date-from", "data-date-to",
        ]:
            self.assertIn(hook, content)

    def test_page_has_no_fabricated_receipt_data(self):
        # The Receipts page fills its rows and metrics at runtime from the
        # real /api/payments/receipts/ endpoint -- metrics must start at —
        # and the table at its loading row, with no hardcoded amounts or
        # pre-filled receipt numbers in the served HTML.
        DjangoUser.objects.create_user(username="apitester_receipts3", password="pass12345")
        self.client.login(username="apitester_receipts3", password="pass12345")
        response = self.client.get("/receipts/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('<strong data-metric="total">—</strong>', content)
        self.assertIn('<strong data-metric="this-month">—</strong>', content)
        self.assertIn("Loading receipts…", content)
        # No fabricated figures, records, or receipt numbers on the page.
        self.assertNotIn("$", content)
        self.assertNotIn("$186K", content)
        self.assertNotIn("$428K", content)
        self.assertNotIn("RCT-", content)
        self.assertNotIn("<td><strong>", content)

    def test_js_wires_receipts_endpoint(self):
        # Receipt rows and the Download PDF link are produced by receipts.js
        # at runtime -- verify the bundle targets the real receipts API and
        # the page's own runtime hooks rather than any mock source.
        js = (settings.BASE_DIR / "static/js/receipts.js").read_text(encoding="utf-8")
        for token in [
            "/api/payments/receipts/", "data-receipt-rows",
            "receipt-search-input", "data-date-from", "data-date-to", "download",
        ]:
            self.assertIn(token, js)
        self.assertNotIn("mock", js)
        self.assertNotIn("RCT-", js)


class PaymentsPageRenderTests(TestCase):
    """The Payments page is server-rendered HTML whose metric tiles, list,
    and cash-movement dialogs are filled/wired at runtime by payments.js
    from the real /api/payments/ endpoints (payments, allocations,
    receipts) plus the partner/invoice dropdown APIs. These tests verify
    the rendered template structure and hooks only -- they do NOT exercise
    browser-side fetch/allocation/receipt behavior, which is covered by the
    API tests in apps.payments.tests (PaymentAPITests,
    AllocatePaymentServiceTests, ReceiptDetailAndDownloadAPITests, etc.).

    /payments/ is @login_required (not @owner_required -- accountants need
    it too), so plain django.contrib.auth login is enough, matching
    Receipts/Documents/Expenses."""

    def _login(self):
        DjangoUser.objects.create_user(username="apitester_pay", password="pass12345")
        self.client.login(username="apitester_pay", password="pass12345")

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/payments/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        self._login()
        response = self.client.get("/payments/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/payments.html")
        content = response.content.decode()
        for hook in [
            "payments.js", "payments.css",
            "data-payment-rows", "data-payment-search",
            "data-direction-filter", "data-ordering",
            'data-metric="received"', 'data-metric="paid"',
            'data-metric="unallocated"', 'data-metric="total"',
            "data-payment-new", "data-payment-dialog", "data-payment-form",
            "data-allocation-dialog", "data-allocation-form",
            "data-receipt-dialog", "data-receipt-form",
            "data-payment-detail-dialog", "data-receipt-preview-dialog",
        ]:
            self.assertIn(hook, content)

    def test_page_has_no_fabricated_payment_data(self):
        # The Payments page fills its metric tiles, payment rows, allocation
        # register, and receipt history at runtime from the real /api/payments/
        # endpoints -- metrics must start at — and the table at its loading
        # row, with no hardcoded dollar figures or fake records in the HTML.
        self._login()
        response = self.client.get("/payments/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for metric in ["received", "paid", "unallocated", "total"]:
            self.assertIn(f'<strong data-metric="{metric}">—</strong>', content)
        self.assertIn("Loading payments…", content)
        # No fabricated overview figures, fake records, or pre-filled
        # receipt numbers on the page.
        self.assertNotIn("$", content)
        self.assertNotIn("$186K", content)
        self.assertNotIn("$428K", content)
        self.assertNotIn("$96K", content)
        self.assertNotIn("RCT-", content)
        self.assertNotIn("<td><strong>", content)

    def test_js_wires_payment_actions_and_endpoints(self):
        # The row actions, metrics, and dialogs are produced by payments.js
        # at runtime, so assert against the JS bundle itself that it targets
        # the real payment/allocations/receipts APIs plus the partner and
        # invoice dropdowns the workflow needs.
        js = (settings.BASE_DIR / "static/js/payments.js").read_text(encoding="utf-8")
        for token in [
            "/api/payments/payments/", "/api/payments/payment-allocations/",
            "/api/payments/receipts/",
            "/api/clients/clients/", "/api/suppliers/suppliers/",
            "/api/employees/", "/api/contractors/",
            "/api/invoicing/client-invoices/", "/api/invoicing/supplier-invoices/",
            "data-allocation", "data-receipt", "RCT-",
            "data-register-allocation", "data-register-receipt",
            "data-payment-detail",
        ]:
            self.assertIn(token, js)
        # No mock/fabricated API tokens or fake batch numbers hidden in the
        # bundle.
        self.assertNotIn("mock", js)
        self.assertNotIn("PAY-FAB", js)
        self.assertNotIn("/api/mock/", js)


class ExpensesPageRenderTests(TestCase):
    """The Expenses dashboard page is server-rendered HTML whose table and
    metrics are filled at runtime by expenses.js from the /api/expenses/
    endpoints (list + category lookup + project lookup). 1A-2 added a
    server-rendered create/edit dialog and an Actions column that the same
    script binds to. These tests verify the rendered template structure
    and hooks only -- they do NOT exercise browser-side fetch/filter/
    pagination/dialog behavior, which is covered by manual browser
    verification against the API tests in
    apps.expenses.tests.ExpenseFilterAndPaginationTests and
    ExpenseUpdateDeleteApiTests."""

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/expenses/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        DjangoUser.objects.create_user(username="expenses_render", password="pass12345")
        self.client.login(username="expenses_render", password="pass12345")
        response = self.client.get("/expenses/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/expenses.html")
        content = response.content.decode()
        self.assertIn("expenses.js", content)
        self.assertIn("expenses.css", content)
        self.assertIn("data-expense-rows", content)
        self.assertIn('data-metric="total"', content)
        self.assertIn('data-metric="pending"', content)
        self.assertIn('data-metric="sum"', content)
        self.assertIn('data-metric="month"', content)
        self.assertIn("expense-search-input", content)
        self.assertIn("expense-category-filter", content)
        self.assertIn("expense-project-filter", content)
        self.assertIn("data-status-filter", content)
        self.assertIn("data-date-from", content)
        self.assertIn("data-date-to", content)

    def test_page_has_no_fabricated_expense_data(self):
        DjangoUser.objects.create_user(username="expenses_render2", password="pass12345")
        self.client.login(username="expenses_render2", password="pass12345")
        response = self.client.get("/expenses/")
        content = response.content.decode()
        # The old mock/dummy rows and hardcoded tile defaults must be gone.
        self.assertNotIn("EXP-0871", content)
        self.assertNotIn("EXP-0868", content)
        self.assertNotIn("$214K", content)
        self.assertNotIn("$188K", content)
        self.assertNotIn("$26K", content)
        self.assertNotIn("Crane rental", content)
        self.assertNotIn("Cedar Heights", content)
        # Nonexistent model fields must not be referenced by the template.
        self.assertNotIn("expense.number", content)
        self.assertNotIn("expense.payee", content)

    def test_page_has_create_edit_dialog_and_actions_hooks(self):
        DjangoUser.objects.create_user(username="expenses_render3", password="pass12345")
        self.client.login(username="expenses_render3", password="pass12345")
        response = self.client.get("/expenses/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The Add expense button opens the create dialog.
        self.assertIn("data-expense-new", content)
        # Create/edit dialog hooks populated at runtime by expenses.js.
        self.assertIn("data-expense-dialog", content)
        self.assertIn("data-expense-form", content)
        self.assertIn("data-expense-form-title", content)
        self.assertIn("data-expense-error", content)
        self.assertIn("data-expense-close", content)
        # Every writable serializer field is present in the form.
        for field in [
            "project", "category", "supplier", "expense_date", "description",
            "amount", "tax_amount", "payment_method", "notes",
        ]:
            self.assertIn(f'name="{field}"', content)
        # 1A-2 adds an Actions column; the loading row spans all 8 columns.
        self.assertIn("<th>Actions</th>", content)
        self.assertIn('colspan="8"', content)


class PartnersPageRenderTests(WithUsersTableMixin, TestCase):
    """The Clients & Partners dashboard page is server-rendered HTML whose
    table and metrics are filled at runtime by partners.js from the
    /api/clients/, /api/suppliers/ and /api/contractors/ endpoints."""

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/partners/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        # /partners/ is @owner_required, which reads request.user.is_owner --
        # only a real users.User (via the app's own login view) has that;
        # a plain django.contrib.auth.User (self.client.login()) doesn't get
        # bridged unless it's already anonymous, per AppUserSessionMiddleware.
        owner = AppUser.objects.create(
            username="apitester_partners", email="partners@example.com", password_hash="x",
            first_name="P", last_name="T", role="OWNER",
        )
        owner.set_password("pass12345")
        owner.save(update_fields=["password_hash"])
        self.client.post("/accounts/login/", {"username": "apitester_partners", "password": "pass12345"})
        response = self.client.get("/partners/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Clients &amp; partners", content)
        self.assertIn("partners.js", content)
        self.assertIn("partners.css", content)
        self.assertIn("data-partner-rows", content)
        self.assertIn("partner-search-input", content)


class WorkforcePageRenderTests(WithUsersTableMixin, TestCase):
    """The Workforce dashboard page is server-rendered HTML whose table and
    metrics are filled at runtime by workforce.js from the /api/employees/
    endpoint (and each employee's project assignments)."""

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/workforce/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        # See PartnersPageRenderTests -- /workforce/ is @owner_required too.
        owner = AppUser.objects.create(
            username="apitester_workforce", email="workforce@example.com", password_hash="x",
            first_name="W", last_name="F", role="OWNER",
        )
        owner.set_password("pass12345")
        owner.save(update_fields=["password_hash"])
        self.client.post("/accounts/login/", {"username": "apitester_workforce", "password": "pass12345"})
        response = self.client.get("/workforce/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Workforce", content)
        self.assertIn("workforce.js", content)
        self.assertIn("workforce.css", content)
        self.assertIn("data-workforce-rows", content)
        self.assertIn("workforce-search-input", content)

    def test_accountant_cannot_open_workforce_page(self):
        accountant = AppUser.objects.create(
            username="workforce_accountant", email="workforce-accountant@example.com",
            password_hash="x", first_name="W", last_name="A", role="ACCOUNTANT",
        )
        accountant.set_password("pass12345")
        accountant.save(update_fields=["password_hash"])
        self.client.post(
            "/accounts/login/",
            {"username": "workforce_accountant", "password": "pass12345"},
        )
        response = self.client.get("/workforce/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

    def test_page_has_workforce_crud_and_assignment_hooks(self):
        owner = AppUser.objects.create(
            username="workforce_hooks", email="workforce-hooks@example.com",
            password_hash="x", first_name="W", last_name="H", role="OWNER",
        )
        owner.set_password("pass12345")
        owner.save(update_fields=["password_hash"])
        self.client.post(
            "/accounts/login/", {"username": "workforce_hooks", "password": "pass12345"},
        )
        content = self.client.get("/workforce/").content.decode()
        for hook in [
            "data-workforce-page-error", "data-workforce-add",
            "data-employee-form-dialog", "data-employee-form", "data-employee-form-error",
            "data-employee-detail-dialog", "data-employee-edit", "data-employee-delete",
            "data-assignment-state", "data-assignment-new", "data-assignment-dialog",
            "data-assignment-form", "data-assignment-error", "data-delete-dialog",
        ]:
            self.assertIn(hook, content)
        for field in [
            "name", "employee_number", "phone", "email", "position", "department",
            "labor_rate", "employment_status", "project_id", "role_on_project",
            "assigned_at", "released_at",
        ]:
            self.assertIn(f'name="{field}"', content)

    def test_page_has_no_fabricated_workforce_data(self):
        owner = AppUser.objects.create(
            username="workforce_empty", email="workforce-empty@example.com",
            password_hash="x", first_name="W", last_name="E", role="OWNER",
        )
        owner.set_password("pass12345")
        owner.save(update_fields=["password_hash"])
        self.client.post(
            "/accounts/login/", {"username": "workforce_empty", "password": "pass12345"},
        )
        content = self.client.get("/workforce/").content.decode()
        self.assertIn("Loading workforce…", content)
        self.assertNotIn("EMP-0001", content)
        self.assertNotIn("Site Engineer", content)
        self.assertNotIn("$", content)

    def test_js_wires_existing_workforce_endpoints_without_prompts(self):
        js = (settings.BASE_DIR / "static/js/workforce.js").read_text(encoding="utf-8")
        for token in [
            "/api/employees/", "/api/projects/projects/", '"POST"',
            '"PATCH"', '"DELETE"', "data-assignment-retry",
            "data-workforce-retry", "assignmentErrors",
        ]:
            self.assertIn(token, js)
        self.assertNotIn("prompt(", js)
        self.assertNotIn("/api/workforce/", js)


class DocumentsPageRenderTests(TestCase):
    """The Documents page is server-rendered HTML whose table, metrics, and
    upload form are filled at runtime by documents.js from the
    /api/documents/ endpoints (CPMAS-25). Not owner_required -- accountants
    need it too -- so plain login is enough here, matching Receipts."""

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/documents/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        DjangoUser.objects.create_user(username="apitester_documents", password="pass12345")
        self.client.login(username="apitester_documents", password="pass12345")
        response = self.client.get("/documents/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/documents.html")
        content = response.content.decode()
        self.assertIn("documents.js", content)
        self.assertIn("documents.css", content)
        self.assertIn("data-doc-rows", content)
        self.assertIn("doc-search-input", content)


class InvoicePageRenderTests(TestCase):
    """The Invoices dashboard page is server-rendered HTML whose table,
    metrics, and both the header and line-item dialogs are filled at runtime
    by invoices.js from the /api/invoicing/ endpoints (ClientInvoice +
    SupplierInvoice). 1C-2 adds line-item editing, a tax-rate picker on line
    items, and supplier flat-charge support; these tests verify the rendered
    template structure and hooks only -- client/supplier/project/PO/tax
    choices and invoice rows are populated dynamically by JavaScript, so they
    are asserted against the JS bundle rather than server HTML.

    /invoices/ is @login_required (not @owner_required -- accountants need
    this page too), so plain django.contrib.auth login is enough, matching
    Receipts/Documents/Expenses."""

    def _login(self):
        DjangoUser.objects.create_user(username="apitester_inv", password="pass12345")
        self.client.login(username="apitester_inv", password="pass12345")

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/invoices/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        self._login()
        response = self.client.get("/invoices/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/invoices.html")
        content = response.content.decode()
        for hook in [
            "invoices.js", "invoices.css",
            "data-invoice-rows", "data-invoice-search",
            "data-type-filter", "data-status-filter",
            'data-metric="receivables"', 'data-metric="payables"',
            'data-metric="overdue"', 'data-metric="total"',
            "data-new-invoice", "data-invoice-dialog", "data-invoice-form",
            "data-invoice-detail", "data-add-item", "data-item-rows",
            "data-item-form", "data-tax-rate",
        ]:
            self.assertIn(hook, content)

    def test_page_has_no_fabricated_invoice_data(self):
        self._login()
        response = self.client.get("/invoices/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Metrics initially render as — ; the table shows a loading row rather
        # than hardcoded invoices; no fabricated invoice numbers exist.
        self.assertIn('<strong data-metric="receivables">—</strong>', content)
        self.assertIn('<strong data-metric="payables">—</strong>', content)
        self.assertIn('<strong data-metric="overdue">—</strong>', content)
        self.assertIn('<strong data-metric="total">—</strong>', content)
        self.assertIn("Loading invoices…", content)
        self.assertNotIn("INV-", content)
        self.assertNotIn("CINV-", content)
        self.assertNotIn("<td><strong>", content)

    def test_js_wires_invoice_actions_and_endpoints(self):
        # The row-action hooks and invoicing endpoints can't be observed in
        # server HTML (they are produced by invoices.js at runtime), so we
        # assert the implementation wires them by inspecting the JS bundle.
        js = (settings.BASE_DIR / "static/js/invoices.js").read_text(encoding="utf-8")
        for token in [
            "/api/invoicing/client-invoices/", "/api/invoicing/supplier-invoices/",
            "/api/invoicing/client-invoice-items/", "/api/invoicing/supplier-invoice-items/",
            "/api/clients/clients/", "/api/suppliers/suppliers/",
            "/api/projects/projects/", "/api/purchasing/purchase-orders/",
            "/api/taxes/tax-rates/",
            "data-new-invoice", "data-edit", "data-delete", "data-view",
            "mark_sent", "cancel", "data-item-delete",
            "data-item-edit", "data-tax-rate", "line_type", "total_amount", "PATCH",
        ]:
            self.assertIn(token, js)
        # No fabricated invoice values hidden in the bundle.
        self.assertNotIn("INV-FAB", js)
        self.assertNotIn("CINV-FAB", js)


class ProcurementPageRenderTests(WithUsersTableMixin, TestCase):
    """The Procurement dashboard page is server-rendered HTML whose table,
    metrics, and detail dialog are filled at runtime by procurement.js from
    the /api/purchasing/ endpoints (CPMAS-42). 1C-1 adds the purchase-order
    authoring dialog (create / edit DRAFT / submit / approve / cancel);
    these tests verify the rendered template structure and hooks only --
    supplier/material choices and PO rows are populated dynamically by
    JavaScript, so they are asserted against the JS bundle rather than server
    HTML."""

    def setUp(self):
        self.owner = AppUser.objects.create(
            username="apitester_procurement", email="procurement@example.com", password_hash="x",
            first_name="P", last_name="R", role="OWNER",
        )
        self.owner.set_password("pass12345")
        self.owner.save(update_fields=["password_hash"])

    def _login_owner(self):
        self.client.post("/accounts/login/", {"username": "apitester_procurement", "password": "pass12345"})
        return self.client.get("/procurement/")

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/procurement/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        # See PartnersPageRenderTests -- /procurement/ is @owner_required too.
        response = self._login_owner()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for hook in [
            "Procurement", "procurement.js", "procurement.css",
            "data-po-rows", "po-search-input",
            "data-po-status", "data-receipt-rows", "receipt-search-input",
            "data-receipt-po-filter", "data-page-prev", "data-page-next",
            "data-receive-dialog", "data-receipt-detail-dialog",
        ]:
            self.assertIn(hook, content)

    def test_po_dialog_hooks_present(self):
        response = self._login_owner()
        content = response.content.decode()
        for hook in [
            "data-po-dialog", "data-po-form", "data-po-supplier",
            "data-po-number", "data-po-order-date", "data-po-expected-date",
            "data-po-item-rows", "data-po-add-item",
            "data-po-error", "data-po-page-error", "data-po-save",
            "data-open-po",
        ]:
            self.assertIn(hook, content)

    def test_supplier_and_material_choices_are_not_server_rendered(self):
        # Supplier/material dropdowns are populated at runtime by
        # procurement.js from /api/suppliers/suppliers/ and
        # /api/inventory/materials/ -- verify the server HTML only ships the
        # loading placeholders (no hardcoded options) and the tables still
        # show loading empty-rows rather than fabricated purchase data.
        response = self._login_owner()
        content = response.content.decode()
        self.assertIn("Loading suppliers…", content)
        self.assertNotIn("Select supplier…", content)
        self.assertNotIn("Select material…", content)
        self.assertIn("Loading purchase orders…", content)
        self.assertIn("Loading goods receipts…", content)
        self.assertIn('<strong data-metric="open_pos">—</strong>', content)
        self.assertNotIn("<td><strong>", content)
        self.assertNotIn("PO-FAB-0001", content)

    def test_js_wires_po_actions_and_endpoints(self):
        # The row-action hooks and purchasing endpoints can't be observed in
        # server HTML (they are produced by procurement.js at runtime), so we
        # assert the implementation wires them by inspecting the JS bundle.
        js = (settings.BASE_DIR / "static/js/procurement.js").read_text(encoding="utf-8")
        for token in [
            "data-po-edit", "data-po-submit-action", "data-po-approve", "data-po-cancel",
            "data-po-remove-item", "data-receive", "window.confirm",
            "/api/suppliers/suppliers/", "/api/inventory/materials/",
            "/api/purchasing/purchase-orders/", "/api/purchasing/purchase-order-items/",
            "submit", "approve", "cancel", "created_by",
        ]:
            self.assertIn(token, js)
        # No fabricated purchasing values hidden in the bundle.
        self.assertNotIn("PO-API-", js)


class InventoryPageRenderTests(WithUsersTableMixin, TestCase):
    """The Inventory dashboard page is server-rendered HTML whose table and
    metrics are filled at runtime by inventory.js from the /api/inventory/
    endpoints (stocks + materials merge + warehouses + stock-movements),
    and whose 1B-2 Record-movement and movement-history dialogs submit to
    the stock-movements ledger and transfer action.

    These tests verify the rendered template structure and hooks only --
    they do NOT exercise browser-side fetch/submit/filter behavior, which
    is covered by manual browser verification against the API tests in
    apps.inventory.tests (StockReadApiTests + StockMovementWorkflowApiTests).
    /inventory/ is @owner_required (like partners/workforce/procurement),
    so owner/accountant behavior is tested through the app's own login
    view."""

    def setUp(self):
        self.owner = AppUser.objects.create(
            username="inv_owner", email="inv@example.com", password_hash="x",
            first_name="I", last_name="O", role="OWNER",
        )
        self.owner.set_password("owner-pass-123")
        self.owner.save(update_fields=["password_hash"])
        self.accountant = AppUser.objects.create(
            username="inv_accountant", email="invacc@example.com", password_hash="x",
            first_name="I", last_name="A", role="ACCOUNTANT",
        )
        self.accountant.set_password("accountant-pass-123")
        self.accountant.save(update_fields=["password_hash"])

    def _login(self, username, password):
        return self.client.post(
            "/accounts/login/", {"username": username, "password": password}, follow=False,
        )

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/inventory/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_owner(self):
        self._login("inv_owner", "owner-pass-123")
        response = self.client.get("/inventory/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/inventory.html")
        content = response.content.decode()
        self.assertIn("inventory.js", content)
        self.assertIn("inventory.css", content)
        self.assertIn("data-inventory-rows", content)
        self.assertIn('data-metric="stock"', content)
        self.assertIn('data-metric="low"', content)
        self.assertIn('data-metric="value"', content)
        self.assertIn('data-metric="transfers"', content)
        self.assertIn("inventory-search-input", content)
        self.assertIn("inventory-warehouse-filter", content)
        self.assertIn("data-status-filter", content)
        self.assertIn("<th>On hand</th>", content)
        self.assertIn("<th>Actions</th>", content)
        self.assertIn('colspan="7"', content)
        # 1B-2: record-movement dialog + form + its fields.
        self.assertIn("data-movement-new", content)
        self.assertIn("data-movement-dialog", content)
        self.assertIn("data-movement-form", content)
        self.assertIn("data-movement-type", content)
        self.assertIn("data-movement-material", content)
        self.assertIn("data-movement-warehouse", content)
        self.assertIn("data-movement-from", content)
        self.assertIn("data-movement-to", content)
        self.assertIn("data-movement-qty", content)
        self.assertIn("data-movement-date", content)
        self.assertIn("data-movement-reference", content)
        self.assertIn("data-movement-notes", content)
        self.assertIn("data-movement-close", content)
        # 1B-2: movement history dialog.
        self.assertIn("data-movement-history-dialog", content)
        self.assertIn("data-movement-history-rows", content)

    def test_accountant_cannot_open_inventory_page(self):
        self._login("inv_accountant", "accountant-pass-123")
        response = self.client.get("/inventory/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

    def test_page_has_no_fabricated_inventory_data(self):
        self._login("inv_owner", "owner-pass-123")
        response = self.client.get("/inventory/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The old mock rows, mock columns, and hardcoded tile defaults must
        # be gone; no fabricated values are injected by the template.
        self.assertNotIn("MAT-CEM-001", content)
        self.assertNotIn("MAT-STL-016", content)
        self.assertNotIn("Portland Cement 50kg", content)
        self.assertNotIn("Rebar Steel 16mm", content)
        self.assertNotIn("Beirut Site Store", content)
        self.assertNotIn("Central Warehouse", content)
        self.assertNotIn("$486K", content)
        self.assertNotIn("$7.80", content)
        self.assertNotIn("480 bags", content)
        self.assertNotIn("$680/t", content)


class AppUserContextProcessorTests(WithUsersTableMixin, TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def test_anonymous_request_has_no_bridge(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertEqual(app_user(request), {"app_user_id": None})

    def test_authenticated_with_no_matching_users_user_degrades_to_none(self):
        django_user = DjangoUser.objects.create_user(username="unmatched", password="pass12345")
        request = self.factory.get("/")
        request.user = django_user
        self.assertEqual(app_user(request), {"app_user_id": None})

    def test_authenticated_with_matching_username_is_bridged(self):
        django_user = DjangoUser.objects.create_user(username="bridged.user", password="pass12345")
        app_user_row = AppUser.objects.create(
            username="bridged.user", email="bridged@example.com", password_hash="x",
            first_name="B", last_name="U", role="OWNER",
        )
        request = self.factory.get("/")
        request.user = django_user
        self.assertEqual(app_user(request), {"app_user_id": str(app_user_row.id)})

    def test_request_user_already_an_app_user_skips_the_lookup(self):
        # The common case since users.middleware.AppUserSessionMiddleware:
        # request.user is already the real users.User -- no DB lookup needed.
        app_user_row = AppUser.objects.create(
            username="already.bridged", email="already@example.com", password_hash="x",
            first_name="A", last_name="B", role="OWNER",
        )
        request = self.factory.get("/")
        request.user = app_user_row
        self.assertEqual(app_user(request), {"app_user_id": str(app_user_row.id)})


class RoleRoutingTests(WithUsersTableMixin, TestCase):
    """Owner and accountant land on their role-appropriate dashboards, and
    workspace/operations pages are gated so accountants are redirected away."""

    def setUp(self):
        self.owner = AppUser.objects.create(
            username="owner", email="owner@example.com", password_hash="x",
            first_name="O", last_name="W", role="OWNER",
        )
        self.owner.set_password("owner-pass-123")
        self.owner.save(update_fields=["password_hash"])
        self.accountant = AppUser.objects.create(
            username="accountant", email="accountant@example.com", password_hash="x",
            first_name="A", last_name="C", role="ACCOUNTANT",
        )
        self.accountant.set_password("accountant-pass-123")
        self.accountant.save(update_fields=["password_hash"])

    def _login(self, username, password):
        self.client.post(
            "/accounts/login/", {"username": username, "password": password}, follow=False,
        )

    def test_owner_lands_on_owner_overview(self):
        self._login("owner", "owner-pass-123")
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/overview.html")

    def test_accountant_lands_on_finance_dashboard(self):
        self._login("accountant", "accountant-pass-123")
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/accountant_overview.html")

    def test_accountant_cannot_open_owner_workspace_page(self):
        self._login("accountant", "accountant-pass-123")
        response = self.client.get("/projects/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

    def test_owner_can_open_workspace_page(self):
        self._login("owner", "owner-pass-123")
        response = self.client.get("/projects/")
        self.assertEqual(response.status_code, 200)

    def test_accountant_can_open_finance_page(self):
        # Finance pages are @login_required (accountants need invoices,
        # payments, and receipts); workspace/operations pages are not.
        self._login("accountant", "accountant-pass-123")
        for url in ["/invoices/", "/payments/", "/receipts/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)


class OwnerDashboardPageRenderTests(WithUsersTableMixin, TestCase):
    """The owner workspace dashboard is server-rendered HTML whose metric
    tiles, portfolio donut, milestones, and projects table are filled at
    runtime by overview.js from the real /api/projects/ endpoints (projects
    list, portfolio budget summary, phases) plus /api/invoicing/
    client-invoices for A/R. No figures are baked into the template --
    every metric starts at — and every list at its loading row. These tests
    verify the rendered structure and hooks only; they do NOT exercise
    browser-side fetch logic.

    /dashboard/ routes to the owner template via request.user.is_accountant
    (apps.core.views.dashboard), so these tests need a real AppUser with
    role OWNER, mirroring RoleRoutingTests."""

    def setUp(self):
        self.owner = AppUser.objects.create(
            username="owner_overview", email="owner_overview@example.com", password_hash="x",
            first_name="O", last_name="W", role="OWNER",
        )
        self.owner.set_password("owner-pass-123")
        self.owner.save(update_fields=["password_hash"])

    def _login(self):
        self.client.post(
            "/accounts/login/",
            {"username": "owner_overview", "password": "owner-pass-123"},
            follow=False,
        )

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_authenticated_user(self):
        self._login()
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/overview.html")
        content = response.content.decode()
        for hook in [
            "overview.js",
            'data-ov-metric="active-projects"', 'data-ov-metric="portfolio-value"',
            'data-ov-metric="actual-cost"', 'data-ov-metric="outstanding-ar"',
            "data-ov-attention-count", "data-ov-attention-text",
            'data-ov-donut="portfolio"', "data-ov-spent-pct",
            "data-ov-approved", "data-ov-actual", "data-ov-remaining",
            "data-ov-portfolio-note", "data-ov-milestones",
            "data-project-rows", "Loading projects…",
        ]:
            self.assertIn(hook, content)

    def test_page_has_no_fabricated_figures(self):
        # The dashboard metrics are filled at runtime from real APIs. The
        # template must ship empty hooks (— and Loading…) with no hardcoded
        # dollar figures, fake milestone names, or trend claims.
        self._login()
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for metric in ["active-projects", "portfolio-value", "actual-cost", "outstanding-ar"]:
            self.assertIn(f'data-ov-metric="{metric}">—</div>', content)
        self.assertIn("Loading…", content)
        for fabricated in [
            "$6.42M", "$3.18M", "$428K", "$214K", "$186K", "$52K",
            "$96K", "$452K", "$4.31M", "$1.13M", "$94K", "$58K",
            "Excavation", "Foundation pour", "Structural framing",
            "Interior fit-out", "On track", "under plan", "above plan",
        ]:
            self.assertNotIn(fabricated, content)

    def test_js_wires_real_overview_endpoints(self):
        # The renderer logic lives in overview.js, so assert the bundle
        # targets the real APIs the widgets derive from and carries the
        # dashboard-local overdue rule.
        js = (settings.BASE_DIR / "static/js/overview.js").read_text(encoding="utf-8")
        for token in [
            "/api/projects/projects/", "/api/projects/budgets/portfolio-summary/",
            "/api/projects/phases/", "/api/invoicing/client-invoices/",
            "data-ov-metric", "data-ov-donut", "data-ov-milestones",
            "conic-gradient", "PARTIALLY_PAID", "outstanding_balance",
        ]:
            self.assertIn(token, js)
        # No fabricated dashboard figure or fake API hidden in the bundle.
        self.assertNotIn("/api/dashboard/", js)
        self.assertNotIn("mock", js)
        self.assertNotIn("$6.42M", js)


class AccountantDashboardPageRenderTests(WithUsersTableMixin, TestCase):
    """The accountant finance dashboard is server-rendered HTML whose metric
    tiles, cash-flow donut, receivables list, and recent-payments table are
    filled at runtime by overview.js from the real invoicing/payments/
    expenses APIs. Metrics render as — and lists at their loading rows; the
    recent-payments table columns are Receipt | Client | Date | Method |
    Amount with no hardcoded rows. These tests verify the rendered structure
    and hooks only (browser-side aggregation is outside the test client).

    Unlike the owner dashboard, /dashboard/ routes accountants to
    accountant_overview.html by request.user.is_accountant, so these tests
    need a real AppUser with role ACCOUNTANT, mirroring RoleRoutingTests."""

    def setUp(self):
        self.accountant = AppUser.objects.create(
            username="acct_overview", email="acct_overview@example.com", password_hash="x",
            first_name="A", last_name="C", role="ACCOUNTANT",
        )
        self.accountant.set_password("accountant-pass-123")
        self.accountant.save(update_fields=["password_hash"])

    def _login(self):
        self.client.post(
            "/accounts/login/",
            {"username": "acct_overview", "password": "accountant-pass-123"},
            follow=False,
        )

    def test_redirects_anonymous_user_to_login(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_page_renders_for_accountant(self):
        self._login()
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/accountant_overview.html")
        content = response.content.decode()
        for hook in [
            "overview.js",
            'data-ov-metric="invoiced-mtd"', 'data-ov-metric="payments-received"',
            'data-ov-metric="outstanding-ar"', 'data-ov-metric="expenses-mtd"',
            "data-ov-attention-count", "data-ov-attention-text",
            'data-ov-donut="cash"', "data-ov-collected-pct",
            "data-ov-received", "data-ov-cash-outstanding",
            "data-ov-cash-expenses", "data-ov-cash-note",
            "data-ov-receivables", "data-ov-recent-rows",
            "Loading receipts…",
        ]:
            self.assertIn(hook, content)

    def test_page_has_no_fabricated_figures(self):
        self._login()
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for metric in ["invoiced-mtd", "payments-received", "outstanding-ar", "expenses-mtd"]:
            self.assertIn(f'data-ov-metric="{metric}">—</div>', content)
        for header in ["<th>Receipt</th>", "<th>Client</th>", "<th>Date</th>", "<th>Method</th>", "<th>Amount</th>"]:
            self.assertIn(header, content)
        for fabricated in [
            "$6.42M", "$3.18M", "$428K", "$214K", "$186K", "$52K",
            "$96K", "$452K", "$4.31M", "$1.13M", "$94K", "$58K",
            "INV-", "RCPT-", "<td><strong>", "invoiced_mtd",
        ]:
            self.assertNotIn(fabricated, content)

    def test_js_wires_accountant_endpoints(self):
        # The accountant widgets derive from the invoicing/payments/expenses
        # APIs in overview.js; assert the bundle targets them.
        js = (settings.BASE_DIR / "static/js/overview.js").read_text(encoding="utf-8")
        for token in [
            "/api/invoicing/client-invoices/",
            "/api/payments/payments/?direction=INCOMING",
            "/api/payments/receipts/",
            "/api/expenses/expenses/?status=PENDING",
            "data-ov-recent-rows", "data-ov-receivables",
            "receipt_date", "invoice_number", "direction=INCOMING",
        ]:
            self.assertIn(token, js)
