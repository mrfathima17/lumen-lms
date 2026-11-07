"""What an administrator does in the browser: manage people, branding and the audit trail."""
from types import SimpleNamespace

import pytest
from playwright.sync_api import Page, expect

from apps.accounts.models import User

pytestmark = pytest.mark.django_db(transaction=True)


def create_user_through_the_form(page, url, username="s2026-0999"):
    page.goto(url("administration:user-new"))
    page.get_by_label("Username").fill(username)
    page.get_by_label("First name").fill("Kavya")
    page.get_by_label("Last name").fill("Silva")
    page.get_by_role("button", name="Create user").click()


def test_admin_creates_a_user_who_must_change_the_sample_password(page: Page, sign_in, switch_to, url, admin_user):
    sign_in(admin_user)
    create_user_through_the_form(page, url)

    expect(page.get_by_text("User created.")).to_be_visible()
    sample_password = page.locator("code").first.inner_text()  # shown once, so read it from the page
    assert User.objects.filter(username="s2026-0999", role="student").exists()

    switch_to(SimpleNamespace(username="s2026-0999"), password=sample_password)
    expect(page.get_by_role("heading", name="Set your new password")).to_be_visible()  # first sign-in forces a new password


def test_admin_disables_an_account_and_that_user_can_no_longer_sign_in(page: Page, sign_in, switch_to, url, admin_user, student):
    sign_in(admin_user)
    page.goto(url("administration:user-edit", student.pk))
    page.get_by_role("button", name="Disable account").click()
    expect(page.get_by_text("Account disabled.")).to_be_visible()

    switch_to(student)
    expect(page).to_have_url(url("accounts:login"))
    expect(page.get_by_role("alert")).to_be_visible()


def test_admin_renames_the_site_and_the_sign_in_page_shows_it(page: Page, sign_in, url, admin_user):
    sign_in(admin_user)
    page.goto(url("administration:theme"))
    page.get_by_label("Site name").fill("Campus Learning")
    page.get_by_role("button", name="Save theme").click()

    page.context.clear_cookies()  # a signed-out visitor
    page.goto(url("accounts:login"))
    expect(page.get_by_text("Campus Learning").first).to_be_visible()


def test_audit_log_records_who_was_created(page: Page, sign_in, url, admin_user):
    sign_in(admin_user)
    create_user_through_the_form(page, url, username="s2026-0555")
    page.goto(url("administration:audit"))
    expect(page.get_by_text("Created user s2026-0555")).to_be_visible()
