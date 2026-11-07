import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.django_db(transaction=True)


def test_student_signs_in_and_lands_on_their_dashboard(page: Page, sign_in, student):
    sign_in(student)
    expect(page).to_have_url(re.compile(r"/student/$"))
    expect(page.get_by_role("heading", level=1)).to_contain_text("Amal")  # greets the signed-in student by name


def test_wrong_password_is_refused_with_an_error(page: Page, sign_in, url, student):
    sign_in(student, password="not-the-password")
    expect(page).to_have_url(url("accounts:login"))  # still on the sign-in page
    expect(page.get_by_role("alert")).to_be_visible()


def test_signed_out_visitor_is_sent_to_sign_in(page: Page, url, course):
    page.goto(url("courses:settings", course.pk))
    expect(page).to_have_url(re.compile(r"/sign-in/"))


def test_user_can_sign_out(page: Page, sign_in, url, student):
    sign_in(student)
    page.get_by_role("button", name="Sign out").click()
    expect(page).to_have_url(re.compile(r"/sign-in/|/$"))
    page.goto(url("courses:my-courses"))  # a protected page now bounces to sign-in
    expect(page).to_have_url(re.compile(r"/sign-in/"))
