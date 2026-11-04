import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_public_pages_open_without_login(client):
    for name in ("core:terms", "core:help", "core:session-expired"):
        assert client.get(reverse(name)).status_code == 200
    assert b"Privacy policy" in client.get(reverse("core:terms")).content
    assert b"What we collect" in client.get(reverse("core:terms") + "?tab=privacy").content
    assert b"Sign in" in client.get(reverse("core:help")).content


def test_unknown_tab_falls_back(client):
    assert b"Using Lumen" in client.get(reverse("core:terms") + "?tab=nope").content


def test_signed_in_users_get_app_layout(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("s1", password="x", role="student"))
    assert b'class="layout"' in client.get(reverse("core:help")).content


def test_contact_support_sends_message_to_admins(client, django_user_model):
    from apps.messaging.models import Message

    admin = django_user_model.objects.create_user("adm9", password="x" * 12, role="admin", is_staff=True)
    stu = django_user_model.objects.create_user("stu9", password="x" * 12, role="student")
    client.force_login(stu)
    assert b"Contact support" in client.get("/help/").content
    r = client.post("/help/", {"subject": "Cannot open quiz", "message": "It says closed."})
    assert r.status_code == 302
    m = Message.objects.get(recipient=admin)
    assert m.subject.startswith("[Support]") and m.sender == stu
    assert client.post("/help/", {"subject": "", "message": ""}).status_code == 302 and Message.objects.count() == 1


def test_contact_support_needs_sign_in(client, db):
    r = client.post("/help/", {"subject": "x", "message": "y"})
    assert r.status_code == 302 and "/sign-in/" in r["Location"]
