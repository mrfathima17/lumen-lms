import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.django_db(transaction=True)


def test_lecturer_renames_their_course(page: Page, sign_in, url, course, lecturer):
    sign_in(lecturer)
    page.goto(url("courses:settings", course.pk))

    title = page.locator("input[name=title]")
    expect(title).to_have_value("Database Systems")
    title.fill("Databases II")
    page.get_by_role("button", name="Save settings").click()

    # the change is saved and shown on the page after the redirect
    expect(page.locator("input[name=title]")).to_have_value("Databases II")
    course.refresh_from_db()
    assert course.title == "Databases II"
    assert course.code == "CS201"  # the code is not editable by a lecturer


def test_course_code_cannot_be_changed_by_a_lecturer(page: Page, sign_in, url, course, lecturer):
    sign_in(lecturer)
    page.goto(url("courses:settings", course.pk))
    assert page.locator("input[name=code]").count() == 0  # the form offers no code field
