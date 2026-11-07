import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.django_db(transaction=True)


def test_student_cannot_open_course_settings(page: Page, sign_in, url, course, enrolled):
    sign_in(enrolled)
    response = page.goto(url("courses:settings", course.pk))
    assert response.status == 403
    expect(page.get_by_role("heading", name="Access denied")).to_be_visible()


def test_student_cannot_open_course_reports(page: Page, sign_in, url, course, enrolled):
    sign_in(enrolled)
    response = page.goto(url("courses:reports", course.pk))
    assert response.status == 403


@pytest.mark.parametrize("page_name", ["administration:users", "administration:audit", "administration:theme", "administration:settings"])
@pytest.mark.parametrize("who", ["student", "lecturer"])
def test_only_administrators_can_open_the_admin_panel(page: Page, sign_in, url, request, who, page_name, course, enrolled):
    sign_in(request.getfixturevalue(who))
    response = page.goto(url(page_name))
    assert response.status == 403


@pytest.mark.parametrize("page_name", ["quizzes:manage-list", "grading:gradebook-list", "attendance:course-list"])
def test_student_cannot_open_lecturer_tools(page: Page, sign_in, url, page_name, enrolled):
    sign_in(enrolled)
    response = page.goto(url(page_name))
    assert response.status == 403
