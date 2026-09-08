"""Supabase Storage helpers for uploaded documents (CPMAS-25).

Documents live in a dedicated public ``documents`` bucket on the project's
Supabase Storage, reusing the REST-object pattern established by
``apps.company.storage.upload_logo``: writes authenticate with the service
role key (bypassing the bucket's RLS), reads use the authenticated object
endpoint, and display/embed URLs use the public object URL.

All helpers are gated behind ``settings.SUPABASE_DOCUMENT_STORAGE`` --
when that flag is off (local-only installs, the test suite), callers
(DocumentViewSet/DocumentSerializer) keep their existing local-disk path
via ``default_storage`` untouched, and these helpers either no-op or raise
``SupabaseStorageError`` rather than silently pretending to work.
"""
import http.client
import io
import re
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote

from django.conf import settings


class SupabaseStorageError(Exception):
    """Raised when a file could not be stored/fetched/deleted on Supabase Storage."""


def configured():
    """True when document uploads should use Supabase Storage."""
    return bool(
        settings.SUPABASE_DOCUMENT_STORAGE
        and settings.SUPABASE_URL
        and (settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY)
    )


def _bucket():
    return settings.SUPABASE_DOCUMENTS_BUCKET or "documents"


def _key():
    return settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY


def _safe_name(name):
    """Basename the uploaded file and keep only filesystem-safe characters."""
    base = (name or "").rsplit("/", 1)[-1]
    base = re.sub(r"[^\w.\- ]+", "_", base).strip(" .")
    return base[:200] or "file"


def _request(url, method, data=None, headers=None):
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(300)
    except (urllib.error.URLError, TimeoutError, OSError,
            http.client.HTTPException, ValueError) as exc:
        # Connection failures, and URL-construction failures too
        # (http.client.InvalidURL when a path isn't URL-encoded), must
        # surface as a clean SupabaseStorageError -- never a raw 500.
        raise SupabaseStorageError(f"Could not reach Supabase Storage: {exc}") from exc


_checked_buckets = set()


def _ensure_bucket():
    """Create the bucket on first upload (idempotent; 400/409 = already exists)."""
    bucket = _bucket()
    if bucket in _checked_buckets:
        return
    _checked_buckets.add(bucket)
    if not settings.SUPABASE_SERVICE_ROLE_KEY:
        # The anon key cannot create buckets; assume the bucket already exists.
        return
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    body = f'{{"name":"{bucket}","public":true}}'.encode("utf-8")
    status, _ = _request(
        f"{settings.SUPABASE_URL}/storage/v1/bucket",
        "POST",
        data=io.BytesIO(body),
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": "application/json",
        },
    )
    if status not in (200, 201, 400, 409):
        raise SupabaseStorageError(f"Supabase Storage bucket creation failed ({status}).")


def storage_key_for(uploaded_file):
    """A unique object key for an upload, preserving its readable file name."""
    return f"{uuid.uuid4().hex}/{_safe_name(uploaded_file.name)}"


def _object_url(storage_key):
    """The storage API URL for an object, with the key URL-encoded.

    Keys embed the original file name, which may contain spaces or other
    characters that http.client rejects in a raw URL path -- quote the whole
    key (keeping the uuid/name ``/``) so any name uploads cleanly.
    """
    return f"{settings.SUPABASE_URL}/storage/v1/object/{_bucket()}/{quote(storage_key)}"


def public_document_url(storage_key):
    """The public read URL for a stored object (for display/embed)."""
    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{_bucket()}/{quote(storage_key)}"


def upload_document(uploaded_file):
    """Upload ``uploaded_file`` to the documents bucket, returning its object key.

    Raises ``SupabaseStorageError`` when document storage is unavailable or
    the Storage API rejects the upload. The bucket is created lazily on
    first use (service-role only).
    """
    if not configured():
        raise SupabaseStorageError("Supabase storage for documents is not configured.")
    _ensure_bucket()

    storage_key = storage_key_for(uploaded_file)
    data = uploaded_file.read() if hasattr(uploaded_file, "read") else uploaded_file
    if isinstance(data, str):
        data = data.encode("utf-8")
    content_type = getattr(uploaded_file, "content_type", None) or "application/octet-stream"
    key = _key()

    status, body = _request(
        _object_url(storage_key),
        "POST",
        data=io.BytesIO(data),
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )
    if status not in (200, 201):
        raise SupabaseStorageError(
            f"Supabase Storage rejected the upload ({status}): {body!r}"
        )
    return storage_key


def read_document(storage_key):
    """Fetch an object's bytes from the documents bucket (authenticated read).

    Raises ``SupabaseStorageError`` on a non-2xx response (e.g. 404 when the
    object no longer exists on storage).
    """
    if not configured():
        raise SupabaseStorageError("Supabase storage for documents is not configured.")
    key = _key()
    status, body = _request(
        f"{settings.SUPABASE_URL}/storage/v1/object/authenticated/{_bucket()}/{quote(storage_key)}",
        "GET",
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
        },
    )
    if status != 200:
        raise SupabaseStorageError(
            f"Supabase Storage could not read the object ({status}): {body!r}"
        )
    return body


def delete_document(storage_key):
    """Remove an object from the documents bucket (service-role, best-effort)."""
    if not configured():
        raise SupabaseStorageError("Supabase storage for documents is not configured.")
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY
    status, _ = _request(
        _object_url(storage_key),
        "DELETE",
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
        },
    )
    # 404 means the object was already gone -- not an error for a delete.
    if status not in (200, 204, 404):
        raise SupabaseStorageError(f"Supabase Storage could not delete the object ({status}).")