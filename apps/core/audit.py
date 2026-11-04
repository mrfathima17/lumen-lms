from .models import AuditLog
from .network import client_ip


def record(request, action, target="", detail="", user=None, result="success"):
    """Write an audit entry. Never raises, so logging cannot break a request."""
    try:
        actor = user or (request.user if getattr(request, "user", None) and request.user.is_authenticated else None)
        AuditLog.objects.create(user=actor, action=action, target=target[:200], detail=detail, ip_address=client_ip(request), result=result)
    except Exception:  # pragma: no cover
        pass
