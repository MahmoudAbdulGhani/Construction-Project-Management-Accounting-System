"""
Custom DRF authentication for the ``users`` app.

Provides two authentication backends:

1. ``UserSessionAuthentication`` — resolves ``request.user`` from the
   Django session via the custom ``users.User`` table.  Used for
   server-rendered pages where the session cookie is the auth mechanism.

2. ``JwtUserAuthentication`` — a ``simplejwt.JWTAuthentication`` subclass
   that looks up ``users.User`` (UUID PK) instead of Django's default
   ``auth.User`` (integer PK).  Used as the DRF default for API calls.
"""
from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as _SimpleJwtAuth,
)

from .models import Role, User

# Session key under which we store the logged-in user's id. Distinct from
# the built-in "_auth_user_id" Django uses so we never collide with, or
# pretend to be, a Django auth.User session.
SESSION_USER_ID_KEY = '_users_user_id'

# Name of the HttpOnly cookies that carry the JWT pair for browser sessions.
# Reading the token from a cookie gives the stateless benefits of JWT on the
# backend while standard browser navigations and API calls work out of the
# box (the browser attaches the cookie automatically, no JS refactor needed).
ACCESS_COOKIE = 'access_token'
REFRESH_COOKIE = 'refresh_token'


def _set_jwt_cookies(response, access_token, refresh_token=None, max_age=None):
    """Attach the JWT tokens to an HTTP response as HttpOnly cookies.

    ``path='/'`` makes them valid for the whole site. ``max_age`` defaults to
    the SimpleJWT lifetimes when not provided. secure/SameSite are left to the
    caller's deployment policy via settings (kept permissive here so local
    HTTP development works; production should set Secure + SameSite=Lax).
    """
    secure = getattr(settings, 'JWT_COOKIE_SECURE', False)
    samesite = getattr(settings, 'JWT_COOKIE_SAMESITE', 'Lax')
    if access_token:
        response.set_cookie(
            ACCESS_COOKIE, access_token, max_age=max_age, path='/',
            httponly=True, secure=secure, samesite=samesite,
        )
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE, refresh_token, max_age=max_age, path='/',
            httponly=True, secure=secure, samesite=samesite,
        )
    return response


def _clear_jwt_cookies(response):
    """Delete the JWT cookies from a response (used on logout)."""
    response.delete_cookie(ACCESS_COOKIE, path='/')
    response.delete_cookie(REFRESH_COOKIE, path='/')
    return response


def _resolve_user_from_jwt_token(raw_token):
    """Validate a JWT access token and return the matching users.User.

    Used by JwtCookieAuthentication and the page-protection middleware to
    resolve the authenticated user from an access-token cookie/string without
    re-implementing signature + expiry checks.
    """
    if not raw_token:
        return None
    try:
        validated = _SimpleJwtAuth().get_validated_token(raw_token)
    except Exception:
        return None
    user_id = validated.get('user_id')
    if user_id is None:
        return None
    try:
        user = User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        return None
    if not user.is_active:
        return None
    return user


def refresh_access_from_refresh_token(raw_refresh, user=None):
    """Return a fresh access-token string from a valid refresh token.

    Used for silent browser refresh: when the access cookie has expired but a
    valid refresh cookie remains, mint a new access token and (optionally) a
    new refresh token. On the auth ``/token/refresh/`` endpoint too, we could
    reuse this, but here it backs the middleware. Returns ``None`` if the
    refresh token is invalid/expired or its user is inactive.
    """
    if not raw_refresh:
        return None
    from rest_framework_simplejwt.tokens import RefreshToken
    try:
        refresh = RefreshToken(raw_refresh)
    except Exception:
        return None
    if user is None:
        target = refresh.get('user_id')
        try:
            user = User.objects.get(pk=target)
        except (User.DoesNotExist, ValueError, TypeError):
            return None
    if user is None or not user.is_active:
        return None
    return {
        'access': str(refresh.access_token),
        'user': user,
    }


def _csrf_required(request) -> bool:
    """
    Whether CSRF enforcement should apply for this request.

    Always returns True: DRF's SessionAuthentication does not add CSRF
    protection against cross-site requests by default (it skips the check
    for non-authenticated or GET requests), so authenticated browser
    sessions must perform the csrfmiddlewaretoken/X-CSRFToken check on
    every unsafe method. The page frontends already forward the token
    (see static/js fetch helpers); local API clients can read the
    csrftoken cookie after login when CSRF_COOKIE_HTTPONLY=False (the
    settings default).

    Regression tests use APIClient(enforce_csrf_checks=True) to prove
    unsafe methods are rejected without the token.
    """
    return True


class UserSessionAuthentication(SessionAuthentication):
    """
    Resolve ``request.user`` from the Django session via users.User id.

    Behaves like DRF's SessionAuthentication (CSRF-protected, relies on the
    session cookie) but reads our own session key and models an
    authenticated ``users.User``.  Used for server-rendered pages.
    """

    def authenticate(self, request):
        user = getattr(request._request, 'user', None)

        # Dashboard pages use Django's login view. When that authenticated
        # web account has a matching application user, resolve the latter so
        # role-aware APIs see OWNER/ACCOUNTANT and financial FK attribution
        # uses the schema-backed users table.
        if user and not getattr(user, 'is_anonymous', True):
            web_user = user
            try:
                user = User.objects.get(username=user.username, is_active=True)
            except User.DoesNotExist:
                user = self._finance_identity_for_web_user(web_user)

        if not user or not getattr(user, 'is_active', False):
            user = self._resolve_from_session(request)

        if user is None or getattr(user, 'is_anonymous', True) or not user.is_active:
            return None

        if _csrf_required(request):
            self.enforce_csrf(request)

        request._request.user = user
        return user, None

    @staticmethod
    def _finance_identity_for_web_user(web_user):
        """Bridge Django administrators to the schema-backed OWNER role.

        The dashboard historically used Django's auth table while APIs use
        the SQL-source-of-truth ``users`` table. A Django superuser is the
        dashboard's Owner equivalent, so ensure it has a matching API
        identity. Ordinary Django users are left unchanged and therefore do
        not gain finance permissions.
        """
        if not getattr(web_user, 'is_superuser', False):
            return web_user

        email = (getattr(web_user, 'email', '') or '').strip()
        if email:
            existing = User.objects.filter(email__iexact=email, is_active=True).first()
            if existing is not None:
                return existing

        try:
            with transaction.atomic():
                return User.objects.create(
                    username=web_user.username,
                    email=email or f'{web_user.username}@dashboard.local',
                    password_hash=web_user.password,
                    first_name=web_user.first_name or 'Dashboard',
                    last_name=web_user.last_name or 'Owner',
                    role=Role.OWNER,
                    is_active=True,
                )
        except IntegrityError:
            # A simultaneous first request may have created it already.
            return User.objects.get(username=web_user.username, is_active=True)

    def _resolve_from_session(self, request):
        session = getattr(request._request, 'session', None)
        if session is None:
            return None
        user_id = session.get(SESSION_USER_ID_KEY)
        if user_id is None:
            return None
        try:
            return User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError):
            return None

    def authenticate_header(self, request):
        return 'Session'


class JwtUserAuthentication(_SimpleJwtAuth):
    """
    JWT authentication that resolves against ``users.User`` instead of
    ``AUTH_USER_MODEL``.

    simplejwt's default ``JWTAuthentication.get_user()`` calls
    ``get_user_model().objects.get(**{pk_field: user_id})``.  Because
    ``users.User`` is NOT ``AUTH_USER_MODEL``, that lookup fails with
    integer/UUID type mismatches.  This subclass overrides ``get_user``
    to query our custom model directly.
    """

    def get_user(self, validated_token):
        user_id = validated_token.get('user_id')
        if user_id is None:
            return None
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class JwtCookieAuthentication(_SimpleJwtAuth):
    """
    DRF authentication that reads the JWT access token from an HttpOnly
    cookie instead of the Authorization header.

    The browser receives the pair as HttpOnly cookies at login, so it sends
    them automatically on every request. This class lets the DRF API trust
    that cookie just like it would a ``Bearer`` header -- no client-side JS
    has to read or attach tokens. Resolves ``users.User`` (UUID PK), same as
    ``JwtUserAuthentication``.
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get(ACCESS_COOKIE)
        if not raw_token:
            return None
        user = _resolve_user_from_jwt_token(raw_token)
        if user is None:
            return None
        # Unlike an Authorization header, browsers attach auth cookies to
        # cross-site requests automatically. Require a matching CSRF token
        # before accepting this cookie as a credential.
        SessionAuthentication().enforce_csrf(request)
        return user, None
