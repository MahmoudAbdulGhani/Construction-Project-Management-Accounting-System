"""
Middleware that exposes the active HTTP request to the audit recording
service, so signal handlers can attribute audit entries to the acting user
and client IP.

Runs after ``AppUserSessionMiddleware`` so ``request.user`` is already the
app's ``users.User`` when the request is stashed.
"""
from .services import reset_current_request, set_current_request


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_current_request(token)