import time

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts import twofactor
from apps.core.models import AuditLog, SiteSettings

PW = "Pass-12345-xyz"


def code_for(device, offset=0):
    t = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    t.time = time.time() + offset * device.step
    return f"{t.token():06d}"


def enable(user):
    """Give the user a confirmed device and return it."""
    return TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=True)


def password_step(client, user, **extra):
    return client.post(reverse("accounts:login"), {"username": user.username, "password": PW, **extra})


# ---------- sign-in flow ----------

def test_without_two_factor_sign_in_is_unchanged(student):
    c = Client()
    assert password_step(c, student).status_code == 302
    assert c.get(reverse("accounts:student-dashboard")).status_code == 200


def test_password_alone_does_not_sign_in(student):
    enable(student)
    c = Client()
    r = password_step(c, student)
    assert r.status_code == 302 and r.url == reverse("accounts:two-factor-verify")
    assert c.get(reverse("accounts:student-dashboard")).status_code == 302  # still not signed in
    assert "_auth_user_id" not in c.session


def test_correct_code_completes_sign_in(student):
    d = enable(student)
    c = Client()
    password_step(c, student)
    r = c.post(reverse("accounts:two-factor-verify"), {"token": code_for(d)})
    assert r.status_code == 302 and r.url == reverse("accounts:student-dashboard")
    assert c.get(reverse("accounts:student-dashboard")).status_code == 200
    assert AuditLog.objects.filter(action="sign_in", detail="two-factor").exists()


def test_wrong_code_is_refused_and_five_wrong_codes_restart(student):
    enable(student)
    c = Client()
    password_step(c, student)
    for i in range(4):
        r = c.post(reverse("accounts:two-factor-verify"), {"token": "000000"})
        assert r.status_code == 200 and b"not right" in r.content
    r = c.post(reverse("accounts:two-factor-verify"), {"token": "000000"})
    assert r.status_code == 302 and r.url == reverse("accounts:login")
    assert c.get(reverse("accounts:two-factor-verify")).status_code == 302  # pending state is gone
    assert AuditLog.objects.filter(action="two_factor_failed").count() == 5


def test_verify_page_needs_a_password_step_first(db):
    assert Client().get(reverse("accounts:two-factor-verify")).status_code == 302
    assert Client().post(reverse("accounts:two-factor-verify"), {"token": "123456"}).status_code == 302


def test_pending_sign_in_expires(student, monkeypatch):
    d = enable(student)
    c = Client()
    password_step(c, student)
    s = c.session
    s["pending_2fa"]["at"] -= 600
    s.save()
    r = c.post(reverse("accounts:two-factor-verify"), {"token": code_for(d)})
    assert r.status_code == 302 and r.url == reverse("accounts:login")
    assert c.get(reverse("accounts:student-dashboard")).status_code == 302


def test_wrong_password_never_reaches_second_step(student):
    enable(student)
    c = Client()
    r = c.post(reverse("accounts:login"), {"username": student.username, "password": "nope"})
    assert r.status_code == 200 and "pending_2fa" not in c.session


def test_code_cannot_be_replayed(student):
    d = enable(student)
    code = code_for(d)
    c1, c2 = Client(), Client()
    password_step(c1, student)
    c1.post(reverse("accounts:two-factor-verify"), {"token": code})
    password_step(c2, student)
    r = c2.post(reverse("accounts:two-factor-verify"), {"token": code})
    assert r.status_code == 200  # same code, same 30 seconds: refused


def test_backup_code_works_once(student):
    enable(student)
    codes = twofactor.new_backup_codes(student)
    c = Client()
    password_step(c, student)
    r = c.post(reverse("accounts:two-factor-verify"), {"token": codes[0]})  # shown with a dash and in lower case
    assert r.status_code == 302 and r.url == reverse("accounts:student-dashboard")
    assert twofactor.backup_codes_left(student) == 9
    c2 = Client()
    password_step(c2, student)
    assert c2.post(reverse("accounts:two-factor-verify"), {"token": codes[0]}).status_code == 200


def test_next_url_is_kept_but_only_if_local(student):
    d = enable(student)
    c = Client()
    password_step(c, student, next="https://evil.example/x")
    r = c.post(reverse("accounts:two-factor-verify"), {"token": code_for(d)})
    assert r.url == reverse("accounts:student-dashboard")
    c = Client()
    password_step(c, student, next="/courses/")
    d.refresh_from_db()
    r = c.post(reverse("accounts:two-factor-verify"), {"token": code_for(d, offset=1)})
    assert r.url == "/courses/"


@override_settings(OTP_TOTP_THROTTLE_FACTOR=1)
def test_django_otp_throttles_rapid_guessing(student):
    d = enable(student)
    assert twofactor.verify(student, "000000") is None
    assert twofactor.verify(student, code_for(d)) is None  # right code, but too soon after a failure


# ---------- setup and management ----------

def test_setup_confirm_and_backup_codes(student):
    c = Client()
    c.force_login(student)
    html = c.post(reverse("accounts:two-factor-start"), follow=True).content
    assert b"<svg" in html and b"Cannot scan" in html
    dev = TOTPDevice.objects.get(user=student)
    assert not dev.confirmed
    # wrong code first
    c.post(reverse("accounts:two-factor-confirm"), {"token": "000000"})
    assert not TOTPDevice.objects.get(pk=dev.pk).confirmed
    TOTPDevice.objects.filter(pk=dev.pk).update(throttling_failure_count=0, throttling_failure_timestamp=None)  # django-otp locks 1s after a miss
    r = c.post(reverse("accounts:two-factor-confirm"), {"token": code_for(dev)}, follow=True)
    assert TOTPDevice.objects.get(pk=dev.pk).confirmed and b"Your backup codes" in r.content
    assert twofactor.backup_codes_left(student) == 10
    assert b"Your backup codes" not in c.get(reverse("accounts:two-factor")).content  # shown once only
    assert AuditLog.objects.filter(action="two_factor_enabled").exists()


def test_qr_and_uri_carry_the_site_name(student):
    d = enable(student)
    uri = twofactor.otpauth_uri(d, "My Uni")
    assert uri.startswith("otpauth://totp/My%20Uni%3As2026-0142?secret=") and "issuer=My%20Uni" in uri


def test_start_is_post_only(student):
    c = Client()
    c.force_login(student)
    assert c.get(reverse("accounts:two-factor-start")).status_code == 405


def test_disable_needs_password_and_is_blocked_when_required(student):
    enable(student)
    c = Client()
    c.force_login(student)
    c.post(reverse("accounts:two-factor-disable"), {"password": "wrong"})
    assert twofactor.is_enabled(student)
    s = SiteSettings.load(); s.two_factor_policy = "everyone"; s.save()
    c.post(reverse("accounts:two-factor-disable"), {"password": PW})
    assert twofactor.is_enabled(student)
    s.two_factor_policy = "off"; s.save()
    c.post(reverse("accounts:two-factor-disable"), {"password": PW})
    assert not twofactor.is_enabled(student) and AuditLog.objects.filter(action="two_factor_disabled").exists()


def test_new_backup_codes_need_password_and_replace_old(student):
    enable(student)
    old = twofactor.new_backup_codes(student)
    c = Client()
    c.force_login(student)
    c.post(reverse("accounts:two-factor-codes"), {"password": "wrong"})
    assert StaticToken.objects.filter(token=old[0].replace("-", "")).exists()
    c.post(reverse("accounts:two-factor-codes"), {"password": PW})
    assert not StaticToken.objects.filter(token=old[0].replace("-", "")).exists() and twofactor.backup_codes_left(student) == 10


# ---------- required by policy ----------

@pytest.mark.parametrize("policy,role,forced", [("off", "admin", False), ("admins", "admin", True), ("admins", "lecturer", False),
                                                 ("staff", "lecturer", True), ("staff", "student", False), ("everyone", "student", True)])
def test_policy_forces_setup(make_user, policy, role, forced):
    u = make_user("u1", role)
    s = SiteSettings.load(); s.two_factor_policy = policy; s.save()
    c = Client()
    c.force_login(u)
    r = c.get(reverse("courses:my-courses"))
    assert (r.status_code == 302 and r.url == reverse("accounts:two-factor")) is forced


def test_forced_user_can_still_reach_setup_and_sign_out(student):
    s = SiteSettings.load(); s.two_factor_policy = "everyone"; s.save()
    c = Client()
    c.force_login(student)
    assert c.get(reverse("accounts:two-factor")).status_code == 200
    d = None
    c.post(reverse("accounts:two-factor-start"))
    d = TOTPDevice.objects.get(user=student)
    c.post(reverse("accounts:two-factor-confirm"), {"token": code_for(d)})
    assert c.get(reverse("courses:my-courses")).status_code == 200  # setup finished, site opens up


def test_admin_can_reset_a_users_two_factor(student, admin_user):
    enable(student)
    twofactor.new_backup_codes(student)
    c = Client()
    c.force_login(admin_user)
    assert b"Reset two-factor" in c.get(reverse("administration:user-edit", args=[student.pk])).content
    r = c.post(reverse("administration:user-two-factor-reset", args=[student.pk]))
    assert r.status_code == 302 and not twofactor.is_enabled(student) and twofactor.backup_codes_left(student) == 0
    assert AuditLog.objects.filter(action="two_factor_reset", target=student.username).exists()
    other = Client(); other.force_login(student)
    assert other.post(reverse("administration:user-two-factor-reset", args=[student.pk])).status_code == 403


def test_settings_page_offers_the_policy(admin_user):
    c = Client(); c.force_login(admin_user)
    assert b"Required for administrators" in c.get(reverse("administration:settings")).content
