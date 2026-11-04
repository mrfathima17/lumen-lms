import pytest
from django.core.exceptions import ValidationError

from apps.core.models import AllowedNetwork, SiteSettings
from apps.core.network import ip_allowed


def test_site_settings_defaults(db):
    s = SiteSettings.load()
    assert s.late_penalty_percent_per_day == 10
    assert s.quiz_review_policy == "after_close"
    assert s.attendance_warning_percent == 80
    assert s.private_files_quota_mb == 500
    assert s.audit_log_retention_months == 12
    assert SiteSettings.load().pk == 1 and SiteSettings.objects.count() == 1


def test_no_rules_means_open(db):
    assert ip_allowed("8.8.8.8", "quiz")


def test_quiz_rule_restricts_only_quiz_scope(db):
    AllowedNetwork.objects.create(name="Campus", cidr="10.20.0.0/16", scope="quiz")
    assert ip_allowed("10.20.5.9", "quiz")
    assert not ip_allowed("8.8.8.8", "quiz")
    assert ip_allowed("8.8.8.8", "admin")


def test_inactive_rule_ignored_and_whole_site_rule(db):
    AllowedNetwork.objects.create(name="Old", cidr="10.0.0.0/8", scope="quiz", is_active=False)
    assert ip_allowed("8.8.8.8", "quiz")
    AllowedNetwork.objects.create(name="All", cidr="192.168.0.0/24", scope="all")
    assert not ip_allowed("8.8.8.8", "quiz") and ip_allowed("192.168.0.7", "quiz")


def test_bad_ip_denied_when_rules_exist(db):
    AllowedNetwork.objects.create(name="Campus", cidr="10.0.0.0/8", scope="quiz")
    assert not ip_allowed(None, "quiz") and not ip_allowed("garbage", "quiz")


def test_cidr_validation(db):
    with pytest.raises(ValidationError):
        AllowedNetwork(name="x", cidr="not-a-network").full_clean()
    AllowedNetwork(name="ok", cidr="203.0.113.7/32").full_clean()


def test_admin_area_blocked_from_other_network(client, admin_user, db):
    AllowedNetwork.objects.create(name="Office", cidr="203.0.113.0/24", scope="admin")
    client.force_login(admin_user)
    assert client.get("/admin-panel/", REMOTE_ADDR="8.8.8.8").status_code == 403
    assert client.get("/admin-panel/", REMOTE_ADDR="203.0.113.9").status_code == 200


def test_x_forwarded_for_ignored_unless_trusted(client, admin_user, settings):
    AllowedNetwork.objects.create(name="Office", cidr="203.0.113.0/24", scope="admin")
    client.force_login(admin_user)
    settings.TRUST_PROXY_HEADERS = False
    assert client.get("/admin-panel/", REMOTE_ADDR="8.8.8.8", HTTP_X_FORWARDED_FOR="203.0.113.9").status_code == 403
    settings.TRUST_PROXY_HEADERS = True
    assert client.get("/admin-panel/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="203.0.113.9").status_code == 200


def test_maintenance_mode(client, student, admin_user, db):
    s = SiteSettings.load(); s.maintenance_mode = True; s.save()
    client.force_login(student)
    assert client.get("/student/").status_code == 503
    client.force_login(admin_user)
    assert client.get("/admin-panel/").status_code == 200
    assert client.get("/sign-in/").status_code in (200, 302)


def test_healthz_is_open_even_in_maintenance(client, db):
    from apps.core.models import SiteSettings

    s = SiteSettings.load()
    s.maintenance_mode = True
    s.save()
    r = client.get("/healthz/")
    assert r.status_code == 200 and r.content == b"ok"
