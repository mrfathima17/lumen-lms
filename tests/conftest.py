import pytest

from apps.accounts.models import User


@pytest.fixture
def make_user(db):
    def _make(username, role="student", password="Pass-12345-xyz", **kw):
        return User.objects.create_user(username=username, password=password, role=role, **kw)

    return _make


@pytest.fixture
def student(make_user):
    return make_user("s2026-0142", "student", first_name="Amal", last_name="Karunaratne")


@pytest.fixture
def lecturer(make_user):
    return make_user("nperera", "lecturer", first_name="Nimal", last_name="Perera")


@pytest.fixture
def admin_user(make_user):
    return make_user("admin1", "admin")


@pytest.fixture
def course(db, lecturer):
    from apps.courses.models import Category, Course

    dept = Category.objects.create(name="Computer Science", kind="department")
    sem = Category.objects.create(name="Semester 3", kind="semester")
    c = Course.objects.create(code="CS201", title="Database Systems", department=dept, semester=sem, credits=4)
    c.lecturers.add(lecturer)
    return c


@pytest.fixture
def enrolled(course, student):
    from apps.courses.models import Enrolment

    Enrolment.objects.create(course=course, user=student)
    return student


@pytest.fixture(autouse=True)
def tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
