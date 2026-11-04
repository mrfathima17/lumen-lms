import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import ProfileField, ProfileValue
from apps.core.models import AuditLog


def as_user(u):
    c = Client()
    c.force_login(u)
    return c


def test_profile_requires_sign_in(db):
    assert Client().get(reverse("accounts:profile")).status_code == 302


@pytest.mark.parametrize("who", ["student", "lecturer", "admin_user"])
def test_every_role_opens_own_profile(request, who):
    u = request.getfixturevalue(who)
    r = as_user(u).get(reverse("accounts:profile"))
    assert r.status_code == 200 and u.username.encode() in r.content


def test_edit_own_details_only_allowed_fields(student):
    c = as_user(student)
    r = c.post(reverse("accounts:profile"), {"first_name": "Amali", "last_name": "K", "email": "a@x.lk",
                                           "role": "admin", "username": "hacker", "index_number": "999", "faculty": "Law", "is_staff": "on"})
    assert r.status_code == 302
    student.refresh_from_db()
    assert (student.first_name, student.email) == ("Amali", "a@x.lk")
    assert student.role == "student" and student.username == "s2026-0142" and not student.is_staff and student.faculty == ""
    assert AuditLog.objects.filter(action="profile_updated").exists()


def test_profile_validation(student):
    c = as_user(student)
    assert c.post(reverse("accounts:profile"), {"first_name": "", "last_name": "K", "email": "x@y.lk"}).status_code == 200
    assert c.post(reverse("accounts:profile"), {"first_name": "A", "last_name": "K", "email": "not-an-email"}).status_code == 200


def test_custom_values_shown_read_only(student):
    f = ProfileField.objects.create(label="Hostel", key="hostel")
    ProfileValue.objects.create(user=student, field=f, value="Block A")
    assert b"Block A" in as_user(student).get(reverse("accounts:profile")).content


def test_sign_out_other_devices(student):
    a, b = as_user(student), as_user(student)
    r = a.post(reverse("accounts:sign-out-others"))
    assert r.status_code == 302
    assert a.get(reverse("accounts:student-dashboard")).status_code == 200
    assert b.get(reverse("accounts:student-dashboard")).status_code == 302
    assert a.get(reverse("accounts:sign-out-others")).status_code == 405


# ---------- viewing other people ----------

def test_student_sees_own_lecturer_with_email(enrolled, lecturer):
    lecturer.email = "nimal@uni.lk"
    lecturer.save()
    r = as_user(enrolled).get(reverse("accounts:person", args=[lecturer.pk]))
    assert r.status_code == 200 and b"nimal@uni.lk" in r.content and b"CS201" in r.content and b"Send message" in r.content


def test_lecturer_sees_enrolled_student(enrolled, lecturer):
    enrolled.email = "amal@uni.lk"
    enrolled.save()
    assert b"amal@uni.lk" in as_user(lecturer).get(reverse("accounts:person", args=[enrolled.pk])).content


def test_students_do_not_see_each_others_email_or_index(enrolled, course, make_user):
    from apps.courses.models import Enrolment

    peer = make_user("s2026-0200", "student", email="peer@uni.lk", index_number="2026-0200")
    Enrolment.objects.create(course=course, user=peer)
    html = as_user(enrolled).get(reverse("accounts:person", args=[peer.pk])).content
    assert b"peer@uni.lk" not in html and b"2026-0200" not in html.replace(b"s2026-0200", b"")


def test_strangers_get_404(student, lecturer, make_user, course):
    # student not enrolled, so shares nothing with the lecturer
    assert as_user(student).get(reverse("accounts:person", args=[lecturer.pk])).status_code == 404
    other = make_user("other", "lecturer")
    assert as_user(other).get(reverse("accounts:person", args=[lecturer.pk])).status_code == 404


def test_nobody_but_admin_sees_admins_or_disabled(enrolled, lecturer, admin_user, admin_client=None):
    assert as_user(enrolled).get(reverse("accounts:person", args=[admin_user.pk])).status_code == 404
    enrolled.is_active = False
    enrolled.save()
    assert as_user(lecturer).get(reverse("accounts:person", args=[enrolled.pk])).status_code == 404
    assert as_user(admin_user).get(reverse("accounts:person", args=[enrolled.pk])).status_code == 200


def test_course_pages_link_to_people(enrolled, course, lecturer):
    html = as_user(enrolled).get(reverse("courses:detail", args=[course.pk])).content
    assert reverse("accounts:person", args=[lecturer.pk]).encode() in html
    html = as_user(lecturer).get(reverse("courses:participants", args=[course.pk])).content
    assert reverse("accounts:person", args=[enrolled.pk]).encode() in html


def test_sidebar_links_for_all_roles(student, lecturer, admin_user):
    for u in (student, lecturer, admin_user):
        assert reverse("accounts:profile").encode() in as_user(u).get(reverse(u.home_url_name)).content


def test_edit_phone_bio_birth_date_and_emergency_contact(student):
    c = as_user(student)
    r = c.post(reverse("accounts:profile"), {"first_name": "A", "last_name": "K", "email": "", "phone": "+94 77 123 4567", "bio": "Hi",
                                           "date_of_birth": "2005-03-14", "emergency_contact": "+94 71 765 4321", "batch": "Hacked"})
    assert r.status_code == 302
    student.refresh_from_db()
    assert student.phone == "+94 77 123 4567" and str(student.date_of_birth) == "2005-03-14" and student.emergency_contact.startswith("+94 71")
    assert student.batch == ""  # set by administrators only
    assert b"2005-03-14" in c.get(reverse("accounts:profile")).content
