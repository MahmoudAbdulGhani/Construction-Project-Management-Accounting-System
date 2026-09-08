"""
No-store middleware for server-rendered HTML.

The dashboard authenticates app users via cookie/session middleware and
renders its pages from templates (logo, user info, role-based nav). The
browser can otherwise cache an HTML page and keep serving a stale snapshot
(e.g. an old company logo URL) on back/forward or normal navigation, which
reads as "the UI didn't update".

This sets ``Cache-Control: no-store`` on every HTML response so the browser
always fetches fresh server-rendered content. Non-HTML responses (API JSON,
static files, redirects) are left untouched.
"""
from django.http import HttpResponse


class NoStoreHtmlMiddleware:
    """Disable browser caching of HTML responses so pages always re-render."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if isinstance(response, HttpResponse) and "text/html" in response.get(
            "Content-Type", ""
        ):
            response["Cache-Control"] = "no-store"
        return response
