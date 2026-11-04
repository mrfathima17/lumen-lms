import pytest
from django.urls import reverse

from apps.core.models import AuditLog
from apps.courses import services
from apps.courses.models import Enrolment

URL = "administration:bulk-enrolment"


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def post(client, course, **kw):
    data = {"course": course.pk, "role": "student", "cohort": "", "identifiers": ""}
    data.update(kw)
    return client.post(reverse(URL), data, follow=True)


def texts(r):
    return [str(m) for m in r.context["messages"]]


# ---------- page ----------

def test_page_matches_the_new_layout(admin_client, course, student):
    Enrolment.objects.create(course=course, user=student)
    html = admin_client.get(reverse(URL)).content.decode()
    for text in ("1 · Choose course", "Role in course", "2 · Choose users", "By cohort", "Or paste usernames / emails (one per line)", "Enrol users", "Currently enrolled (2)", "Remove"):
        assert text in html, text
    assert "CS201 · Database Systems" in html and "Batch 2026 (1)" in html and "s2026-0142" in html
    assert "Preview" not in html


def test_list_follows_the_course_in_the_url(admin_client, course, student, lecturer):
    from apps.courses.models import Course

    other = Course.objects.create(code="CS999", title="Empty", credits=1)
    assert b"Currently enrolled (1)" in admin_client.get(reverse(URL) + f"?course={course.pk}").content  # just the lecturer
    assert b"Currently enrolled (0)" in admin_client.get(reverse(URL) + f"?course={other.pk}").content
    assert admin_client.get(reverse(URL) + "?course=99999").status_code == 200


def test_admin_only(client, student):
    client.force_login(student)
    assert client.get(reverse(URL)).status_code == 403
    assert client.post(reverse("administration:bulk-enrolment-remove"), {}).status_code == 403


# ---------- cohorts and lookup ----------

def test_cohort_is_the_year_in_the_index_number_or_username(make_user):
    from apps.accounts.models import User

    assert services.cohort_of(User(username="s2026-0142")) == "2026"
    assert services.cohort_of(User(username="x", index_number="2024/CS/007")) == "2024"
    assert services.cohort_of(User(username="nperera")) is None
    assert services.cohort_of(User(username="u12345")) is None  # five digits are not a year


def test_cohort_list_counts_students_only(make_user):
    make_user("s2026-0001", "student"); make_user("s2026-0002", "student"); make_user("s2025-0003", "student"); make_user("l2026-1", "lecturer")
    assert services.cohorts() == [("2026", 2), ("2025", 1)]


def test_lookup_by_email_only_when_unique(make_user):
    a = make_user("amal", "student", email="amal@example.com")
    make_user("b1", "student", email="shared@example.com"); make_user("b2", "student", email="shared@example.com")
    assert services.find_user("AMAL@example.com") == a
    assert services.find_user("shared@example.com") is None  # two accounts: do not guess
    assert services.find_user("nobody@example.com") is None


# ---------- enrolling ----------

def test_paste_students_by_username_index_and_email(admin_client, course, make_user):
    a = make_user("s2026-0201", "student")
    b = make_user("s2026-0202", "student", index_number="IDX-7")
    c = make_user("s2026-0203", "student", email="c@example.com")
    r = post(admin_client, course, identifiers="s2026-0201\nIDX-7\nc@example.com\nghost")
    assert {e.user for e in Enrolment.objects.filter(course=course)} == {a, b, c}
    msgs = " ".join(texts(r))
    assert "Enrolled 3 students in CS201" in msgs and "Not found: ghost" in msgs
    assert AuditLog.objects.get(action="bulk_enrol").detail == "3 enrolled of 4"


def test_whole_cohort(admin_client, course, make_user):
    for i in range(3):
        make_user(f"s2026-10{i}", "student")
    make_user("s2025-999", "student")
    r = post(admin_client, course, cohort="2026")
    assert Enrolment.objects.filter(course=course).count() == 3 and "Enrolled 3 students" in " ".join(texts(r))
    post(admin_client, course, cohort="2026", identifiers="s2025-999")  # again plus one more: no duplicates
    assert Enrolment.objects.filter(course=course).count() == 4


def test_already_enrolled_and_wrong_role_reported(admin_client, course, student, lecturer):
    Enrolment.objects.create(course=course, user=student)
    msgs = " ".join(texts(post(admin_client, course, identifiers=f"{student.username} {lecturer.username}")))
    assert f"Already on CS201: {student.username}" in msgs and f"Not students, so skipped: {lecturer.username}" in msgs
    assert Enrolment.objects.filter(course=course).count() == 1


def test_lecturers_join_the_course_list(admin_client, course, make_user, student):
    new = make_user("nsilva", "lecturer")
    msgs = " ".join(texts(post(admin_client, course, role="lecturer", identifiers=f"nsilva {student.username}")))
    assert new in course.lecturers.all() and "Added 1 lecturer to CS201" in msgs and f"Not lecturers, so skipped: {student.username}" in msgs
    assert not Enrolment.objects.filter(user=new).exists()
    assert "lecturer(s) added" in AuditLog.objects.get(action="bulk_enrol").detail
    assert "Already on CS201: nsilva" in " ".join(texts(post(admin_client, course, role="lecturer", identifiers="nsilva")))


@pytest.mark.parametrize("data,error", [({"identifiers": "  "}, "Choose a cohort or paste"), ({"role": "lecturer", "cohort": "2026"}, "Cohorts are groups of students"),
                                        ({"role": "admin", "identifiers": "x"}, "Select a valid choice"), ({"cohort": "1999"}, "Select a valid choice"),
                                        ({"identifiers": " ".join(f"u{i}" for i in range(1001))}, "more than 1000")])
def test_validation(admin_client, course, student, data, error):
    r = admin_client.post(reverse(URL), {"course": course.pk, "role": "student", "cohort": "", "identifiers": "", **data})
    assert r.status_code == 200 and error in r.content.decode() and not Enrolment.objects.exists()


def test_unknown_course_is_a_form_error(admin_client):
    assert admin_client.post(reverse(URL), {"course": 9999, "role": "student", "identifiers": "x"}).status_code == 200


# ---------- remove ----------

def test_remove_student_and_lecturer(admin_client, course, student, lecturer):
    Enrolment.objects.create(course=course, user=student)
    r = admin_client.post(reverse("administration:bulk-enrolment-remove"), {"course": course.pk, "user": student.pk, "role": "student"})
    assert r.status_code == 302 and r["Location"].endswith(f"?course={course.pk}") and not Enrolment.objects.exists()
    admin_client.post(reverse("administration:bulk-enrolment-remove"), {"course": course.pk, "user": lecturer.pk, "role": "lecturer"})
    assert not course.lecturers.exists()
    assert [a.detail for a in AuditLog.objects.filter(action="unenrol").order_by("id")] == [student.username, f"{lecturer.username} (lecturer)"]


def test_remove_needs_post_and_real_ids(admin_client, course):
    assert admin_client.get(reverse("administration:bulk-enrolment-remove")).status_code == 405
    assert admin_client.post(reverse("administration:bulk-enrolment-remove"), {"course": 999, "user": 999}).status_code == 404
