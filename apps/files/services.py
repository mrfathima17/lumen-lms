from django.db.models import Sum

from apps.core.models import SiteSettings

from .models import PrivateFile

MB = 1024 * 1024


def used_bytes(user):
    return PrivateFile.objects.filter(owner=user).aggregate(t=Sum("size"))["t"] or 0


def quota_bytes():
    return SiteSettings.load().private_files_quota_mb * MB


def usage(user):
    used, quota = used_bytes(user), quota_bytes()
    pct = min(100, round(used * 100 / quota)) if quota else 100
    return {"used": used, "quota": quota, "percent": pct, "left": max(0, quota - used), "near_full": pct >= 90}


def human(n):
    if n >= MB:
        return f"{n / MB:.1f} MB"
    return f"{max(1, round(n / 1024)) if n else 0} KB"


def can_store(user, size):
    return used_bytes(user) + size <= quota_bytes()
