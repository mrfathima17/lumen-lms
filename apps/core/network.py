"""Client IP detection and network allow-list checks."""
import ipaddress

from django.conf import settings

from .models import AllowedNetwork


def client_ip(request):
    """REMOTE_ADDR, or the first X-Forwarded-For entry only when we run behind our own proxy."""
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def ip_allowed(ip, scope):
    """True when no active rule covers the scope, or the IP is inside one of them."""
    rules = list(AllowedNetwork.objects.filter(is_active=True, scope__in=[scope, AllowedNetwork.Scope.ALL]))
    if not rules:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except (TypeError, ValueError):
        return False
    for rule in rules:
        try:
            if addr in ipaddress.ip_network(rule.cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def scope_for_path(path):
    if path.startswith("/admin-panel/"):
        return AllowedNetwork.Scope.ADMIN
    # Student-facing quiz pages (start, attempt, autosave, finish). The lecturer editor lives under /quiz-manager/.
    if path.startswith("/quizzes/"):
        return AllowedNetwork.Scope.QUIZ
    return AllowedNetwork.Scope.ALL
