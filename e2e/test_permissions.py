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
