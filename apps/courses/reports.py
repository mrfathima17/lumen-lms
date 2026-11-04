"""Figures for the lecturer's course report page. All computed in bulk from existing records."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.assignments.models import Submission
from apps.attendance import services as attendance
from apps.completion import services as completion
from apps.grading import services as grading
from apps.grading.models import GradeBand
from apps.quizzes.models import Answer, Attempt

AT_RISK_BELOW = Decimal("50")
WEEKS = 6


def _pct(n, d):
    return None if not d else int(round(n * 100 / d))


def build(course, with_attendance=True, with_quizzes=True):
    students = attendance.active_students(course)
    ids = [s.pk for s in students]
    items = list(course.grade_items.all())
    fractions = grading.load_fractions(course, ids)
    percents = {}
    for s in students:
        p, _, _ = grading.course_percent(items, fractions, s.pk)
        if p is not None:
            percents[s.pk] = p
    avg = round(sum(percents.values()) / len(percents), 1) if percents else None

    # grade distribution by band (highest band first); students without a mark yet are left out
    bands = list(GradeBand.objects.order_by("-min_percent"))
    dist = []
    if bands and percents:
        counts = defaultdict(int)
        for p in percents.values():
            for b in bands:
                if p >= b.min_percent:
                    counts[b.letter] += 1
                    break
            else:
                counts[bands[-1].letter] += 1
        top = max(counts.values())
        letters = [b.letter for b in bands]
        dist = [{"label": l, "count": counts[l], "pct": int(round(counts[l] * 100 / top)) if top else 0} for l in dict.fromkeys(letters)]

    # completion
    rule = completion.rule_for(course)
    complete = tracked = 0
    for s in students:
        r = completion.evaluate(course, s, rule)
        if r["tracked"]:
            tracked += 1
            complete += 1 if r["complete"] else 0
    completion_rate = _pct(complete, tracked)

    # attendance and at-risk
    att_avg, below = None, set()
    if with_attendance:
        rows = attendance.course_overview(course)
        vals = [r["stats"]["percent"] for r in rows if r["stats"]["percent"] is not None]
        att_avg = int(round(sum(vals) / len(vals))) if vals else None
        below = {r["student"].pk for r in rows if r["below"]}
    at_risk = sorted({pk for pk, p in percents.items() if p < AT_RISK_BELOW} | below)
    risk_students = [s for s in students if s.pk in at_risk]

    # most missed questions
    missed = []
    if with_quizzes:
        stat = defaultdict(lambda: [0, 0, None])
        qs = Answer.objects.filter(attempt__quiz__course=course, attempt__status=Attempt.Status.GRADED, awarded__isnull=False).select_related("question", "attempt__quiz")
        for a in qs:
            st = stat[a.question_id]
            st[2] = a.question
            st[1] += 1
            if a.awarded >= a.question.marks:
                st[0] += 1
        for qid, (ok, n, q) in stat.items():
            if n >= 3:
                missed.append({"text": q.text[:90], "quiz": q.quiz.title, "pct": _pct(ok, n), "n": n})
        missed.sort(key=lambda r: r["pct"])
        missed = missed[:5]

    # weekly activity: submissions and finished quiz attempts, last WEEKS weeks
    today = timezone.localdate()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=WEEKS - 1)
    weeks = [{"label": (start + timedelta(weeks=i)).strftime("%d %b").lstrip("0"), "count": 0} for i in range(WEEKS)]
    since = timezone.make_aware(timezone.datetime.combine(start, timezone.datetime.min.time()))
    stamps = list(Submission.objects.filter(assignment__course=course, submitted_at__gte=since).values_list("submitted_at", flat=True))
    stamps += list(Attempt.objects.filter(quiz__course=course, submitted_at__gte=since).values_list("submitted_at", flat=True))
    for t in stamps:
        i = (timezone.localtime(t).date() - start).days // 7
        if 0 <= i < WEEKS:
            weeks[i]["count"] += 1
    top = max((w["count"] for w in weeks), default=0)
    for w in weeks:
        w["pct"] = int(round(w["count"] * 100 / top)) if top else 0

    return {"students": len(students), "average": avg, "completion_rate": completion_rate, "attendance": att_avg,
            "at_risk": risk_students, "dist": dist, "missed": missed, "weeks": weeks, "graded": len(percents)}
