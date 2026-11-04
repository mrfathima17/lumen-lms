import re

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Enrolment

User = get_user_model()


def parse_identifiers(text):
    """Split pasted usernames / index numbers on commas, spaces and new lines; drop blanks and repeats, keep order."""
    seen, out = set(), []
    for token in re.split(r"[\s,;]+", text or ""):
        token = token.strip()
        if token and token.lower() not in seen:
            seen.add(token.lower())
            out.append(token)
    return out


def find_user(ident):
    """By username, then index number, then e-mail address (only when exactly one account has that address)."""
    user = User.objects.filter(username__iexact=ident).first() or User.objects.filter(index_number__iexact=ident).first()
    if user or "@" not in ident:
        return user
    matches = list(User.objects.filter(email__iexact=ident)[:2])
    return matches[0] if len(matches) == 1 else None


_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def cohort_of(user):
    """The batch a student belongs to: the year in their index number, else in their username (s2026-0142 -> 2026). None if there is none."""
    for text in (user.index_number or "", user.username or ""):
        m = _YEAR.search(text)
        if m:
            return m.group(1)
    return None


def cohorts():
    """[(year, number of students)], newest batch first."""
    counts = {}
    for pk, idx, name in User.objects.filter(role="student").values_list("pk", "index_number", "username"):
        year = cohort_of(User(index_number=idx, username=name))
        if year:
            counts[year] = counts.get(year, 0) + 1
    return sorted(counts.items(), reverse=True)


def cohort_students(year):
    return [u for u in User.objects.filter(role="student").order_by("last_name", "first_name", "username") if cohort_of(u) == year]


@transaction.atomic
def enrol_users(course, role, identifiers=(), cohort=None):
    """Add people to a course as students (an enrolment) or as lecturers (the course's lecturer list).

    People come from pasted usernames / index numbers / e-mails and, for students, from a whole batch. Anyone whose account role does not
    match is skipped and reported. Returns {enrolled, already: [users], not_found, wrong_role: [what was typed]}."""
    result = {"enrolled": [], "already": [], "not_found": [], "wrong_role": []}
    people, seen = [], set()

    def add(user):
        if user.pk not in seen:
            seen.add(user.pk)
            people.append((user, user.username))

    for ident in identifiers:
        user = find_user(ident)
        if not user:
            result["not_found"].append(ident)
        elif user.role != role:
            result["wrong_role"].append(ident)
            seen.add(user.pk)
        else:
            add(user)
    if cohort and role == "student":
        for user in cohort_students(cohort):
            add(user)
    if role == "lecturer":
        have = set(course.lecturers.values_list("pk", flat=True))
        for user, _ in people:
            if user.pk in have:
                result["already"].append(user)
            else:
                course.lecturers.add(user)
                result["enrolled"].append(user)
    else:
        for user, _ in people:
            _, created = Enrolment.objects.get_or_create(course=course, user=user)
            result["enrolled" if created else "already"].append(user)
    return result


def people_in(course):
    """Everyone on a course for the 'Currently enrolled' list: lecturers first, then students. Dicts of user, role, status."""
    rows = [{"user": u, "role": "lecturer", "status": "active"} for u in course.lecturers.order_by("last_name", "first_name", "username")]
    rows += [{"user": e.user, "role": "student", "status": e.status} for e in course.enrolments.select_related("user")]
    return rows


def preview_enrol(course, identifiers):
    """What enrol_students would do, without changing anything. Same result shape; values are display names."""
    result = {"enrolled": [], "already": [], "not_found": [], "not_student": []}
    already = set(Enrolment.objects.filter(course=course).values_list("user_id", flat=True))
    for ident in identifiers:
        user = find_user(ident)
        if not user:
            result["not_found"].append(ident)
        elif user.role != "student":
            result["not_student"].append(ident)
        elif user.pk in already:
            result["already"].append(user)
        else:
            result["enrolled"].append(user)
    return result


@transaction.atomic
def enrol_students(course, identifiers):
    """Enrol users found by username or index number. Returns lists describing what happened to each identifier."""
    result = {"enrolled": [], "already": [], "not_found": [], "not_student": []}
    for ident in identifiers:
        user = find_user(ident)
        if not user:
            result["not_found"].append(ident)
        elif user.role != "student":
            result["not_student"].append(ident)
        else:
            _, created = Enrolment.objects.get_or_create(course=course, user=user)
            result["enrolled" if created else "already"].append(ident)
    return result


def next_topic_position(course):
    last = course.topics.order_by("-position").first()
    return (last.position + 1) if last else 0
