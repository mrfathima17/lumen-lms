"""Gradebook maths. Everything is computed in bulk (a handful of queries per course) and rounded only at the end."""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.assignments.models import Submission
from apps.quizzes.models import Attempt

from .models import CourseResult, GradeBand, GradeItem, ManualMark

ZERO = Decimal("0")
HUNDRED = Decimal("100")


def q2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def load_fractions(course, student_ids):
    """Return {(item_id, student_id): fraction between 0 and 1}. A missing key means "not graded yet"."""
    items = list(course.grade_items.all())
    out = {}
    a_ids = [i.assignment_id for i in items if i.kind == GradeItem.Kind.ASSIGNMENT and i.assignment_id]
    q_ids = [i.quiz_id for i in items if i.kind == GradeItem.Kind.QUIZ and i.quiz_id]
    m_ids = [i.pk for i in items if i.kind == GradeItem.Kind.MANUAL]
    by_assignment = {i.assignment_id: i for i in items if i.assignment_id}
    by_quiz = {i.quiz_id: i for i in items if i.quiz_id}
    by_pk = {i.pk: i for i in items}
    if a_ids:
        for s in Submission.objects.filter(assignment_id__in=a_ids, student_id__in=student_ids, status="graded").select_related("assignment"):
            if s.final_mark is not None and s.assignment.max_mark > 0:
                out[(by_assignment[s.assignment_id].pk, s.student_id)] = s.final_mark / s.assignment.max_mark
    if q_ids:
        best = defaultdict(lambda: None)
        for a in Attempt.objects.filter(quiz_id__in=q_ids, student_id__in=student_ids, status="graded").select_related("quiz"):
            key = (a.quiz_id, a.student_id)
            if best[key] is None or a.score > best[key].score:
                best[key] = a
        totals = {i.quiz_id: i.quiz.total_marks for i in items if i.kind == GradeItem.Kind.QUIZ and i.quiz_id}
        for (quiz_id, sid), a in best.items():
            total = totals.get(quiz_id) or ZERO
            if total > 0:
                out[(by_quiz[quiz_id].pk, sid)] = a.score / total  # best attempt counts
    if m_ids:
        for m in ManualMark.objects.filter(item_id__in=m_ids, student_id__in=student_ids):
            mx = by_pk[m.item_id].max_mark
            if mx and mx > 0:
                out[(m.item_id, m.student_id)] = m.mark / mx
    return out


def course_percent(items, fractions, student_id):
    """Weighted percentage over the items graded so far. Returns (percent or None, graded_weight, total_weight)."""
    total_w = sum((i.weight for i in items), ZERO)
    graded_w, acc = ZERO, ZERO
    for i in items:
        f = fractions.get((i.pk, student_id))
        if f is not None:
            graded_w += i.weight
            acc += f * i.weight
    if graded_w == 0:
        return None, graded_w, total_w
    return q2(acc / graded_w * HUNDRED), graded_w, total_w


def band_for(percent):
    """The highest band the percentage reaches; None if no scale is defined."""
    return GradeBand.objects.filter(min_percent__lte=percent).order_by("-min_percent").first()


def student_course_summary(course, student):
    items = list(course.grade_items.select_related("assignment", "quiz"))
    fr = load_fractions(course, [student.pk])
    pct, gw, tw = course_percent(items, fr, student.pk)
    rows = []
    for i in items:
        f = fr.get((i.pk, student.pk))
        rows.append({"item": i, "percent": None if f is None else q2(f * HUNDRED)})
    band = band_for(pct) if pct is not None else None
    return {"course": course, "rows": rows, "percent": pct, "band": band, "graded_weight": gw, "total_weight": tw,
            "coursework": _kind_average(rows, quizzes=False), "quizzes": _kind_average(rows, quizzes=True),
            "graded": sum(1 for r in rows if r["percent"] is not None), "pending": sum(1 for r in rows if r["percent"] is None)}


def _kind_average(rows, quizzes):
    """Weighted average of the graded rows that are quizzes (or, with quizzes=False, everything else). None if there are none."""
    picked = [r for r in rows if r["percent"] is not None and (r["item"].kind == "quiz") == quizzes and r["item"].weight]
    weight = sum(r["item"].weight for r in picked)
    if not weight:
        return None
    return q2(sum((r["percent"] * r["item"].weight for r in picked), ZERO) / weight)


@transaction.atomic
def publish_results(course, actor, now=None):
    """Freeze a result for every active student who has at least one graded item. Returns (published, skipped_usernames)."""
    now = now or timezone.now()
    students = [e.user for e in course.enrolments.filter(status="active").select_related("user")]
    items = list(course.grade_items.all())
    fr = load_fractions(course, [s.pk for s in students])
    published, skipped, notified = 0, [], []
    for s in students:
        pct, _, _ = course_percent(items, fr, s.pk)
        band = band_for(pct) if pct is not None else None
        if pct is None or band is None:
            skipped.append(s.username)
            continue
        CourseResult.objects.update_or_create(course=course, student=s, defaults={
            "percent": pct, "letter": band.letter, "points": band.points, "credits": course.credits, "published_at": now, "published_by": actor})
        published += 1
        notified.append(s)
    from apps.messaging.services import notify

    notify(notified, f"Your {course.code} result has been published", "/results/", "grade")
    return published, skipped


def gpa(results):
    """GPA = sum(points x credits) / sum(credits). None when there are no credits."""
    credits = sum(r.credits for r in results)
    if not credits:
        return None
    return q2(sum((r.points * r.credits for r in results), ZERO) / credits)


def results_by_semester(student):
    """Published results grouped by semester, each with its GPA, plus the cumulative GPA."""
    rows = list(CourseResult.objects.filter(student=student).select_related("course__semester"))
    groups = defaultdict(list)
    for r in rows:
        groups[r.course.semester.name if r.course.semester else "No semester"].append(r)
    semesters = [{"name": n, "results": rs, "gpa": gpa(rs), "credits": sum(r.credits for r in rs)} for n, rs in sorted(groups.items())]
    return semesters, gpa(rows), sum(r.credits for r in rows)
