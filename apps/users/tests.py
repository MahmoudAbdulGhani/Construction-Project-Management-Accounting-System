"""
Tests for the ``users`` app -- Authentication & Authorization (RBAC).

Covers:
- Service/model: password hashing (set_password/check_password), role flags,
  and the stateless reset-token generator.
- Auth API: login (JWT), logout, profile (get/patch),
  change-password, token refresh.
- Password reset API: request (emails a reset link) and complete (reset
  with uid + token).
- RBAC: non-Owner users cannot reach Owner-only user management.

The in-memory SQLite test DB doesn't provision the (managed=False) users
table, so every test class mixes in ``WithUsersTableMixin`` to create it
for the duration of the class, mirroring the other domain apps.
"""
from django.core import mail
from django.test import Client, TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Role, User
from users.testing import WithUsersTableMixin
from users.tokens import default_token_generator


def _make_password():
    user = User(username="pw", email="pw@example.com", password_hash="x",
                first_name="P", last_name="W", role=Role.OWNER)
    user.set_password("correct-horse-battery-staple")
    user.save()
    return user


class PasswordHashingTests(WithUsersTableMixin, TestCase):
    def test_set_password_hashes_not_plaintext(self):
        user = _make_password()
        self.assertNotEqual(user.password_hash, "correct-horse-battery-staple")
        self.assertTrue(user.check_password("correct-horse-battery-staple"))
        self.assertFalse(user.check_password("wrong"))

    def test_role_flags(self):
        owner = _make_password()
        owner.role = Role.OWNER
        self.assertTrue(owner.is_owner)
        self.assertFalse(owner.is_accountant)
        owner.role = Role.ACCOUNTANT
        self.assertTrue(owner.is_accountant)
        self.assertFalse(owner.is_owner)


class AuthApiBase(WithUsersTableMixin, TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User(username="owner", email="owner@example.com",
                          first_name="O", last_name="W", role=Role.OWNER)
        self.owner.set_password("owner-pass-123")
        self.owner.save()
        self.acc = User(username="accountant", email="acc@example.com",
                        first_name="A", last_name="C", role=Role.ACCOUNTANT)
        self.acc.set_password("acc-pass-123")
        self.acc.save()

    def login(self, username, password):
        """Login and set the Bearer token header on the client."""
        resp = self.client.post("/api/auth/login/",
                                {"username": username, "password": password},
                                format="json")
        if resp.status_code == status.HTTP_200_OK:
            token = resp.data["access"]
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return resp


class LoginLogoutTests(AuthApiBase):
    def test_login_returns_jwt_tokens(self):
        resp = self.login("owner", "owner-pass-123")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertIsInstance(resp.data["access"], str)
        self.assertIsInstance(resp.data["refresh"], str)

    def test_login_is_case_insensitive_on_username(self):
        resp = self.login("OWNER", "owner-pass-123")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_login_by_email_is_not_supported(self):
        resp = self.login("owner@example.com", "owner-pass-123")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_wrong_password_fails(self):
        resp = self.login("owner", "wrong-password")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_inactive_user_fails(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        resp = self.login("owner", "owner-pass-123")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_me_works_with_bearer_token(self):
        self.login("owner", "owner-pass-123")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data["username"], "owner")

    def test_me_fails_without_token(self):
        self.client.credentials()  # clear any credentials
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_succeeds(self):
        self.login("owner", "owner-pass-123")
        logout_resp = self.client.post("/api/auth/logout/")
        self.assertEqual(logout_resp.status_code, status.HTTP_200_OK)

    def test_token_refresh_returns_new_access(self):
        resp = self.login("owner", "owner-pass-123")
        refresh = resp.data["refresh"]
        refresh_resp = self.client.post("/api/auth/token/refresh/",
                                        {"refresh": refresh}, format="json")
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_resp.data)

class MeProfileTests(AuthApiBase):
    def test_unauthenticated_me_fails(self):
        self.client.credentials()
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_profile_valid(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.patch("/api/auth/me/",
                                 {"phone": "5551234", "first_name": "Olivia"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["first_name"], "Olivia")
        self.assertEqual(resp.data["phone"], "5551234")

    def test_patch_profile_cannot_escalate_role(self):
        self.login("accountant", "acc-pass-123")
        resp = self.client.patch("/api/auth/me/", {"role": Role.OWNER}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.acc.refresh_from_db()
        self.assertEqual(self.acc.role, Role.ACCOUNTANT)


class ChangePasswordTests(AuthApiBase):
    def test_change_password(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.post("/api/auth/change-password/",
                                {"old_password": "owner-pass-123",
                                 "new_password": "brand-new-pass-456"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("brand-new-pass-456"))

    def test_change_password_wrong_current(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.post("/api/auth/change-password/",
                                {"old_password": "nope", "new_password": "brand-new-pass-456"},
                                format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class PasswordResetTests(AuthApiBase):
    def test_request_reset_sends_email_with_link(self):
        resp = self.client.post("/api/auth/request-password-reset/",
                                {"email": "owner@example.com"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("owner@example.com", mail.outbox[0].to)
        self.assertIn("reset", mail.outbox[0].subject.lower())

    def test_request_reset_unknown_email_success_but_no_email(self):
        resp = self.client.post("/api/auth/request-password-reset/",
                                {"email": "nobody@example.com"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_complete_reset_with_valid_uid_and_token(self):
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        token = default_token_generator.make_token(self.owner)
        resp = self.client.post("/api/auth/reset-password/",
                                {"uid": uid, "token": token,
                                 "new_password": "fresh-password-789"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("fresh-password-789"))

    def test_complete_reset_with_invalid_token(self):
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        resp = self.client.post("/api/auth/reset-password/",
                                {"uid": uid, "token": "bad-token",
                                 "new_password": "fresh-password-789"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("owner-pass-123"))


class UserManagementRbacTests(AuthApiBase):
    def test_unauthenticated_cannot_list_users(self):
        self.client.credentials()
        resp = self.client.get("/api/auth/users/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_accountant_cannot_manage_users(self):
        self.login("accountant", "acc-pass-123")
        resp = self.client.get("/api/auth/users/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        create = self.client.post("/api/auth/users/",
                                  {"username": "hacker", "email": "h@example.com",
                                   "first_name": "H", "last_name": "K",
                                   "role": Role.ACCOUNTANT, "password": "password-123"},
                                  format="json")
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_register_user(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.post("/api/auth/users/",
                                {"username": "newusr", "email": "new@example.com",
                                 "first_name": "New", "last_name": "User",
                                 "role": Role.ACCOUNTANT, "password": "password-123"},
                                format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["username"], "newusr")
        self.assertNotIn("password", resp.data)
        created = User.objects.get(username="newusr")
        self.assertTrue(created.check_password("password-123"))

    def test_owner_can_deactivate_and_activate(self):
        self.login("owner", "owner-pass-123")
        deact = self.client.post(f"/api/auth/users/{self.acc.pk}/deactivate/")
        self.assertEqual(deact.status_code, status.HTTP_200_OK)
        self.acc.refresh_from_db()
        self.assertFalse(self.acc.is_active)
        act = self.client.post(f"/api/auth/users/{self.acc.pk}/activate/")
        self.assertEqual(act.status_code, status.HTTP_200_OK)
        self.acc.refresh_from_db()
        self.assertTrue(self.acc.is_active)

    def test_create_auto_generates_username_and_password(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.post("/api/auth/users/",
                                {"first_name": "First", "last_name": "User",
                                 "role": Role.ACCOUNTANT,
                                 "email": "first.user@gmail.com"},
                                format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["username"], "first-user")
        self.assertEqual(resp.data["email"], "first.user@gmail.com")
        self.assertNotIn("password", resp.data)
        created = User.objects.get(username="first-user")
        self.assertTrue(created.password_hash)
        self.assertFalse(created.check_password("first-user"))

    def test_create_requires_email(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.post("/api/auth/users/",
                                {"first_name": "First", "last_name": "User",
                                 "role": Role.ACCOUNTANT},
                                format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_emails_credentials_to_supplied_email(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.post("/api/auth/users/",
                                {"first_name": "Mail", "last_name": "Recipient",
                                 "role": Role.OWNER,
                                 "email": "mail.recipient@gmail.com"},
                                format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["mail.recipient@gmail.com"])
        self.assertIn("Username:", mail.outbox[0].body)
        self.assertIn("Password:", mail.outbox[0].body)

    def test_create_with_explicit_username_email_password(self):
        self.login("owner", "owner-pass-123")
        resp = self.client.post("/api/auth/users/",
                                {"username": "explicit", "email": "explicit@example.com",
                                 "first_name": "Ex", "last_name": "Plicit",
                                 "role": Role.ACCOUNTANT, "password": "explicit-pass-123"},
                                format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["username"], "explicit")
        created = User.objects.get(username="explicit")
        self.assertTrue(created.check_password("explicit-pass-123"))


class AppUserSessionBridgingTests(WithUsersTableMixin, TestCase):
    """
    AppUserSessionMiddleware must present the app's ``users.User`` as
    ``request.user`` -- never Django's built-in auth.User -- so that role-
    based dashboard views (``request.user.is_owner`` /
    ``request.user.is_accountant``) work even when the visitor signed in
    through the Django admin and has no app session key.

    Regression: a Django auth.User attached by AuthenticationMiddleware lacks
    ``is_accountant`` and would crash ``apps.core.views.dashboard`` with an
    AttributeError.
    """

    def _app_user(self, username="owner", role=Role.OWNER):
        return User.objects.create(
            username=username, email=f"{username}@example.com",
            password_hash="x", first_name="O", last_name="W", role=role,
        )

    def test_django_auth_user_is_bridged_to_app_user(self):
        from django.contrib.auth.models import User as DjangoUser
        from django.test import RequestFactory

        from .middleware import AppUserSessionMiddleware

        self._app_user("mwb_owner", Role.OWNER)
        django_user = DjangoUser.objects.create_user(username="mwb_owner", password="pass12345")

        factory = RequestFactory()
        request = factory.get("/dashboard/")
        request.user = django_user

        captured = {}

        def get_response(req):
            captured["user"] = req.user
            return "ok"

        middleware = AppUserSessionMiddleware(get_response)
        middleware(request)
        self.assertEqual(captured["user"].username, "mwb_owner")
        self.assertTrue(captured["user"].is_owner)

    def test_django_auth_user_without_matching_app_user_is_left_alone(self):
        from django.contrib.auth.models import User as DjangoUser
        from django.test import RequestFactory

        from .middleware import AppUserSessionMiddleware

        django_user = DjangoUser.objects.create_user(username="no_match", password="pass12345")
        factory = RequestFactory()
        request = factory.get("/dashboard/")
        request.user = django_user

        captured = {}

        def get_response(req):
            captured["user"] = req.user
            return "ok"

        AppUserSessionMiddleware(get_response)(request)
        # no app users.User matches, so the Django user is left authenticating
        self.assertEqual(captured["user"], django_user)


class SessionAuthCsrfEnforcementTests(WithUsersTableMixin, TestCase):
    """
    Phase-1 hardening regression: ``UserSessionAuthentication`` enforces
    CSRF on authenticated unsafe methods UNCONDITIONALLY -- even when
    Django runs with DEBUG=True (it previously relaxed the check in
    DEBUG). Uses ``APIClient(enforce_csrf_checks=True)`` so CSRF is
    actually verified for the DRF session-authenticated request, exactly
    as it is in production.

    The web login view writes both the Django session and HttpOnly JWT
    cookies; the API client here deliberately forwards only the session
    cookie (+ csrftoken), so the request authenticates through
    UserSessionAuthentication -- the same path every browser-driven
    fetch on the dashboard uses -- rather than via a JWT cookie, which
    is not CSRF-relevant by design.
    """

    def setUp(self):
        self.user = User.objects.create(
            username="csrfowner", email="csrfowner@example.com", password_hash="x",
            first_name="C", last_name="O", role=Role.OWNER,
        )
        self.user.set_password("csrf-pass-123")
        self.user.save(update_fields=["password_hash"])

    def _login(self):
        """Log in through the server-rendered login page and return:
        (sessionid, csrftoken) -- the session cookie plus the CSRF cookie."""
        boot = Client()
        page = boot.get("/accounts/login/")
        csrftoken = page.cookies["csrftoken"].value
        resp = boot.post(
            "/accounts/login/",
            {"username": "csrfowner", "password": "csrf-pass-123",
             "csrfmiddlewaretoken": csrftoken},
        )
        # Login redirects to the dashboard after a successful auth.
        self.assertEqual(resp.status_code, 302)
        sessionid = boot.cookies["sessionid"].value
        return sessionid, csrftoken

    def _session_api_client(self, csrftoken):
        """An APIClient with enforced CSRF carrying only the session cookie."""
        client = APIClient(enforce_csrf_checks=True)
        if csrftoken:
            client.cookies["csrftoken"] = csrftoken
        return client

    def test_unsafe_post_without_csrf_token_is_rejected(self):
        sessionid, csrftoken = self._login()
        client = self._session_api_client(csrftoken)
        client.cookies["sessionid"] = sessionid
        # Deliberately no X-CSRFToken header: mark_all_read is a POST and
        # therefore unsafe, so without the token the session-authenticated
        # request must be refused -- this is the core regression.
        response = client.post("/api/notifications/notifications/mark_all_read/")
        self.assertEqual(response.status_code, 403)

    def test_unsafe_post_with_valid_csrf_token_succeeds(self):
        sessionid, csrftoken = self._login()
        client = self._session_api_client(csrftoken)
        client.cookies["sessionid"] = sessionid
        response = client.post(
            "/api/notifications/notifications/mark_all_read/",
            HTTP_X_CSRFTOKEN=csrftoken,
        )
        self.assertEqual(response.status_code, 200)

    def test_safe_get_does_not_require_csrf_token(self):
        sessionid, csrftoken = self._login()
        client = self._session_api_client(csrftoken)
        client.cookies["sessionid"] = sessionid
        response = client.get("/api/notifications/notifications/?is_read=false")
        self.assertEqual(response.status_code, 200)

    def test_unsafe_jwt_cookie_post_without_csrf_token_is_rejected(self):
        boot = Client()
        page = boot.get("/accounts/login/")
        csrftoken = page.cookies["csrftoken"].value
        response = boot.post(
            "/accounts/login/",
            {"username": "csrfowner", "password": "csrf-pass-123",
             "csrfmiddlewaretoken": csrftoken},
        )
        self.assertEqual(response.status_code, 302)

        client = APIClient(enforce_csrf_checks=True)
        client.cookies["access_token"] = boot.cookies["access_token"].value
        response = client.post("/api/notifications/notifications/mark_all_read/")
        self.assertEqual(response.status_code, 403)

    def test_unsafe_jwt_cookie_post_with_csrf_token_succeeds(self):
        boot = Client()
        page = boot.get("/accounts/login/")
        csrftoken = page.cookies["csrftoken"].value
        response = boot.post(
            "/accounts/login/",
            {"username": "csrfowner", "password": "csrf-pass-123",
             "csrfmiddlewaretoken": csrftoken},
        )
        self.assertEqual(response.status_code, 302)

        client = APIClient(enforce_csrf_checks=True)
        client.cookies["access_token"] = boot.cookies["access_token"].value
        client.cookies["csrftoken"] = csrftoken
        response = client.post(
            "/api/notifications/notifications/mark_all_read/",
            HTTP_X_CSRFTOKEN=csrftoken,
        )
        self.assertEqual(response.status_code, 200)
