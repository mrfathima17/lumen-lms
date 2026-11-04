from django.shortcuts import render

from .models import SiteSettings
from .network import client_ip, ip_allowed, scope_for_path

STATIC_PREFIXES = ("/static/", "/media/", "/branding/", "/healthz/")  # health checks must answer even in maintenance mode or from any network


class MaintenanceMiddleware:
    """When maintenance mode is on, only signed-in admins can use the site."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(STATIC_PREFIXES) or request.path.startswith("/sign-in"):
            return self.get_response(request)
        s = SiteSettings.load()
        if s.apply_schedule():
            from . import audit

            audit.record(request, "maintenance_changed", detail="switched on as scheduled")
        if s.maintenance_mode:
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated and getattr(user, "role", "") == "admin"):
                return render(request, "errors/maintenance.html", status=503)
        return self.get_response(request)


class NetworkRulesMiddleware:
    """Block requests from networks that are not allowed for the area being visited."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(STATIC_PREFIXES):
            return self.get_response(request)
        ip, scope = client_ip(request), scope_for_path(request.path)
        if not ip_allowed(ip, scope):
            self._audit(request, ip, scope)
            return render(request, "errors/restricted.html", {"client_ip": ip}, status=403)
        return self.get_response(request)

    @staticmethod
    def _audit(request, ip, scope):
        """Log the block, at most once a minute per address, so someone refreshing a blocked page cannot flood the log."""
        try:
            from datetime import timedelta

            from django.utils import timezone

            from . import audit
            from .models import AuditLog

            recent = AuditLog.objects.filter(action="ip_blocked", ip_address=ip, created_at__gte=timezone.now() - timedelta(seconds=60))
            if not recent.exists():
                audit.record(request, "ip_blocked", target=request.path[:200], detail=str(scope or ""), result="blocked")
        except Exception:  # pragma: no cover  (logging must never break the response)
            pass


class ModuleMiddleware:
    """Switched-off optional modules answer 404 for everyone (administrators switch them back on in the admin panel)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from . import modules

        if not request.path.startswith(STATIC_PREFIXES):
            key = modules.module_for_path(request.path)
            if key and key in modules.disabled_keys(request):
                return render(request, "errors/module_off.html", {"module_label": modules.MODULES[key][0]}, status=404)
        return self.get_response(request)
