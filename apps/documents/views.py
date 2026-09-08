"""
DRF viewset for the ``documents`` app -- Document Management (CPMAS-25).
"""
import logging
import mimetypes

from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from . import storage
from .models import Document
from .serializers import DocumentSerializer

logger = logging.getLogger(__name__)


def _is_legacy_local_path(file_path):
    """True for rows written before Supabase storage (``documents/<file>``)."""
    return file_path.startswith("documents/")


def _resolve_uploader(user):
    """Return the schema-backed ``users.User`` a document upload is attributed to.

    Dashboard sessions can authenticate against the legacy ``auth.User``
    table (see ``users.authentication.UserSessionAuthentication``): Django's
    login keeps a non-superuser ``auth.User`` as-is, but the documents
    ``uploaded_by`` column is a UUID FK to the schema ``users`` table, so
    saving an ``auth.User`` (integer pk) directly would crash the upload.
    Map it here exactly the way that auth layer maps superusers -- match a
    ``users.User`` by username, otherwise bridge into one (OWNER for Django
    superusers, ACCOUNTANT otherwise) -- and raise a client-facing
    ValidationError instead of a 500 when no identity can exist.
    """
    from users.models import Role, User as AppUser

    if isinstance(user, AppUser):
        return user
    if user is None or getattr(user, 'is_anonymous', True):
        raise ValidationError({"uploaded_by": "No user account is attached to this session."})
    try:
        return AppUser.objects.get(username=user.username, is_active=True)
    except AppUser.DoesNotExist:
        pass
    email = (getattr(user, 'email', '') or '').strip()
    first = (getattr(user, 'first_name', '') or '').strip() or 'Dashboard'
    last = (getattr(user, 'last_name', '') or '').strip() or 'User'
    role = Role.OWNER if getattr(user, 'is_superuser', False) else Role.ACCOUNTANT
    try:
        with transaction.atomic():
            return AppUser.objects.create(
                username=user.username,
                email=email or f'{user.username}@dashboard.local',
                password_hash=getattr(user, 'password', ''),
                first_name=first,
                last_name=last,
                role=role,
                is_active=True,
            )
    except IntegrityError:
        # A concurrent request may have bridged the same account already.
        return AppUser.objects.get(username=user.username, is_active=True)


class DocumentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       mixins.CreateModelMixin, mixins.UpdateModelMixin,
                       mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    /api/documents/documents/                GET (list, ?entity_type=&entity_id=&document_type=), POST (upload)
    /api/documents/documents/{id}/           GET, PATCH (document_type only -- see DocumentSerializer), DELETE

    No raw file replacement on update -- swapping the underlying file is a
    delete + re-upload (see DocumentSerializer's read_only_fields), so a
    document's stored path never changes out from under something that
    already linked to it.
    """

    queryset = Document.objects.select_related('uploaded_by').all()
    serializer_class = DocumentSerializer
    # Multipart for the upload itself; JSON for the metadata-only PATCH
    # (document_type) an upload doesn't need a form re-submission for.
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = ['file_name', 'document_type']

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        entity_type = params.get('entity_type')
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)

        entity_id = params.get('entity_id')
        if entity_id:
            queryset = queryset.filter(entity_id=entity_id)

        document_type = params.get('document_type')
        if document_type:
            queryset = queryset.filter(document_type=document_type)

        return queryset

    def perform_create(self, serializer):
        # Resolve the uploader to a schema-backed users.User BEFORE touching
        # storage, so a session that can't map to one fails cleanly (400)
        # without having orphaned an uploaded object in the bucket.
        uploader = _resolve_uploader(self.request.user)
        uploaded_file = serializer.validated_data.pop('file')
        # file_path stores where the bytes actually live: the object key in
        # the Supabase documents bucket when that storage is configured, or
        # a MEDIA_ROOT-relative path (e.g. "documents/foo.pdf") otherwise --
        # never a served URL. DocumentSerializer.file_url computes the
        # display URL for either case.
        try:
            if storage.configured():
                file_path = storage.upload_document(uploaded_file)
            else:
                file_path = default_storage.save(f'documents/{uploaded_file.name}', uploaded_file)
        except storage.SupabaseStorageError as exc:
            # A storage outage/timeout must surface as an actionable 400
            # with the real reason -- not an opaque 500 -- so the client can
            # tell the user what went wrong. The full traceback is logged.
            logger.exception("Document upload to storage failed")
            raise ValidationError({"file": f"Could not store the file: {exc}"})
        serializer.save(
            uploaded_by=uploader,
            file_name=uploaded_file.name,
            file_path=file_path,
            file_type=uploaded_file.content_type or '',
            file_size=uploaded_file.size,
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """
        GET /api/documents/documents/{id}/download/ -- downloads the
        stored file as an attachment. Bytes are streamed back through
        Django itself (no web-server / DEBUG dependency) from whichever
        storage the document uses -- the Supabase documents bucket when
        configured, local MEDIA_ROOT otherwise -- so downloads work in dev
        and the file stays behind the viewset's authentication.
        """
        document = self.get_object()
        content_type = (
            document.file_type
            or mimetypes.guess_type(document.file_name)[0]
            or 'application/octet-stream'
        )
        try:
            if storage.configured() and not _is_legacy_local_path(document.file_path):
                response = HttpResponse(
                    storage.read_document(document.file_path), content_type=content_type
                )
            else:
                try:
                    file_handle = default_storage.open(document.file_path, 'rb')
                except FileNotFoundError:
                    raise NotFound('The stored file is missing on storage.')
                response = FileResponse(file_handle, content_type=content_type)
        except storage.SupabaseStorageError:
            # Legacy row stored under MEDIA_ROOT before Supabase storage was
            # configured: fall back to local disk rather than failing a
            # download that local bytes can still satisfy.
            try:
                file_handle = default_storage.open(document.file_path, 'rb')
            except FileNotFoundError:
                raise NotFound('The stored file is missing on storage.')
            response = FileResponse(file_handle, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{document.file_name}"'
        return response

    def update(self, request, *args, **kwargs):
        # PUT would require re-sending `file` (required on create) just to
        # patch document_type -- there's no full-replace operation here, so
        # only PATCH (partial=True) is supported. See DocumentSerializer's
        # docstring: swapping the file is delete + re-upload, not an update.
        if not kwargs.get('partial', False):
            raise MethodNotAllowed('PUT')
        return super().update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        # Best-effort: remove the stored file too, from whichever storage it
        # lives in (Supabase object for new uploads, local MEDIA_ROOT for
        # legacy pre-Supabase rows) -- but a missing/already-gone file
        # shouldn't block deleting the (still-authoritative) row.
        try:
            if storage.configured() and not _is_legacy_local_path(instance.file_path):
                storage.delete_document(instance.file_path)
            else:
                default_storage.delete(instance.file_path)
        except storage.SupabaseStorageError:
            pass
        instance.delete()
