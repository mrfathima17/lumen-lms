"""Who may see whose profile. People see each other only through shared courses; administrators see everyone."""
from django.contrib.auth import get_user_model

from apps.courses import permissions as perm
from apps.courses.models import Course, Enrolment

User = get_user_model()


def courses_of(user):
    """Courses a person is active in (teaches or is enrolled in)."""
    if user.role == "lecturer":
        return Course.objects.filter(lecturers=user)
    if user.role == "student":
        return Course.objects.filter(enrolments__user=user, enrolments__status=Enrolment.Status.ACTIVE)
    return Course.objects.none()


def shared_courses(viewer, target):
    if viewer.role == "admin":
        return courses_of(target)
    return courses_of(target).filter(pk__in=perm.visible_courses_for(viewer).values_list("pk", flat=True)).distinct()


def can_view_person(viewer, target):
    if not viewer.is_authenticated:
        return False
    if viewer.pk == target.pk or viewer.role == "admin":
        return True
    if not target.is_active or target.role == "admin":
        return False
    return shared_courses(viewer, target).exists()


def can_see_email(viewer, target):
    """Students do not see each other's email; everyone else involved does."""
    return viewer.pk == target.pk or viewer.role in ("admin", "lecturer") or target.role == "lecturer"
