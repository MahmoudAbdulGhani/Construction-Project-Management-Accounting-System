"""
URL configuration for the ``company`` app API.

Mounted by the root URLconf at ``/api/company/``. A single read/update
ViewSet is registered with an empty prefix so the routes appear directly on
that mount point:

- GET   /api/company/              -> single company profile
- GET   /api/company/{pk}/         -> single company profile
- PATCH /api/company/{pk}/         -> update company details (owner only)
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CompanyProfileViewSet, FinancialSettingsView

router = DefaultRouter()
router.register(r"", CompanyProfileViewSet, basename="companyprofile")

urlpatterns = [
    path(
        "financial-settings/",
        FinancialSettingsView.as_view(),
        name="financial-settings",
    ),
] + router.urls