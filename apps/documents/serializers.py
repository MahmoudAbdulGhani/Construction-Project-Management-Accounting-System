"""
DRF serializers for the ``documents`` app -- Document Management (CPMAS-25).
"""
from django.core.files.storage import default_storage
from rest_framework import serializers

from . import storage
from .models import Document


class DocumentSerializer(serializers.ModelSerializer):
    """
    Serializer for Document list/retrieve/create/destroy.

    ``file`` is a write-only upload input, not a model field -- the model
    stores the resulting ``file_path``/``file_name``/``file_type``/
    ``file_size`` (all derived from the uploaded file in ``create``), not
    the file object itself. Only ``document_type`` is patchable after
    creation -- swapping the underlying file means delete + re-upload, not
    an in-place replace, so a document's stored path never goes stale
    against what a client already downloaded/linked.

    ``file_url`` is a computed read-only field: ``file_path`` stores the
    storage-relative path, not something a browser can fetch directly.
    """

    file = serializers.FileField(write_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id', 'file', 'file_name', 'file_path', 'file_url', 'file_type', 'file_size',
            'document_type', 'entity_type', 'entity_id',
            'uploaded_by', 'uploaded_by_name', 'uploaded_at',
        ]
        read_only_fields = ['file_name', 'file_path', 'file_type', 'file_size', 'uploaded_by', 'uploaded_at']

    def get_uploaded_by_name(self, obj):
        user = obj.uploaded_by
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name or user.username

    def get_file_url(self, obj):
        if storage.configured() and not obj.file_path.startswith("documents/"):
            return storage.public_document_url(obj.file_path)
        return default_storage.url(obj.file_path)

    def validate_entity_type(self, value):
        if value not in Document.ENTITY_TYPES:
            raise serializers.ValidationError(
                f"entity_type must be one of {Document.ENTITY_TYPES}."
            )
        return value

    def validate(self, attrs):
        # On update, only document_type may change -- re-pointing a document
        # at a different entity after the fact would silently break
        # whatever already links to it under its original entity_type/id.
        if self.instance is not None:
            for locked_field in ('entity_type', 'entity_id'):
                if locked_field in attrs and attrs[locked_field] != getattr(self.instance, locked_field):
                    raise serializers.ValidationError(
                        {locked_field: "Cannot change this after upload."}
                    )
        return attrs
