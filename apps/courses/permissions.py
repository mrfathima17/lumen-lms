"""Object-level permission checks (check 7 of the request pipeline). Views call these; they never inline the logic."""
from django.db.models import Q

from .models import Course, Enrolment


def teaches(user, course):
    return user.is_authenticated and user.role == "lecturer" and course.lecturers.filter(pk=user.pk).exists()


def can_manage(user, course):
    """Admins manage every course; lecturers manage only the courses they teach."""
    return user.is_authenticated and (user.role == "admin" or teaches(user, course))


def is_enrolled(user, course):
    return user.is_authenticated and Enrolment.objects.filter(course=course, user=user, status=Enrolment.Status.ACTIVE).exists()


def can_view(user, course):
    if can_manage(user, course):
        return True
    if course.is_visible and user.role == "student" and getattr(user, "preview_course_id", None) == course.pk:
        return True  # a lecturer previewing this course as a student (see PreviewMiddleware)
    return course.is_visible and user.role == "student" and is_enrolled(user, course)


def visible_courses_for(user):
    """Courses that appear in 'My courses' for this user."""
    if user.role == "admin":
        return Course.objects.all()
    if user.role == "lecturer":
        return Course.objects.filter(lecturers=user)
    preview = getattr(user, "preview_course_id", None)
    if preview:
        return Course.objects.filter(is_visible=True, pk=preview)
    return Course.objects.filter(is_visible=True, enrolments__user=user, enrolments__status=Enrolment.Status.ACTIVE)
