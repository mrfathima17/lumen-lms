"""Completion rules and certificates."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.attendance import services as attendance
from apps.grading import services as grading
from apps.quizzes.models import Attempt, Quiz

from .models import Certificate, CompletionRule


def rule_for(course):
    return CompletionRule.objects.get_or_create(course=course)[0]


def _check(key, label, ok, detail):
    return {"key": key, "label": label, "ok": ok, "detail": detail}


def evaluate(course, student, rule=None):
    """Check one student against the course's rules.

    Returns {"tracked": bool, "checks": [...], "complete": bool, "met": int, "total": int, "percent": int}.
    """
    rule = rule or rule_for(course)
    checks = []
    if rule.require_assignments:
        ids = list(Assignment.objects.filter(course=course, is_visible=True).values_list("pk", flat=True))
        done = Submission.objects.filter(assignment_id__in=ids, student=student).values("assignment_id").distinct().count()
        checks.append(_check("assignments", "Submit all assignments", done == len(ids), f"{done} of {len(ids)}" if ids else "No assignments yet"))
    if rule.min_quiz_percent is not None:
        quizzes = list(Quiz.objects.filter(course=course, is_visible=True))
        if quizzes:
            best = {}
            for a in Attempt.objects.filter(quiz__in=quizzes, student=student, status="graded"):
                if a.score is not None and (a.quiz_id not in best or a.score > best[a.quiz_id]):
                    best[a.quiz_id] = a.score
            fractions = []
            for q in quizzes:
                total = q.total_marks
                fractions.append((best.get(q.pk, Decimal(0)) / total) if total > 0 else Decimal(0))
            avg = (sum(fractions) / len(fractions) * 100).quantize(Decimal("0.1"))
            checks.append(_check("quizzes", f"Quiz average at least {rule.min_quiz_percent}%", avg >= rule.min_quiz_percent, f"{avg}%"))
        else:
            checks.append(_check("quizzes", f"Quiz average at least {rule.min_quiz_percent}%", False, "No quizzes yet"))
    if rule.min_attendance_percent is not None:
        pct = attendance.student_course_stats(course, student)["percent"]
        checks.append(_check("attendance", f"Attendance at least {rule.min_attendance_percent}%", pct is not None and pct >= rule.min_attendance_percent,
                             "Nothing recorded yet" if pct is None else f"{pct}%"))
    if rule.min_final_percent is not None:
        items = list(course.grade_items.all())
        fr = grading.load_fractions(course, [student.pk])
        pct, _, _ = grading.course_percent(items, fr, student.pk)
        checks.append(_check("final", f"Course mark at least {rule.min_final_percent}%", pct is not None and pct >= rule.min_final_percent,
                             "Not graded yet" if pct is None else f"{pct}%"))
    met = sum(1 for c in checks if c["ok"])
    total = len(checks)
    return {"tracked": total > 0, "checks": checks, "complete": total > 0 and met == total, "met": met, "total": total,
            "percent": round(100 * met / total) if total else 0}


def issue_certificate(course, student, now=None):
    """Create the certificate (once). Returns (certificate, created). A revoked certificate is never recreated."""
    existing = Certificate.objects.filter(course=course, student=student).first()
    if existing:
        return existing, False
    if getattr(student, "preview_course_id", None):
        return None, False  # a lecturer previewing as a student never earns a certificate
    try:
        with transaction.atomic():
            cert = Certificate.objects.create(
                course=course, student=student, issued_at=now or timezone.now(),
                student_name=student.get_full_name() or student.username, course_title=course.title, course_code=course.code,
            )
    except IntegrityError:  # two requests at once: the other one won
        return Certificate.objects.get(course=course, student=student), False
    from apps.messaging.services import notify

    notify([student], f"You completed {course.code} — your certificate is ready.", "/certificates/", "info")
    return cert, True


def award_if_complete(course, student, rule=None):
    """Issue a certificate when the rules are met and the course issues them automatically. Returns the certificate or None."""
    rule = rule or rule_for(course)
    if not rule.auto_certificate:
        return Certificate.objects.filter(course=course, student=student).first()
    if getattr(student, "preview_course_id", None):
        return None
    if evaluate(course, student, rule)["complete"]:
        return issue_certificate(course, student)[0]
    return Certificate.objects.filter(course=course, student=student).first()


def roster(course):
    """Every active student with their completion state, for the lecturer."""
    rule = rule_for(course)
    certs = {c.student_id: c for c in Certificate.objects.filter(course=course)}
    rows = []
    for s in attendance.active_students(course):
        r = evaluate(course, s, rule)
        rows.append({"student": s, "result": r, "certificate": certs.get(s.pk)})
    return rows


def issue_all(course):
    """Issue certificates to everyone who qualifies and has none. Returns the number issued."""
    n = 0
    rule = rule_for(course)
    for row in roster(course):
        if row["result"]["complete"] and not row["certificate"]:
            if issue_certificate(course, row["student"])[1]:
                n += 1
    return n


def revoke(cert, now=None):
    if cert.revoked_at is None:
        cert.revoked_at = now or timezone.now()
        cert.save(update_fields=["revoked_at"])
    return cert


def issue_due():
    """Issue certificates for every course with automatic certificates and at least one rule. Returns the number issued."""
    total = 0
    for rule in CompletionRule.objects.filter(auto_certificate=True).select_related("course"):
        if rule.any_rule:
            total += issue_all(rule.course)
    return total


def activity_checklist(course, student):
    """Everything a student can do in a course, grouped by topic, with a done flag. Returns (sections, done, total).

    Materials are ticked by the student; assignments, quizzes and surveys tick themselves when handed in or answered.
    """
    from apps.content.models import ResourceDone
    from apps.surveys.models import Submission as SurveySubmission

    sections, done_n, total_n = [], 0, 0
    ticked = set(ResourceDone.objects.filter(user=student, resource__topic__course=course).values_list("resource_id", flat=True))
    handed = set(Submission.objects.filter(assignment__course=course, student=student).values_list("assignment_id", flat=True))
    by_topic = {}
    for a in Assignment.objects.filter(course=course, is_visible=True).order_by("due_at"):
        by_topic.setdefault(a.topic_id, []).append(a)
    for t in course.topics.filter(is_visible=True):
        items = [{"kind": "file" if r.kind == "file" else "link", "title": r.title, "url": ("content:view", r.pk), "done": r.pk in ticked, "manual": True, "pk": r.pk}
                 for r in t.resources.filter(is_visible=True)]
        items += [{"kind": "assignment", "title": a.title, "url": ("assignments:detail", a.pk), "done": a.pk in handed, "manual": False} for a in by_topic.pop(t.pk, [])]
        if items:
            sections.append({"title": t.title, "items": items})
    loose = [a for group in by_topic.values() for a in group]
    extra = [{"kind": "assignment", "title": a.title, "url": ("assignments:detail", a.pk), "done": a.pk in handed, "manual": False} for a in loose]
    quizzes = Quiz.objects.filter(course=course, is_visible=True)
    attempted = set(Attempt.objects.filter(quiz__in=quizzes, student=student).exclude(status="in_progress").values_list("quiz_id", flat=True))
    extra += [{"kind": "quiz", "title": q.title, "url": ("quizzes:student-detail", q.pk), "done": q.pk in attempted, "manual": False} for q in quizzes]
    answered = set(SurveySubmission.objects.filter(survey__course=course, student=student).values_list("survey_id", flat=True))
    for sv in course.surveys.filter(is_visible=True):
        extra.append({"kind": "poll" if sv.kind == "poll" else "survey", "title": sv.title, "url": ("surveys:student-detail", sv.pk), "done": sv.pk in answered, "manual": False})
    if extra:
        sections.append({"title": "Assignments, quizzes and polls", "items": extra})
    for sec in sections:
        for it in sec["items"]:
            total_n += 1
            done_n += it["done"]
    return sections, done_n, total_n
