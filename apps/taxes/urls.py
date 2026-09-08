"""URL routing for the ``taxes`` app (Tax Rates configuration API).

Mounted under /api/taxes/ (see ``construction/urls.py``). Exposes the
``tax_rates`` table as a DRF viewset so the Company settings Tax Rates tab
(and any API client) can list/create/update/delete tax rates and toggle
their active state.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TaxRateViewSet

router = DefaultRouter()
router.register('tax-rates', TaxRateViewSet, basename='tax-rate')

urlpatterns = [
    path('', include(router.urls)),
]