from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.administration import backups, reports
from apps.core.jobs import dispatch
from apps.core.models import JobHeartbeat
from apps.messaging import tasks as msg_tasks
from apps.messaging.models import Notification
from apps.messaging.services import notify


@pytest.fixture(autouse=True)
def backup_dir(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path / "backups"


def send(users, text="New grade posted", url="/grades/", capture=None):
    with capture(execute=True):
        return notify(users, text, url)


# ---------- email notifications ----------

def test_notify_emails_people_with_an_address(student, lecturer, django_capture_on_commit_callbacks):
    student.email = "amal@uni.lk"; student.save()
    send([student, lecturer], capture=django_capture_on_commit_callbacks)  # lecturer has no address
    assert Notification.objects.count() == 2
    (m,) = mail.outbox
    assert m.to == ["amal@uni.lk"] and "New grade posted" in m.subject and m.subject.startswith("[Lumen]")
    assert "http://localhost:8000/grades/" in m.body and "Profile & settings" in m.body


def test_email_respects_the_switch_and_disabled_accounts(student, lecturer, django_capture_on_commit_callbacks):
    student.email = "a@uni.lk"; student.email_notifications = False; student.save()
    lecturer.email = "l@uni.lk"; lecturer.save()
    send([student, lecturer], capture=django_capture_on_commit_callbacks)
    assert [m.to for m in mail.outbox] == [["l@uni.lk"]]
    mail.outbox.clear()
    lecturer.is_active = False; lecturer.save()
    assert msg_tasks.email_notifications([lecturer.pk], "x", "/") == 0 and not mail.outbox


def test_in_app_notification_exists_even_when_queueing_fails(student, monkeypatch, django_capture_on_commit_callbacks):
    student.email = "a@uni.lk"; student.save()

    def boom(*a, **k):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(msg_tasks.email_notifications, "apply_async", boom)
    send([student], capture=django_capture_on_commit_callbacks)  # must not raise
    assert Notification.objects.filter(user=student).count() == 1 and not mail.outbox


def test_dispatch_reports_failure_instead_of_raising():
    class Dead:
        name = "dead"

        def apply_async(self, **kw):
            raise OSError("no broker")

    assert dispatch(Dead()) is False


def test_email_task_retries_on_smtp_trouble(student, monkeypatch):
    student.email = "a@uni.lk"; student.save()
    assert msg_tasks.email_notifications.autoretry_for == (OSError,) and msg_tasks.email_notifications.max_retries == 4


def test_non_local_url_is_not_used_in_the_link(student):
    student.email = "a@uni.lk"; student.save()
    msg_tasks.email_notifications([student.pk], "hi", "https://evil.example/x")
    assert "evil.example" not in mail.outbox[0].body


def test_profile_switch_for_emails(student):
    c = Client(); c.force_login(student)
    c.post(reverse("accounts:profile"), {"first_name": "A", "last_name": "B", "email": "a@uni.lk"})  # box left unticked
    student.refresh_from_db()
    assert student.email_notifications is False
    c.post(reverse("accounts:profile"), {"first_name": "A", "last_name": "B", "email": "a@uni.lk", "email_notifications": "on"})
    student.refresh_from_db()
    assert student.email_notifications is True


# ---------- scheduled jobs ----------

def test_every_scheduled_task_exists():
    from django.conf import settings

    from config.celery import app

    app.loader.import_default_modules()
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        assert entry["task"] in app.tasks, f"{name}: {entry['task']} is not a registered task"


def test_scheduler_task_closes_attempts_and_beats(db):
    from apps.quizzes.tasks import close_expired_attempts

    assert close_expired_attempts() == 0
    assert JobHeartbeat.objects.get(name="scheduler").last_run > timezone.now() - timedelta(minutes=1)


def test_overdue_attempt_is_submitted_by_the_task(enrolled, course):
    from decimal import Decimal

    from apps.quizzes.models import Attempt, Question, Quiz
    from apps.quizzes.tasks import close_expired_attempts

    q = Quiz.objects.create(course=course, title="Q", time_limit_minutes=10)
    Question.objects.create(quiz=q, kind="mcq", text="?", marks=Decimal(5), position=1)
    past = timezone.now() - timedelta(hours=1)
    a = Attempt.objects.create(quiz=q, student=enrolled, number=1, started_at=past, deadline_at=past + timedelta(minutes=10))
    assert close_expired_attempts() == 1
    a.refresh_from_db()
    assert a.status != "in_progress"


def test_backup_and_purge_tasks(admin_user):
    from apps.administration.tasks import make_backup, purge_audit_log
    from apps.core.models import AuditLog

    name = make_backup(keep=1)
    assert backups.path_for(name)
    old = AuditLog.objects.create(action="x")
    AuditLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=800))
    assert purge_audit_log() == 1


def test_certificate_task(enrolled, course):
    from apps.completion import services
    from apps.completion.models import Certificate
    from apps.completion.tasks import issue_certificates

    rule = services.rule_for(course)
    rule.min_attendance_percent = 0  # needs a record: none yet, so nobody qualifies
    rule.save()
    assert issue_certificates() == 0 and not Certificate.objects.exists()


# ---------- the admin warning ----------

@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_overview_warns_when_the_scheduler_is_silent(db):
    assert any("Background jobs are not running" in t for _, t, _ in reports.attention())
    JobHeartbeat.objects.create(name="scheduler", last_run=timezone.now())
    assert not any("Background jobs are not running" in t for _, t, _ in reports.attention())
    JobHeartbeat.objects.update(last_run=timezone.now() - timedelta(minutes=9))
    assert any("Background jobs are not running" in t for _, t, _ in reports.attention())


def test_no_warning_in_eager_mode(db):
    assert not any("Background jobs" in t for _, t, _ in reports.attention())


@pytest.fixture(autouse=True)
def _reset_pause():
    from apps.core import jobs

    jobs._down_until = 0.0
    yield
    jobs._down_until = 0.0


def test_dispatch_pauses_after_a_failure():
    calls = []

    class Dead:
        name = "dead"

        def apply_async(self, **kw):
            calls.append(1)
            raise OSError("no broker")

    assert dispatch(Dead()) is False and dispatch(Dead()) is False
    assert len(calls) == 1  # the second call was skipped, so no second wait
