import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import SiteSettings
from apps.files import services
from apps.files.models import PrivateFile


def upload(client, name="notes.pdf", data=b"hello", status=302):
    r = client.post(reverse("files:upload"), {"file": SimpleUploadedFile(name, data)})
    assert r.status_code == status
    return r


def set_quota(mb):
    s = SiteSettings.load()
    s.private_files_quota_mb = mb
    s.save()


def test_upload_list_download_delete(client, student):
    client.force_login(student)
    upload(client, "my notes.pdf", b"secret bytes")
    f = PrivateFile.objects.get()
    assert f.owner == student and f.size == 12 and f.name == "my_notes.pdf"
    assert b"my_notes.pdf" in client.get(reverse("files:list")).content
    r = client.get(reverse("files:download", args=[f.pk]))
    assert b"".join(r.streaming_content) == b"secret bytes"
    assert "attachment" in r["Content-Disposition"] and r["X-Content-Type-Options"] == "nosniff"
    path = f.file.path
    assert os.path.exists(path)
    assert client.get(reverse("files:delete", args=[f.pk])).status_code == 405
    client.post(reverse("files:delete", args=[f.pk]))
    assert not PrivateFile.objects.exists() and not os.path.exists(path)  # the bytes are gone too


def test_only_the_owner_can_touch_a_file_not_even_admin(client, student, lecturer, admin_user, make_user):
    client.force_login(student)
    upload(client)
    f = PrivateFile.objects.get()
    for u in (lecturer, admin_user, make_user("classmate", "student")):
        client.force_login(u)
        assert client.get(reverse("files:download", args=[f.pk])).status_code == 403
        assert client.post(reverse("files:delete", args=[f.pk])).status_code == 403
        assert b"notes.pdf" not in client.get(reverse("files:list")).content
    assert PrivateFile.objects.filter(pk=f.pk).exists()


def test_disallowed_type_and_oversize_rejected(client, student, settings):
    client.force_login(student)
    upload(client, "run.exe", b"MZ", status=400)
    upload(client, "page.html", b"<script>", status=400)
    settings.MAX_UPLOAD_MB = 1
    upload(client, "big.pdf", b"x" * (1024 * 1024 + 1), status=400)
    assert not PrivateFile.objects.exists()


def test_quota_enforced_and_freed_on_delete(client, student):
    set_quota(1)
    client.force_login(student)
    upload(client, "a.pdf", b"x" * 700_000)
    r = upload(client, "b.pdf", b"x" * 400_000, status=400)  # 1.1 MB would exceed the 1 MB quota
    assert b"Not enough space" in r.content and PrivateFile.objects.count() == 1
    assert services.usage(student)["percent"] == 67
    client.post(reverse("files:delete", args=[PrivateFile.objects.get().pk]))
    upload(client, "b.pdf", b"x" * 400_000)
    assert PrivateFile.objects.count() == 1


def test_quota_is_per_user(client, student, lecturer):
    set_quota(1)
    client.force_login(student)
    upload(client, "a.pdf", b"x" * 900_000)
    client.force_login(lecturer)
    upload(client, "a.pdf", b"x" * 900_000)
    assert PrivateFile.objects.count() == 2


def test_exactly_full_is_allowed_and_warning_shows(client, student):
    set_quota(1)
    client.force_login(student)
    upload(client, "a.pdf", b"x" * 1024 * 1024)
    assert services.usage(student)["near_full"]
    assert b"nearly out of space" in client.get(reverse("files:list")).content
    upload(client, "b.pdf", b"x", status=400)


def test_deleting_the_user_removes_their_files_from_disk(student):
    f = PrivateFile.objects.create(owner=student, file=SimpleUploadedFile("a.pdf", b"x"), size=1)
    path = f.file.path
    student.delete()
    assert not os.path.exists(path)


def test_download_uses_accel_redirect_when_enabled(client, student, settings):
    settings.USE_ACCEL_REDIRECT = True
    client.force_login(student)
    upload(client)
    f = PrivateFile.objects.get()
    r = client.get(reverse("files:download", args=[f.pk]))
    assert r["X-Accel-Redirect"] == f"/media/{f.file.name}" and r.content == b""


def test_filesize_filter_and_human():
    assert services.human(0) == "0 KB" and services.human(2048) == "2 KB" and services.human(3 * 1024 * 1024) == "3.0 MB"


def test_anonymous_redirected_and_nav(client, student, lecturer):
    assert client.get(reverse("files:list")).status_code == 302
    assert client.post(reverse("files:upload")).status_code == 302
    for u, dash in ((student, "accounts:student-dashboard"), (lecturer, "accounts:lecturer-dashboard")):
        client.force_login(u)
        assert reverse("files:list").encode() in client.get(reverse(dash)).content
