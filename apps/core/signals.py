from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

from . import audit


@receiver(user_login_failed)
def audit_failed_login(sender, credentials=None, request=None, **kwargs):
    """A wrong sign-in. The attempted username is kept only when it is a real account (people sometimes type a password there);
    the password is never stored."""
    if request is None:
        return
    name = ((credentials or {}).get("username") or "").strip()[:150]
    known = bool(name) and get_user_model().objects.filter(username__iexact=name).exists()
    audit.record(request, "login_failed", target=name if known else "", detail="wrong password" if known else "unknown user", result="failed")
