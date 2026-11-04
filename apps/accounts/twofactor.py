"""Two-factor sign-in with an authenticator app (TOTP) and one-time backup codes (django-otp)."""
import base64
import secrets
from urllib.parse import quote

import segno
from django.utils.safestring import mark_safe
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.models import SiteSettings

BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
BACKUP_COUNT = 10


def confirmed_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).first() if user and user.is_authenticated else None


def is_enabled(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def required_for(user):
    policy = SiteSettings.load().two_factor_policy
    return (policy == "everyone" or (policy == "staff" and user.role in ("admin", "lecturer")) or (policy == "admins" and user.role == "admin"))


def start_setup(user):
    """A fresh, unconfirmed device. Any earlier unconfirmed attempt is thrown away."""
    TOTPDevice.objects.filter(user=user, confirmed=False).delete()
    return TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=False)


def pending_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-pk").first()


def secret_text(device):
    return base64.b32encode(device.bin_key).decode().rstrip("=")


def otpauth_uri(device, issuer):
    label = quote(f"{issuer}:{device.user.get_username()}")
    return f"otpauth://totp/{label}?secret={secret_text(device)}&issuer={quote(issuer)}&digits={device.digits}&period={device.step}"


def qr_svg(device, issuer):
    return mark_safe(segno.make(otpauth_uri(device, issuer), error="m").svg_inline(scale=5, border=2, dark="#171a2e", light="#ffffff", title="QR code for your authenticator app"))


def confirm_setup(user, token):
    """True and the device becomes active when the app's current code is right."""
    device = pending_device(user)
    if not device or not (token or "").strip().isdigit() or not device.verify_token(token.strip()):
        return False
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    return True


def new_backup_codes(user):
    """Replace all backup codes; returns the plain codes (shown once, stored as given for django-otp to compare)."""
    dev, _ = StaticDevice.objects.get_or_create(user=user, name="Backup codes", defaults={"confirmed": True})
    dev.token_set.all().delete()
    codes = ["".join(secrets.choice(BACKUP_ALPHABET) for _ in range(10)) for _ in range(BACKUP_COUNT)]
    StaticToken.objects.bulk_create([StaticToken(device=dev, token=c) for c in codes])
    return [f"{c[:5]}-{c[5:]}" for c in codes]


def backup_codes_left(user):
    return StaticToken.objects.filter(device__user=user).count()


def verify(user, token):
    """Check a TOTP code or a backup code. Returns the device that accepted it, or None. A backup code works once."""
    raw = (token or "").strip().replace(" ", "").replace("-", "").lower()
    if not raw:
        return None
    if raw.isdigit():
        for d in TOTPDevice.objects.filter(user=user, confirmed=True):
            if d.verify_token(raw):
                return d
        return None
    for d in StaticDevice.objects.filter(user=user, confirmed=True):
        if d.verify_token(raw):
            return d
    return None


def disable(user):
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
