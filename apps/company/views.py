"""
Views for the ``company`` app -- Company Administration API.

``CompanyProfileViewSet`` exposes the single system-wide company record.

Endpoints (mounted under /api/company/):
- GET   /api/company/                -> the single company profile
- GET   /api/company/{pk}/           -> the single company profile
- PATCH /api/company/{pk}/           -> update the company details (owner only)
- POST/PUT/DELETE  -> 405 (there is only ever one company: no create, no
                          full-replace, no delete)

Security: only the Owner (``IsOwner`` from ``users.permissions``) may view
or update company details. The server-rendered page is gated the same way
(``owner_required`` in ``apps/core``), and the accountant's dashboard hides
the Settings entry entirely.
"""
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsOwner

from .models import CompanyProfile, FinancialSettings
from .serializers import CompanyProfileSerializer, FinancialSettingsSerializer


class CompanyProfileViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Owner-only view/update of the single company identity record.
    """

    permission_classes = [IsOwner]
    serializer_class = CompanyProfileSerializer
    http_method_names = ["get", "patch", "options", "head"]

    def get_queryset(self):
        return CompanyProfile.objects.all()

    def get_object(self):
        # There is only ever one company record, so ignore any {pk} in the
        # URL and always operate on that single profile.
        return self.get_queryset().first()

    def partial_update(self, request, *args, **kwargs):
        """PATCH /api/company/{pk}/ -- update the single company details."""
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class FinancialSettingsView(APIView):
    """
    GET / PATCH the single Financial rules record.

    - GET   /api/company/financial-settings/  -> the singleton record
    - PATCH /api/company/financial-settings/  -> update financial rules (owner)

    Security: Owner only, matching ``CompanyProfileViewSet`` (the Settings
    pages are only reachable by the Owner role).
    """

    permission_classes = [IsOwner]

    def get_object(self):
        settings, _ = FinancialSettings.objects.get_or_create(
            pk=FinancialSettings.SINGLETON_PK
        )
        return settings

    def get(self, request):
        return Response(FinancialSettingsSerializer(self.get_object()).data)

    def patch(self, request):
        instance = self.get_object()
        serializer = FinancialSettingsSerializer(
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)