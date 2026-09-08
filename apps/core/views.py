from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from rest_framework_simplejwt.tokens import RefreshToken

from company.models import DEFAULT_CURRENCY_UUID, CompanyProfile
from company.storage import SupabaseStorageError, upload_logo

from users.authentication import SESSION_USER_ID_KEY, _set_jwt_cookies, _clear_jwt_cookies
from users.models import User
from users.serializers import (
    RequestPasswordResetSerializer,
    ResetPasswordSerializer,
)
from users.services import get_user_from_uid, send_password_reset_email
from users.tokens import default_token_generator


def owner_required(view_func):
    """Restrict a dashboard view to owners; redirect accountants to their
    dashboard. Keeps workspace/operations pages out of accountants' hands."""
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_owner:
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)
    return _wrapped


def login(request):
    """Render the app login page and authenticate a users.User on POST.

    This is the server-rendered counterpart of the /api/auth/login/ endpoint:
    it validates a username + password against the app's own ``users.User``
    (the same model the DRF API uses) and, on success, records the login in
    the Django session AND sets the JWT pair as HttpOnly cookies. The JWT
    cookies give API calls stateless auth automatically (the browser sends
    them on every request); the session + AppUserSessionMiddleware keep
    ``@login_required`` and the dashboard working on standard navigations.
    """
    error = None
    redirect_to = request.POST.get("next") or request.GET.get("next") or reverse("dashboard")
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = User.objects.filter(username__iexact=username).first()
        if user is not None and user.is_active and user.check_password(password):
            request.session[SESSION_USER_ID_KEY] = str(user.id)
            request.session.save()
            request.user = user
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])
            response = redirect(redirect_to)
            # Set the JWT access (+ refresh) as HttpOnly cookies so the browser
            # authenticates the API layer from the cookie, no JS token handling.
            # Tokens are minted straight from the already-verified user -- avoiding
            # a second (expensive, Argon2) password hash that the serializer
            # round-trip would perform.
            refresh = RefreshToken.for_user(user)
            _set_jwt_cookies(
                response,
                str(refresh.access_token),
                str(refresh),
            )
            return response
        error = "Your username or password is incorrect."
    return render(request, "registration/login.html", {"error": error, "next": redirect_to})


@require_POST
def logout(request):
    request.session.flush()
    response = redirect(reverse("landing"))
    _clear_jwt_cookies(response)
    return response


def forgot_password(request):
    """Render the forgot-password page and email a reset link on POST.

    Mirrors the /api/auth/request-password-reset/ behaviour: the user submits
    the email on their account and, if it matches, a reset link is emailed.
    The page always shows a neutral "check your email" message so it cannot be
    used to discover which addresses have accounts.
    """
    ctx = {"sent": False}
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        serializer = RequestPasswordResetSerializer(data={"email": email})
        if serializer.is_valid():
            user = serializer._user
            if user is not None and user.is_active:
                send_password_reset_email(user)
            ctx = {"sent": True}
        else:
            ctx = {"sent": False, "error": "Enter a valid email address."}
    return render(request, "registration/forgot_password.html", ctx)


def reset_password(request):
    """Render the reset-password page and apply a new password on POST.

    The user arrives via the emailed button link carrying ?uid=... &token=...
    (see ``users.services.send_password_reset_email``). This is the page that
    URL points to. GET validates the link so we can show an "invalid/expired"
    state early; POST validates uid+token+new_password (via
    ``ResetPasswordSerializer``) and, on success, replaces the password.
    """
    ctx = {"uid": "", "token": "", "invalid": False, "done": False}

    if request.method == "POST":
        uid = request.POST.get("uid") or ""
        token = request.POST.get("token") or ""
        new_password = request.POST.get("new_password") or ""
        confirm = request.POST.get("confirm_password") or ""

        if new_password != confirm:
            ctx = {"uid": uid, "token": token, "error": "The passwords you entered do not match."}
            return render(request, "registration/reset_password.html", ctx)

        serializer = ResetPasswordSerializer(
            data={"uid": uid, "token": token, "new_password": new_password}
        )
        if serializer.is_valid():
            user = serializer.validated_data["user"]
            user.set_password(new_password)
            user.save(update_fields=["password_hash", "updated_at"])
            ctx = {"done": True}
        else:
            ctx = {"uid": uid, "token": token, "error": str(serializer.errors)}
        return render(request, "registration/reset_password.html", ctx)

    # GET: read uid/token from the query string and report whether the link is
    # still valid so we can route to the success/expired states.
    uid = request.GET.get("uid") or ""
    token = request.GET.get("token") or ""
    user = get_user_from_uid(uid)
    valid = user is not None and default_token_generator.check_token(user, token or "")
    if not valid:
        return render(request, "registration/reset_password.html", {"invalid": True})
    return render(request, "registration/reset_password.html", {"uid": uid, "token": token})


def landing(request):
    return render(request, "public/landing.html")


def cedar_control(request):
    return render(request, "public/cedar_control.html")


@login_required
def dashboard(request):
    """Render the user's landing dashboard, selected by role.

    Owners see the full workspace overview; accountants land on a
    finance-only dashboard (no workspace/operations).
    """
    if request.user.is_accountant:
        context = {
            "active_page": "overview",
            "invoiced_mtd": "$214K",
            "payments_received": "$186K",
            "outstanding_ar": "$428K",
            "expenses_mtd": "$52K",
            "recent_payments": [],
        }
        return render(request, "dashboard/accountant_overview.html", context)

    context = {
        "active_page": "overview",
        "active_projects": 8,
        "portfolio_value": "$6.42M",
        "actual_cost": "$3.18M",
        "outstanding_ar": "$428K",
        "projects": [],
    }

    return render(request, "dashboard/overview.html", context)


def _dashboard_page(request, template_name, active_page, **context):
    """Render one of the dedicated v3 dashboard screens."""
    return render(
        request,
        f"dashboard/{template_name}.html",
        {"active_page": active_page, **context},
    )


@owner_required
def projects_page(request):
    return _dashboard_page(request, "projects", "projects", projects=[])


@owner_required
def project_detail(request, pk):
    return _dashboard_page(request, "project_detail", "projects", project={"pk": pk})


@owner_required
def approvals_page(request):
    return _dashboard_page(request, "approvals", "approvals", approvals=[])


@owner_required
def partners_page(request):
    return _dashboard_page(request, "partners", "partners", partners=[])


@owner_required
def procurement_page(request):
    return _dashboard_page(request, "procurement", "procurement")


@owner_required
def inventory_page(request):
    return _dashboard_page(request, "inventory", "inventory")


@owner_required
def workforce_page(request):
    return _dashboard_page(request, "workforce", "workforce", workforce=[])


@login_required
def invoices_page(request):
    return _dashboard_page(request, "invoices", "invoices", invoices=[])


@login_required
def payments_page(request):
    return _dashboard_page(request, "payments", "payments", payments=[])


@login_required
def accounting_page(request):
    """
    Accounting / Financial Transactions page (CPMAS-34). Renders a dashboard
    view that talks to the /api/accounting/ endpoints (AccountViewSet,
    FinancialTransactionViewSet, TransactionLineViewSet) for listing,
    creating, editing, posting, and voiding journal entries.
    """
    return _dashboard_page(request, "accounting", "accounting")


@login_required
def expenses_page(request):
    # The Expenses page renders empty and fills its table + metrics at
    # runtime from /api/expenses/ (expenses.js) -- no server context needed.
    return _dashboard_page(request, "expenses", "expenses")


@login_required
def reports_page(request):
    return _dashboard_page(request, "reports", "reports")


@login_required
def module_page(request, module):
    """Render a shared placeholder until each module owns its page."""
    return render(
        request,
        "dashboard/module_page.html",
        {"page_title": module.replace("-", " ").title(), "active_page": module},
    )


@login_required
def receipts_page(request):
    """
    Receipts page (CPMAS-58/CPMAS-21). Renders a dashboard view that
    talks to /api/payments/receipts/ (ReceiptViewSet) for listing,
    search, date-range filtering, and PDF download.
    """
    return render(request, "dashboard/receipts.html", {"active_page": "receipts"})


@login_required
def documents_page(request):
    """
    Document Management page (CPMAS-25). Renders a dashboard view that
    talks to /api/documents/documents/ (DocumentViewSet) for browsing,
    uploading, and deleting files associated with any entity (contracts,
    invoices, receipts, POs, change orders, ...). Not owner_required --
    accountants need this too (client/supplier invoices, receipts).
    """
    return render(request, "dashboard/documents.html", {"active_page": "documents"})


@owner_required
def suppliers(request):
    """
    Supplier Management page. Renders a dashboard view that talks to the
    /api/suppliers/ endpoints (SupplierViewSet) for supplier profile,
    purchase orders, invoices, payments, and outstanding balance.
    """
    return render(request, "dashboard/suppliers.html", {"active_page": "suppliers"})


@login_required
def contractors(request):
    """
    Contractor Management page. Renders a dashboard view that talks to the
    /api/contractors/ endpoints (ContractorViewSet) for contractor profile,
    project assignments, and linked documents.
    """
    return render(request, "dashboard/contractors.html", {"active_page": "contractors"})


@login_required
def employees(request):
    """
    Employee Management page. Renders a dashboard view that talks to the
    /api/employees/ endpoints (EmployeeViewSet) for employee profiles,
    project assignments, and labor information.
    """
    return render(request, "dashboard/employees.html", {"active_page": "employees"})


def _company_profile_form_value(request, key, required=False):
    value = request.POST.get(key, "").strip()
    if required and not value:
        return ""
    return value or None


@login_required
def profile(request):
    """
    My profile page: view and edit profile details (name/email/phone; role
    is read-only) and change the user's password. POST handles either the
    profile form (fields below with a ``profile_action`` marker) or the
    password form (``change-password``). Accessible to any authenticated
    user (Owner or Accountant); each user edits only their own account.
    """
    user = request.user
    error = None
    success = None

    if request.method == "POST":
        submitted_action = request.POST.get("form_action")
        if submitted_action == "password":
            new_password = request.POST.get("new_password") or ""
            confirm = request.POST.get("confirm_password") or ""
            if len(new_password) < 8:
                error = "New password must be at least 8 characters long."
            elif new_password != confirm:
                error = "The new passwords you entered do not match."
            else:
                user.set_password(new_password)
                user.save(update_fields=["password_hash", "updated_at"])
                success = "Password changed successfully."
        else:
            first_name = (request.POST.get("first_name") or "").strip()
            last_name = (request.POST.get("last_name") or "").strip()
            email = (request.POST.get("email") or "").strip()
            if not first_name or not last_name or not email:
                error = "First name, last name and email are required."
            else:
                user.first_name = first_name
                user.last_name = last_name
                user.email = email
                user.phone = (request.POST.get("phone") or "").strip() or None
                user.save(update_fields=["first_name", "last_name", "email", "phone", "updated_at"])
                success = "Profile updated successfully."

    return render(
        request,
        "dashboard/profile.html",
        {"active_page": "profile", "user": user, "error": error, "saved": success},
    )


@login_required
def company_settings(request):
    """
    Administration -> Company settings page.

    Single system-wide company identity backed by the existing
    ``company_details`` table (CompanyProfile, managed=False). GET renders
    the form prefilled from the most recently updated row; POST saves the
    editable identity fields. ``currency`` is deliberately never written
    here -- the system currency is fixed at USD and there is no currencies
    table in the schema to choose from.
    """
    profile = CompanyProfile.objects.order_by("-updated_at").first()
    error = None

    if request.method == "POST":
        form_name = _company_profile_form_value(request, "name")
        if not form_name:
            error = "Company name is required."
        else:
            data = {
                "name": form_name,
                "registration_number": _company_profile_form_value(request, "registration_number"),
                "address": _company_profile_form_value(request, "address"),
                "phone": _company_profile_form_value(request, "phone"),
                "email": _company_profile_form_value(request, "email"),
                "website": _company_profile_form_value(request, "website"),
                "tax_information": _company_profile_form_value(request, "tax_information"),
            }
            logo_file = request.FILES.get("logo")
            if logo_file:
                try:
                    data["logo"] = upload_logo(logo_file)
                except SupabaseStorageError as exc:
                    error = f"Could not upload logo: {exc}"
            if error is None:
                if profile is None:
                    profile = CompanyProfile.objects.create(currency=DEFAULT_CURRENCY_UUID, **data)
                else:
                    for field, value in data.items():
                        setattr(profile, field, value)
                    profile.save(update_fields=list(data.keys()) + ["updated_at"])
                return redirect(f"{reverse('settings')}?saved=1")

    return render(
        request,
        "dashboard/company_settings.html",
        {"active_page": "settings", "profile": profile, "current_user_id": str(request.user.id), "saved": request.GET.get("saved") == "1", "error": error},
    )
