"""
URL routing for the ``notifications`` app's API (CPMAS-22).

Mounted under /api/notifications/ by construction/urls.py.
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import NotificationPreferenceView, NotificationViewSet

router = DefaultRouter()
router.register('notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),
] + router.urls
