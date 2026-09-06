"""
Shared template context processors (CPMAS-58).

``app_user`` bridges a bit of a real architecture gap: the dashboard
(``apps.core``) authenticates against Django's built-in ``auth.User``
(session login via ``/accounts/login/``), while the domain API
(``users.User`` -- FKs like ``Notification.user``) is a separate model
authenticated via ``/api/auth/login/``. Nothing currently links a
logged-in dashboard session to a specific ``users.User`` row.

Until that's unified (a cross-cutting auth change well beyond this
ticket), this resolves the best available bridge -- a ``users.User``
row whose ``username`` matches the Django session's username -- so
per-user frontend widgets (the notifications bell) have *something* to
scope requests by. When no matching row exists, ``app_user_id`` is
simply empty and those widgets degrade to an empty state rather than
erroring.

Runs on every authenticated template render project-wide (it's a
context processor, not scoped to one app), so the ``users`` table not
existing is treated the same way -- e.g. a test rendering an
authenticated page without ``users.testing.WithUsersTableMixin`` (most
don't, since most pages have nothing to do with this bridge) shouldn't
start failing because of a widget it never asked for.
"""
from django.db.utils import DatabaseError

from company.models import CompanyProfile
from users.models import User as AppUser


def app_user(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"app_user_id": None}

    try:
        app_user_row = AppUser.objects.filter(username=user.get_username()).first()
    except DatabaseError:
        return {"app_user_id": None}
    return {"app_user_id": str(app_user_row.id) if app_user_row else None}


def company_logo(request):
    """Expose the company's logo URL to every template.

    Single-company system (see ``CompanyProfile`` / the ``company_details``
    table). Resolves to the most recently updated profile's ``logo`` value
    (a Supabase storage public URL), or ``None`` when none is set or the
    table isn't present (e.g. in most tests). Templates can then do
    ``{% if company_logo %}`` to swap the placeholder glyph for the real
    logo image, falling back to the glyph otherwise.
    """
    try:
        profile = CompanyProfile.objects.order_by("-updated_at").first()
    except DatabaseError:
        profile = None
    logo = getattr(profile, "logo", None) or None
    version = ""
    if logo and getattr(profile, "updated_at", None) is not None:
        version = str(int(profile.updated_at.timestamp()))
    return {"company_logo": logo, "company_logo_version": version}

