"""Site search. Every query starts from what the signed-in person is allowed to see, then matches the words."""
from django.db.models import Q
from django.urls import reverse

from apps.assignments.models import Assignment
from apps.content.models import Resource
from apps.courses import permissions as perm
from apps.courses.models import Course
from apps.files.models import PrivateFile
from apps.messaging.models import ForumTopic
from apps.messaging.services import allowed_recipients
from apps.quizzes.models import Quiz

MIN_LENGTH = 2
MAX_LENGTH = 80
PER_GROUP = 50
TABS = [("all", "All"), ("courses", "Courses"), ("materials", "Materials"), ("activities", "Activities"), ("forum", "Forum"), ("people", "People")]


def clean_query(raw):
    return " ".join((raw or "").split())[:MAX_LENGTH]


def _courses(user, q):
    # Students can find anything in the catalog; lecturers their own courses; administrators every course.
    qs = Course.objects.filter(is_visible=True) if user.role == "student" else perm.visible_courses_for(user)
    qs = qs.filter(Q(title__icontains=q) | Q(code__icontains=q) | Q(summary__icontains=q)).select_related("department", "semester").distinct()[:PER_GROUP]
    return [{"icon": "book", "title": f"{c.code} · {c.title}", "url": reverse("courses:detail", args=[c.pk]),
             "meta": " · ".join(x for x in (str(c.department or ""), str(c.semester or "")) if x) or "Course"} for c in qs]


def _materials(user, q):
    ids = perm.visible_courses_for(user).values_list("pk", flat=True)
    qs = Resource.objects.filter(topic__course_id__in=ids).filter(Q(title__icontains=q) | Q(description__icontains=q)).select_related("topic__course")
    if user.role == "student":
        qs = qs.filter(is_visible=True, topic__is_visible=True)
    out = [{"icon": "file-text" if r.kind == "file" else "arrow", "title": r.title, "url": reverse("courses:detail", args=[r.topic.course_id]),
            "meta": f"{r.topic.course.code} · {r.get_kind_display()} · {r.topic.title}"} for r in qs[:PER_GROUP]]
    out += [{"icon": "folder", "title": f.name, "url": reverse("files:list"), "meta": "Your private files"}
            for f in PrivateFile.objects.filter(owner=user, file__icontains=q)[:PER_GROUP]]
    return out


def _activities(user, q):
    ids = perm.visible_courses_for(user).values_list("pk", flat=True)
    quizzes = Quiz.objects.filter(course_id__in=ids, title__icontains=q).select_related("course")
    assignments = Assignment.objects.filter(course_id__in=ids, title__icontains=q).select_related("course")
    if user.role == "student":
        quizzes, assignments = quizzes.filter(is_visible=True), assignments.filter(is_visible=True)
    out = []
    for qz in quizzes[:PER_GROUP]:
        url = reverse("quizzes:student-detail", args=[qz.pk]) if user.role == "student" else reverse("quizzes:editor", args=[qz.pk])
        out.append({"icon": "edit", "title": qz.title, "url": url, "meta": f"{qz.course.code} · Quiz"})
    for a in assignments[:PER_GROUP]:
        out.append({"icon": "upload", "title": a.title, "url": reverse("assignments:detail", args=[a.pk]), "meta": f"{a.course.code} · Assignment"})
    return out


def _forum(user, q):
    ids = [c.pk for c in perm.visible_courses_for(user) if perm.can_view(user, c)]
    qs = ForumTopic.objects.filter(course_id__in=ids, title__icontains=q).select_related("course", "author")[:PER_GROUP]
    return [{"icon": "messages", "title": t.title, "url": reverse("messaging:topic", args=[t.pk]),
             "meta": f"Forum · {t.course.code} · {t.author.get_full_name() or t.author.username}"} for t in qs]


def _people(user, q):
    qs = allowed_recipients(user).filter(
        Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q) | Q(index_number__icontains=q)
        | (Q(email__icontains=q) if user.role == "admin" else Q(pk__in=[]))
    )
    if user.role != "admin":
        qs = qs.exclude(role="admin")  # their profile pages are not open to everyone
    qs = qs[:PER_GROUP]
    return [{"icon": "user", "title": p.get_full_name() or p.username, "url": reverse("accounts:person", args=[p.pk]),
             "meta": f"{p.get_role_display()} · {p.username}"} for p in qs]


GROUPS = {"courses": _courses, "materials": _materials, "activities": _activities, "forum": _forum, "people": _people}


def search(user, q, tab="all"):
    """(results, counts). results is the list for the chosen tab; counts has the size of every group."""
    if len(q) < MIN_LENGTH:
        return [], {}
    found = {key: fn(user, q) for key, fn in GROUPS.items()}
    counts = {k: len(v) for k, v in found.items()}
    if tab in found:
        return found[tab], counts
    # "All": a few from each group, in a fixed order
    return [r for key in GROUPS for r in found[key][:5]], counts
