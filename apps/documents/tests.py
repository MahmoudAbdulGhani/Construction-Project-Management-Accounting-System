"""
Tests for the ``documents`` app -- Document Management (CPMAS-25).

Organized into:
- Model tests: basic sanity (str, ordering).
- API tests: upload (multipart), list/filter, metadata-only update,
  destroy (including the underlying file being removed from storage),
  and the read-only/locked fields (file_name/file_path/uploaded_by,
  entity_type/entity_id once created).
"""
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.models import User
from users.testing import WithUsersTableMixin

from . import storage
from .models import Document


class DocumentsTestBase(WithUsersTableMixin, TestCase):
    """Shared fixtures: an uploader user and an authenticated APIClient.

    Documents always use local disk (MEDIA_ROOT) here -- the Supabase
    Storage branch is exercised separately in SupabaseDocumentStorageAPITests
    with the HTTP layer mocked, so a local .env with real Supabase keys
    never causes the suite to touch the live bucket.
    """

    def setUp(self):
        self._storage_override = override_settings(SUPABASE_DOCUMENT_STORAGE=False)
        self._storage_override.enable()
        self.uploader = User.objects.create(
            username="uploader", email="uploader@example.com", password_hash="x",
            first_name="U", last_name="P", role="OWNER",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.uploader)

    def tearDown(self):
        # Clean up any files written to MEDIA_ROOT during a test.
        for doc in Document.objects.all():
            default_storage.delete(doc.file_path)
        self._storage_override.disable()

    def upload(self, entity_type="project", entity_id=None, document_type="CONTRACT", content=b"hello world", name="contract.pdf"):
        entity_id = entity_id or "11111111-1111-1111-1111-111111111111"
        upload_file = SimpleUploadedFile(name, content, content_type="application/pdf")
        return self.client.post("/api/documents/documents/", {
            "file": upload_file, "entity_type": entity_type, "entity_id": entity_id,
            "document_type": document_type,
        }, format="multipart")


class DocumentModelTests(TestCase):
    def test_str_returns_file_name(self):
        doc = Document(file_name="invoice.pdf")
        self.assertEqual(str(doc), "invoice.pdf")


class DocumentUploadAPITests(DocumentsTestBase):
    def test_upload_creates_document_with_derived_fields(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["file_name"], "contract.pdf")
        self.assertEqual(data["file_type"], "application/pdf")
        self.assertEqual(data["file_size"], len(b"hello world"))
        self.assertEqual(data["entity_type"], "project")
        self.assertEqual(data["uploaded_by"], str(self.uploader.id))
        self.assertIn("uploaded_by_name", data)
        self.assertTrue(data["file_url"].startswith("/media/"))

        # The file was actually written to storage.
        doc = Document.objects.get(pk=data["id"])
        self.assertTrue(default_storage.exists(doc.file_path))

    def test_uploaded_by_is_taken_from_the_authenticated_user_not_client_input(self):
        other = User.objects.create(
            username="other", email="other@example.com", password_hash="x",
            first_name="O", last_name="T", role="OWNER",
        )
        response = self.client.post("/api/documents/documents/", {
            "file": SimpleUploadedFile("x.txt", b"x"), "entity_type": "project",
            "entity_id": "11111111-1111-1111-1111-111111111111", "uploaded_by": str(other.id),
        }, format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["uploaded_by"], str(self.uploader.id))

    def test_invalid_entity_type_is_rejected(self):
        response = self.upload(entity_type="not_a_real_entity")
        self.assertEqual(response.status_code, 400)
        self.assertIn("entity_type", response.json())

    def test_unauthenticated_upload_is_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.upload()
        self.assertEqual(response.status_code, 401)


class DocumentListAPITests(DocumentsTestBase):
    def test_filter_by_entity_type_and_entity_id(self):
        self.upload(entity_type="project", entity_id="11111111-1111-1111-1111-111111111111")
        self.upload(entity_type="supplier", entity_id="22222222-2222-2222-2222-222222222222")

        response = self.client.get("/api/documents/documents/?entity_type=project&entity_id=11111111-1111-1111-1111-111111111111")
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["entity_type"], "project")

    def test_filter_by_document_type(self):
        self.upload(document_type="CONTRACT")
        self.upload(document_type="RECEIPT")

        response = self.client.get("/api/documents/documents/?document_type=RECEIPT")
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["document_type"], "RECEIPT")


class DocumentUpdateAPITests(DocumentsTestBase):
    def test_document_type_is_patchable(self):
        doc_id = self.upload(document_type="CONTRACT").json()["id"]
        response = self.client.patch(f"/api/documents/documents/{doc_id}/", {"document_type": "INVOICE"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["document_type"], "INVOICE")

    def test_entity_type_cannot_be_changed(self):
        doc_id = self.upload(entity_type="project").json()["id"]
        response = self.client.patch(f"/api/documents/documents/{doc_id}/", {"entity_type": "supplier"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_put_is_not_allowed(self):
        doc_id = self.upload().json()["id"]
        response = self.client.put(f"/api/documents/documents/{doc_id}/", {"document_type": "INVOICE"}, format="json")
        self.assertEqual(response.status_code, 405)


class DocumentDownloadAPITests(DocumentsTestBase):
    def test_download_streams_the_stored_file_as_an_attachment(self):
        doc_id = self.upload(name="contract.pdf", content=b"%PDF-1.4 test").json()["id"]
        response = self.client.get(f"/api/documents/documents/{doc_id}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="contract.pdf"', response["Content-Disposition"])

    def test_download_404s_with_json_when_the_file_is_missing_from_storage(self):
        doc_id = self.upload().json()["id"]
        doc = Document.objects.get(pk=doc_id)
        default_storage.delete(doc.file_path)  # simulate a file lost from storage

        response = self.client.get(f"/api/documents/documents/{doc_id}/download/")
        self.assertEqual(response.status_code, 404)


SUPABASE_SETTINGS = dict(
    SUPABASE_DOCUMENT_STORAGE=True,
    SUPABASE_URL="https://xyz.supabase.co",
    SUPABASE_SERVICE_ROLE_KEY="service-key",
    SUPABASE_ANON_KEY="anon-key",
    SUPABASE_DOCUMENTS_BUCKET="documents",
)


class SupabaseDocumentStorageAPITests(WithUsersTableMixin, TestCase):
    """The Supabase Storage branch of upload/retrieve/download/destroy.

    ``urllib.request.urlopen`` is mocked (no network, no live bucket); these
    verify the requests are shaped correctly and that the API behaves over
    Supabase storage. Local-disk behavior stays covered by the base tests.
    """

    def setUp(self):
        storage._checked_buckets.clear()  # each test re-exercises bucket creation
        self.uploader = User.objects.create(
            username="uploader", email="uploader@example.com", password_hash="x",
            first_name="U", last_name="P", role="OWNER",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.uploader)

    def tearDown(self):
        # Clean up any local-media writes left by the legacy-fallback test.
        for doc in Document.objects.all():
            default_storage.delete(doc.file_path)
        default_storage.delete("documents/contract.pdf")
        storage._checked_buckets.clear()

    def _ok(self, urlopen, body=b"{}", status=201):
        fake = mock.MagicMock()
        fake.status = status
        fake.read.return_value = body
        urlopen.return_value.__enter__.return_value = fake

    def _header(self, request, name):
        for key, value in dict(getattr(request, "headers", {}) or {}).items():
            if key.lower() == name.lower():
                return value
        return None

    def _upload(self, urlopen, name="contract.pdf", content=b"%PDF-1.4 test"):
        self._ok(urlopen, status=201)
        return self.client.post("/api/documents/documents/", {
            "file": SimpleUploadedFile(name, content, content_type="application/pdf"),
            "entity_type": "project",
            "entity_id": "11111111-1111-1111-1111-111111111111",
        }, format="multipart"), urlopen

    def test_upload_with_supabase_storage_posts_to_the_documents_bucket(self):
        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                response, urlopen = self._upload(urlopen)

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["file_url"].startswith(
            "https://xyz.supabase.co/storage/v1/object/public/documents/"
        ))
        # First call creates the bucket, second uploads the object.
        upload_call = urlopen.call_args_list[1].args[0]
        self.assertEqual(upload_call.get_method(), "POST")
        self.assertTrue(upload_call.full_url.startswith(
            "https://xyz.supabase.co/storage/v1/object/documents/"
        ))
        self.assertTrue(upload_call.full_url.endswith("/contract.pdf"))
        self.assertEqual(upload_call.get_header("Authorization"), "Bearer service-key")
        self.assertEqual(self._header(upload_call, "content-type"), "application/pdf")

        doc = Document.objects.get(pk=data["id"])
        # file_path is the object key, not a served URL, and nothing was
        # written to local media.
        self.assertNotIn("documents/", doc.file_path)
        self.assertIn("/contract.pdf", doc.file_path)
        self.assertFalse(default_storage.exists(doc.file_path))

    def test_download_streams_supabase_bytes_as_an_attachment(self):
        doc_id = None
        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                response, _ = self._upload(urlopen)
                doc_id = response.json()["id"]
            with mock.patch("urllib.request.urlopen") as urlopen:
                self._ok(urlopen, body=b"%PDF-1.4 test bytes", status=200)
                dl = self.client.get(f"/api/documents/documents/{doc_id}/download/")

        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, b"%PDF-1.4 test bytes")
        self.assertEqual(dl["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="contract.pdf"', dl["Content-Disposition"])
        read_call = urlopen.call_args.args[0]
        self.assertTrue(read_call.full_url.startswith(
            "https://xyz.supabase.co/storage/v1/object/authenticated/documents/"
        ))

    def test_download_404s_when_supabase_object_is_missing(self):
        doc_id = None
        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                response, _ = self._upload(urlopen)
                doc_id = response.json()["id"]
            with mock.patch("urllib.request.urlopen") as urlopen:
                self._ok(urlopen, body=b'{"message":"404"}', status=404)
                dl = self.client.get(f"/api/documents/documents/{doc_id}/download/")

        self.assertEqual(dl.status_code, 404)

    def test_download_falls_back_to_local_disk_for_legacy_rows(self):
        # A row created before Supabase storage has a "documents/<file>" path
        # and its bytes on local disk. Storage is now configured, but the
        # download must still serve the local bytes instead of trying (and
        # failing on) a Supabase object that never existed.
        doc_id = None
        name = "contract.pdf"
        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                response, _ = self._upload(urlopen)
                doc_id = response.json()["id"]
                Document.objects.filter(pk=doc_id).update(file_path=f"documents/{name}")
            default_storage.save(f"documents/{name}", SimpleUploadedFile(name, b"%PDF-1.4 test"))
            with mock.patch("urllib.request.urlopen") as urlopen:
                dl = self.client.get(f"/api/documents/documents/{doc_id}/download/")
        dl_bytes = b"".join(dl.streaming_content)
        dl.close()

        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl_bytes, b"%PDF-1.4 test")

    def test_destroy_deletes_the_supabase_object(self):
        doc_id = None
        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                response, _ = self._upload(urlopen)
                doc_id = response.json()["id"]
            with mock.patch("urllib.request.urlopen") as urlopen:
                self._ok(urlopen, status=200)
                dr = self.client.delete(f"/api/documents/documents/{doc_id}/")

        self.assertEqual(dr.status_code, 204)
        delete_call = urlopen.call_args.args[0]
        self.assertEqual(delete_call.get_method(), "DELETE")
        self.assertTrue(delete_call.full_url.startswith(
            "https://xyz.supabase.co/storage/v1/object/documents/"
        ))
        self.assertFalse(Document.objects.filter(pk=doc_id).exists())

    def test_upload_returns_400_not_500_when_storage_upload_fails(self):
        # A storage outage/timeout must surface as an actionable 400 with
        # the reason on "file" -- not an opaque 500 -- and must not leave a
        # row behind.
        import urllib.error

        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                urlopen.side_effect = urllib.error.URLError("storage down")
                response = self.client.post("/api/documents/documents/", {
                    "file": SimpleUploadedFile("contract.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
                    "entity_type": "project",
                    "entity_id": "11111111-1111-1111-1111-111111111111",
                }, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())
        self.assertFalse(Document.objects.exists())

    def test_upload_url_encodes_spaces_in_the_object_key(self):
        # A file whose name contains spaces (e.g. "RCT-PAY-2026-0006 _1_.pdf")
        # used to crash with http.client.InvalidURL (raw space in the request
        # path) -> 500. The object key must be URL-encoded everywhere the
        # storage API is called, while the DB keeps the readable name.
        name = "RCT-PAY-2026-0006 _1_.pdf"
        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                self._ok(urlopen, status=201)
                response = self.client.post("/api/documents/documents/", {
                    "file": SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf"),
                    "entity_type": "client",
                    "entity_id": "11111111-1111-1111-1111-111111111111",
                }, format="multipart")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        # Display URL is percent-encoded; no raw space survives in the URL.
        self.assertIn("%20", data["file_url"])
        self.assertNotIn(" ", data["file_url"])

        # First call creates the bucket, second uploads the object.
        upload_call = urlopen.call_args_list[1].args[0]
        self.assertEqual(upload_call.get_method(), "POST")
        self.assertIn("%20", upload_call.full_url)
        self.assertNotIn(" ", upload_call.full_url)
        self.assertTrue(upload_call.full_url.endswith(f"/{name.replace(' ', '%20')}"))

        doc = Document.objects.get(pk=data["id"])
        # The stored key keeps the readable spaced name; only URLs are quoted.
        self.assertIn(name, doc.file_path)
        self.assertFalse(default_storage.exists(doc.file_path))

    def test_download_and_destroy_encode_spaces_in_the_object_key(self):
        # read_document/delete_document must also quote keys so a spaced-name
        # document can be downloaded and removed -- not 500 InvalidURL.
        name = "RCT-PAY-2026-0006 _1_.pdf"
        doc_id = None
        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                self._ok(urlopen, status=201)
                response = self.client.post("/api/documents/documents/", {
                    "file": SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf"),
                    "entity_type": "client",
                    "entity_id": "11111111-1111-1111-1111-111111111111",
                }, format="multipart")
                doc_id = response.json()["id"]

            with mock.patch("urllib.request.urlopen") as urlopen:
                self._ok(urlopen, body=b"%PDF-1.4 test bytes", status=200)
                dl = self.client.get(f"/api/documents/documents/{doc_id}/download/")
            self.assertEqual(dl.status_code, 200)
            self.assertEqual(dl.content, b"%PDF-1.4 test bytes")
            read_call = urlopen.call_args.args[0]
            self.assertIn("%20", read_call.full_url)
            self.assertNotIn(" ", read_call.full_url)

            with mock.patch("urllib.request.urlopen") as urlopen:
                self._ok(urlopen, status=200)
                dr = self.client.delete(f"/api/documents/documents/{doc_id}/")
            self.assertEqual(dr.status_code, 204)
            delete_call = urlopen.call_args.args[0]
            self.assertEqual(delete_call.get_method(), "DELETE")
            self.assertIn("%20", delete_call.full_url)
            self.assertNotIn(" ", delete_call.full_url)

    def test_upload_returns_400_not_500_when_the_object_url_is_malformed(self):
        # http.client.InvalidURL (a raw space/control char in a URL path) is
        # NOT a URLError -- it escaped _request as a 500 before. It must now
        # be wrapped as a SupabaseStorageError and surface as a clean 400.
        import http.client

        with override_settings(**SUPABASE_SETTINGS):
            with mock.patch("urllib.request.urlopen") as urlopen:
                urlopen.side_effect = http.client.InvalidURL(
                    "URL can't contain control characters. '/storage/v1/object/...' (found at least ' ')"
                )
                response = self.client.post("/api/documents/documents/", {
                    "file": SimpleUploadedFile("contract.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
                    "entity_type": "project",
                    "entity_id": "11111111-1111-1111-1111-111111111111",
                }, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())
        self.assertFalse(Document.objects.exists())


class UploaderIdentityTests(WithUsersTableMixin, TestCase):
    """The uploaded_by identity bridge (Django auth sessions -> users.User)."""

    def test_passthrough_for_an_existing_users_user(self):
        from django.contrib.auth.models import User as DjangoUser
        from users.models import User

        app_user = User.objects.create(
            username="appuser", email="app@example.com", password_hash="x",
            first_name="A", last_name="P", role="OWNER",
        )
        django_user = DjangoUser(username="appuser", password="x")
        from .views import _resolve_uploader
        self.assertEqual(_resolve_uploader(django_user), app_user)

    def test_bridges_a_superuser_django_account_to_an_owner(self):
        from django.contrib.auth.models import User as DjangoUser

        django_user = DjangoUser(
            username="boss", email="boss@example.com", password="x",
            first_name="B", last_name="O", is_superuser=True,
        )
        from users.models import Role, User
        from .views import _resolve_uploader
        resolved = _resolve_uploader(django_user)
        self.assertEqual(resolved.username, "boss")
        self.assertEqual(resolved.role, Role.OWNER)

    def test_bridges_a_nonsuperuser_django_account_to_an_accountant(self):
        from django.contrib.auth.models import User as DjangoUser

        django_user = DjangoUser(
            username="smokeuser", email="smoke@example.com", password="x",
            first_name="S", last_name="U", is_superuser=False,
        )
        from users.models import Role, User
        from .views import _resolve_uploader
        resolved = _resolve_uploader(django_user)
        self.assertEqual(resolved.username, "smokeuser")
        self.assertEqual(resolved.role, Role.ACCOUNTANT)
        # Idempotent: a second call reuses the bridged identity.
        self.assertEqual(_resolve_uploader(django_user), resolved)

    def test_anonymous_session_is_a_clear_400_not_a_500(self):
        from .views import _resolve_uploader
        with self.assertRaisesMessage(Exception, "No user account is attached"):
            _resolve_uploader(None)


class DocumentUploadWithDjangoAuthSessionTests(DocumentsTestBase):
    """A dashboard session authenticated as a plain Django auth.User must be
    able to upload -- the uploader identity is bridged into a users.User."""

    def test_upload_bridges_a_nonsuperuser_django_account(self):
        from django.contrib.auth.models import User as DjangoUser
        from users.models import User

        django_user = DjangoUser.objects.create_user(
            username="dash-uploader", email="dash@example.com", password="x"
        )
        self.client.force_authenticate(user=django_user)
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        bridged = User.objects.get(username="dash-uploader")
        self.assertEqual(response.json()["uploaded_by"], str(bridged.id))
        self.assertEqual(response.json()["uploaded_by_name"], "Dashboard User")


class DocumentDestroyAPITests(DocumentsTestBase):
    def test_destroy_removes_the_stored_file_too(self):
        data = self.upload().json()
        doc = Document.objects.get(pk=data["id"])
        self.assertTrue(default_storage.exists(doc.file_path))

        response = self.client.delete(f"/api/documents/documents/{data['id']}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Document.objects.filter(pk=data["id"]).exists())
        self.assertFalse(default_storage.exists(doc.file_path))
