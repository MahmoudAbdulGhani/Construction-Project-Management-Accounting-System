"""
URL configuration for construction project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls')),

    # Each domain app mounts its own DRF router under /api/<app>/ as it's
    # built out, so this list grows one line per app rather than
    # centralizing all routes here.
    path('api/inventory/', include('inventory.urls')),  # CPMAS-28, CPMAS-29
    path('api/purchasing/', include('purchasing.urls')),  # CPMAS-30, CPMAS-31
    path('api/invoicing/', include('invoicing.urls')),  # CPMAS-32
    path('api/projects/', include('projects.urls')),  # CPMAS-33
    path('api/clients/', include('clients.urls')),  # CPMAS-34
    path('api/suppliers/', include('suppliers.urls')),
    path('api/contractors/', include('contractors.urls')),
    path('api/employees/', include('employees.urls')),
    path('api/expenses/', include('expenses.urls')),  # CPMAS-35
    path('api/accounting/', include('accounting.urls')),
    path('api/payments/', include('payments.urls')),  # CPMAS-35, CPMAS-21
    path('api/notifications/', include('notifications.urls')),  # CPMAS-22
path('api/taxes/', include('taxes.urls')),  # Tax Rates configuration
    path('api/audit/', include('audit.urls')),  # Read-only audit trail
    path('api/documents/', include('documents.urls')),  # CPMAS-25
    path('api/auth/', include('users.urls')),  # Auth & Authorization (RBAC)
    path('api/company/', include('company.urls')),  # Company profile (view/update)
]

# Serve uploaded files locally in development. In production this is
# handled by the web server / reverse proxy, not Django.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
