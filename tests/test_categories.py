from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.courses.models import Category, Course

LIST = "courses:admin-categories"


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def add(client, **data):
    return client.post(reverse(LIST), data)


def test_page_shows_the_three_cards(admin_client, course):
    html = admin_client.get(reverse(LIST)).content.decode()
    assert "<h2>Faculties</h2>" in html and "<h2>Departments</h2>" in html and "<h2>Semesters</h2>" in html
    assert "Computer Science" in html and "Semester 3" in html
    assert "New department name" in html and "New faculty name" in html and "New semester name" in html


def test_add_faculty_and_department_in_it(admin_client):
    assert add(admin_client, name="Computing", kind="faculty").status_code == 302
    fac = Category.objects.get(kind="faculty")
    add(admin_client, name="Software Engineering", kind="department", faculty=fac.pk)
    dept = Category.objects.get(kind="department")
    assert dept.faculty == fac and fac.departments.count() == 1
    html = admin_client.get(reverse(LIST)).content.decode()
    assert "Software Engineering" in html and "Computing" in html


def test_faculty_must_be_a_faculty(admin_client):
    other = Category.objects.create(name="Maths", kind="department")
    r = add(admin_client, name="Stats", kind="department", faculty=other.pk)
    assert r.status_code == 200 and not Category.objects.filter(name="Stats").exists()


def test_faculty_and_dates_are_ignored_on_the_wrong_kind(admin_client):
    fac = Category.objects.create(name="Computing", kind="faculty")
    add(admin_client, name="Odd", kind="faculty", faculty=fac.pk, start_date="2026-01-01", end_date="2026-06-01")
    odd = Category.objects.get(name="Odd")
    assert odd.faculty is None and odd.start_date is None and odd.end_date is None


def test_unknown_kind_falls_back_to_department(admin_client):
    add(admin_client, name="Physics", kind="nonsense")
    assert Category.objects.get(name="Physics").kind == "department"


def test_duplicate_name_is_refused_whatever_the_case(admin_client):
    Category.objects.create(name="Business", kind="department")
    r = add(admin_client, name="  business ", kind="department")
    assert r.status_code == 200 and "already exists" in r.content.decode()
    assert Category.objects.filter(kind="department").count() == 1
    # The same name is fine for another kind.
    assert add(admin_client, name="Business", kind="faculty").status_code == 302


def test_semester_dates_validation(admin_client):
    r = add(admin_client, name="S1", kind="semester", start_date="2026-06-01", end_date="2026-01-01")
    assert r.status_code == 200 and "after the start date" in r.content.decode()
    r = add(admin_client, name="S1", kind="semester", start_date="2026-06-01")
    assert r.status_code == 200 and "both dates" in r.content.decode()
    assert not Category.objects.filter(name="S1").exists()
    assert add(admin_client, name="S1", kind="semester").status_code == 302  # dates stay optional


def test_semester_status_follows_the_dates(db):
    today = timezone.localdate()
    mk = lambda a, b: Category(kind="semester", name="x", start_date=today + timedelta(days=a), end_date=today + timedelta(days=b))
    assert mk(-5, 5).status == "current" and mk(-5, 0).status == "current" and mk(0, 5).status == "current"
    assert mk(1, 9).status == "upcoming" and mk(-9, -1).status == "archived"
    assert Category(kind="semester", name="x").status == "" and Category(kind="department", name="d").status == ""


def test_semester_span_text():
    c = Category(kind="semester", name="x", start_date=date(2026, 8, 1), end_date=date(2026, 12, 20))
    assert c.span == "Aug – Dec 2026"
    c.end_date = date(2027, 2, 1)
    assert c.span == "Aug 2026 – Feb 2027"


def test_page_lists_semesters_newest_first_with_pills(admin_client):
    t = timezone.localdate()
    Category.objects.create(name="Old term", kind="semester", start_date=t - timedelta(days=400), end_date=t - timedelta(days=300))
    Category.objects.create(name="Now term", kind="semester", start_date=t - timedelta(days=10), end_date=t + timedelta(days=60))
    Category.objects.create(name="Next term", kind="semester", start_date=t + timedelta(days=100), end_date=t + timedelta(days=200))
    Category.objects.create(name="Undated", kind="semester")
    html = admin_client.get(reverse(LIST)).content.decode()
    order = [html.index(n) for n in ("Next term", "Now term", "Old term", "Undated")]
    assert order == sorted(order)
    assert ">Current<" in html and ">Upcoming<" in html and ">Archived<" in html and ">No dates<" in html


def test_edit_keeps_kind_and_saves(admin_client):
    c = Category.objects.create(name="Mathmatics", kind="department")
    fac = Category.objects.create(name="Science", kind="faculty")
    url = reverse("courses:admin-category-edit", args=[c.pk])
    assert admin_client.get(url).status_code == 200
    r = admin_client.post(url, {"name": "Mathematics", "kind": "semester", "faculty": fac.pk})
    assert r.status_code == 302
    c.refresh_from_db()
    assert (c.name, c.kind, c.faculty) == ("Mathematics", "department", fac)


def test_edit_may_keep_its_own_name(admin_client):
    c = Category.objects.create(name="Law", kind="faculty")
    r = admin_client.post(reverse("courses:admin-category-edit", args=[c.pk]), {"name": "Law"})
    assert r.status_code == 302


def test_edit_semester_dates(admin_client):
    c = Category.objects.create(name="S", kind="semester")
    url = reverse("courses:admin-category-edit", args=[c.pk])
    assert b'type="date"' in admin_client.get(url).content
    admin_client.post(url, {"name": "S", "start_date": "2026-08-01", "end_date": "2026-12-20"})
    c.refresh_from_db()
    assert c.start_date == date(2026, 8, 1) and c.end_date == date(2026, 12, 20)


def test_delete_leaves_courses_in_place(admin_client, course):
    dept = course.department
    r = admin_client.post(reverse("courses:admin-category-delete", args=[dept.pk]))
    assert r.status_code == 302 and not Category.objects.filter(pk=dept.pk).exists()
    course.refresh_from_db()
    assert course.department is None and Course.objects.filter(pk=course.pk).exists()


def test_delete_faculty_keeps_its_departments(admin_client):
    fac = Category.objects.create(name="Arts", kind="faculty")
    dept = Category.objects.create(name="History", kind="department", faculty=fac)
    admin_client.post(reverse("courses:admin-category-delete", args=[fac.pk]))
    dept.refresh_from_db()
    assert dept.faculty is None


def test_delete_needs_post(admin_client):
    c = Category.objects.create(name="Law", kind="faculty")
    assert admin_client.get(reverse("courses:admin-category-delete", args=[c.pk])).status_code == 405
    assert Category.objects.filter(pk=c.pk).exists()


def test_changes_are_audited(admin_client):
    add(admin_client, name="Computing", kind="faculty")
    c = Category.objects.get(name="Computing")
    admin_client.post(reverse("courses:admin-category-edit", args=[c.pk]), {"name": "Computing & IT"})
    admin_client.post(reverse("courses:admin-category-delete", args=[c.pk]))
    assert list(AuditLog.objects.filter(action__startswith="category_").order_by("id").values_list("action", flat=True)) == [
        "category_created", "category_updated", "category_deleted"]
    html = admin_client.get(reverse("administration:audit") + "?category=courses").content.decode()
    assert "Added faculty Computing" in html and "Deleted faculty Computing &amp; IT" in html


@pytest.mark.parametrize("name", ["admin-categories"])
def test_only_admins(client, student, lecturer, name):
    for u in (student, lecturer):
        client.force_login(u)
        assert client.get(reverse(f"courses:{name}")).status_code == 403
        assert client.post(reverse(f"courses:{name}"), {"name": "X", "kind": "faculty"}).status_code == 403
    assert not Category.objects.filter(name="X").exists()


def test_edit_and_delete_only_admins(client, lecturer):
    c = Category.objects.create(name="Law", kind="faculty")
    client.force_login(lecturer)
    assert client.get(reverse("courses:admin-category-edit", args=[c.pk])).status_code == 403
    assert client.post(reverse("courses:admin-category-delete", args=[c.pk])).status_code == 403
    assert Category.objects.filter(pk=c.pk).exists()
