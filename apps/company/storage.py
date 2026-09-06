"""Supabase Storage helper for the company logo upload.

The company logo is stored in the ``logo`` public bucket on the project's
Supabase Storage. ``upload_logo`` POSTs an uploaded file to the Storage
object endpoint and returns the stable public URL (``.../object/public/...``)
that the rest of the app displays.

Config comes from settings (``SUPABASE_URL``, ``SUPABASE_ANON_KEY``,
``SUPABASE_SERVICE_ROLE_KEY``, ``SUPABASE_LOGO_BUCKET``), themselves read
from ``.env``. ``upload_logo`` authenticates with the service role key when
one is configured -- it bypasses the bucket's storage RLS policies, so no
public INSERT policy is required -- and falls back to the anon public key
otherwise. If neither set of credentials is available, uploading raises
``SupabaseStorageError`` so the caller can surface a friendly error instead
of silently storing a bare filename (the previous behaviour). The service
role key is used server-side only and must never be exposed client-side.
"""
import io
import urllib.error
import urllib.request
import uuid

from django.conf import settings


class SupabaseStorageError(Exception):
    """Raised when the logo could not be uploaded to Supabase Storage."""


def public_logo_url(filename):
    """The public read URL for a file already in the logo bucket."""
    bucket = settings.SUPABASE_LOGO_BUCKET
    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"


def upload_logo(uploaded_file):
    """Upload ``uploaded_file`` to the logo bucket, returning its public URL.

    ``uploaded_file`` is a Django ``UploadedFile``. A unique name is used so
    replacing the logo never collides with a previously cached variant. Raises
    ``SupabaseStorageError`` on missing config or a non-2xx response.
    """
    bucket = settings.SUPABASE_LOGO_BUCKET
    base = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY
    if not base or not key:
        raise SupabaseStorageError(
            "Supabase Storage is not configured "
            "(missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY)."
        )

    ext = ""
    name = getattr(uploaded_file, "name", "") or ""
    if "." in name:
        ext = name.rsplit(".", 1)[-1].lower()[:10]
    ext = ext if ext in {"png", "jpg", "jpeg", "svg"} else "png"

    filename = f"logo-{uuid.uuid4().hex}.{ext}"

    data = uploaded_file.read() if hasattr(uploaded_file, "read") else uploaded_file
    if isinstance(data, str):
        data = data.encode("utf-8")

    content_type = getattr(uploaded_file, "content_type", None) or {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")

    url = f"{base}/storage/v1/object/{bucket}/{filename}"
    request = urllib.request.Request(
        url,
        data=io.BytesIO(data),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            body = response.read(300)
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read(300)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SupabaseStorageError(f"Could not reach Supabase Storage: {exc}") from exc

    if status not in (200, 201):
        raise SupabaseStorageError(
            f"Supabase Storage rejected the upload ({status}): {body[:300]!r}"
        )

    return public_logo_url(filename)
