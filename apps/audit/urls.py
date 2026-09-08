"""
URL routing for the ``audit`` app (read-only Audit Trail API).

Mounted under /api/audit/ (see ``construction/urls.py``). Only a list /
retrieve resource exists -- writes flow exclusively through
``audit.services.record_audit``.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AuditLogViewSet, audit_entities

router = DefaultRouter()
router.register('audit-logs', AuditLogViewSet, basename='audit-log')

urlpatterns = [
    path('entities/', audit_entities, name='audit-entities'),
    path('', include(router.urls)),
]