import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.urls import reverse

from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()


def make(django_user_model, **kw):
    kw.setdefault("email", "amal@example.com")
    return django_user_model.objects.create_user("s2026-1", password="Old-pass-12345", role="student", **kw)


def test_page_opens_and_is_linked_from_login(client):
    assert b"Forgot your password?" in client.get(reverse("accounts:forgot-password")).content
    assert reverse("accounts:forgot-password").encode() in client.get(reverse("accounts:login")).content


def test_reset_by_username_or_email_sends_one_link(client, django_user_model):
    make(django_user_model)
    for ident in ("s2026-1", "AMAL@example.com"):
        cache.clear()
        mail.outbox.clear()
        r = client.post(reverse("accounts:forgot-password"), {"identifier": ident})
        assert b"Check your email" in r.content and len(mail.outbox) == 1
        assert "/reset/" in mail.outbox[0].body


def test_unknown_account_gets_same_answer_and_no_mail(client, django_user_model):
    make(django_user_model)
    r = client.post(reverse("accounts:forgot-password"), {"identifier": "nobody"})
    assert b"Check your email" in r.content and not mail.outbox


def test_disabled_or_emailless_accounts_get_nothing(client, django_user_model):
    u = make(django_user_model)
    u.is_active = False
    u.save()
    client.post(reverse("accounts:forgot-password"), {"identifier": "s2026-1"})
    u.is_active, u.email = True, ""
    u.save()
    client.post(reverse("accounts:forgot-password"), {"identifier": "s2026-1"})
    assert not mail.outbox


def test_throttle(client, django_user_model):
    make(django_user_model)
    for _ in range(8):
        client.post(reverse("accounts:forgot-password"), {"identifier": "s2026-1"})
    assert len(mail.outbox) == 5


def test_full_reset_flow(client, django_user_model):
    u = make(django_user_model, must_change_password=True)
    client.post(reverse("accounts:forgot-password"), {"identifier": "s2026-1"})
    link = re.search(r"http://testserver(/\S+)", mail.outbox[0].body).group(1)
    assert client.get(link).status_code == 200
    r = client.post(link, {"new_password1": "Brand-new-pass-77", "new_password2": "Brand-new-pass-77"}, follow=True)
    assert b"Your password was changed" in r.content
    u.refresh_from_db()
    assert u.check_password("Brand-new-pass-77") and not u.must_change_password
    assert client.get(link).status_code == 400  # one use only
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"password_reset_requested", "password_reset_done"} <= actions


def test_weak_password_and_bad_link(client, django_user_model, settings):
    settings.AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}}]
    make(django_user_model)
    client.post(reverse("accounts:forgot-password"), {"identifier": "s2026-1"})
    link = re.search(r"http://testserver(/\S+)", mail.outbox[0].body).group(1)
    r = client.post(link, {"new_password1": "short", "new_password2": "short"})
    assert r.status_code == 200 and b"too short" in r.content
    assert client.get("/reset/zz/bad-token/").status_code == 400
