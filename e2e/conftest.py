"""Shared setup for the browser (end-to-end) tests.

These tests drive a real Chromium browser with Playwright against a temporary copy of the app
(pytest-django's `live_server`). They reuse the user, course and enrolment fixtures from `tests/conftest.py`.
"""
import os

# Playwright runs an event loop in the same process as the test; without this, Django refuses
# database calls made from the test body ("You cannot call this from an async context").
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import pytest  # noqa: E402
from django.urls import reverse  # noqa: E402

from tests.conftest import course, enrolled, lecturer, make_user, student, tmp_media  # noqa: E402,F401

PASSWORD = "Pass-12345-xyz"  # the default password make_user() gives every test user


def pytest_configure(config):
    # The shared browser keeps its connection to the test server open until the very end, so Django logs a harmless
    # "DatabaseWrapper ... thread" error while shutting down. It does not affect any result; hide the noise.
    config.addinivalue_line("filterwarnings", "ignore::pytest.PytestUnhandledThreadExceptionWarning")


# --- One shared browser page, so all tests are recorded into a single video ---------------------

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "record_video_dir": "videos/",
        "record_video_size": {"width": 1280, "height": 720},
    }


@pytest.fixture(scope="session")
def context(browser, browser_context_args):
    ctx = browser.new_context(**browser_context_args)
    yield ctx
    ctx.close()  # the single video file is written when the context closes


@pytest.fixture(scope="session")
def page(context):
    p = context.new_page()
    yield p


@pytest.fixture(autouse=True)
def _fresh_session(context, page):
    """Because the page is shared, start every test signed out on a blank page."""
    context.clear_cookies()
    page.goto("about:blank")
    yield


# --- Helpers -------------------------------------------------------------------------------------

@pytest.fixture
def url(live_server):
    """Build a full address from a URL name, e.g. url("courses:settings", course.pk)."""
    def _url(name, *args):
        return live_server.url + reverse(name, args=args)
    return _url


@pytest.fixture
def sign_in(page, url):
    """Sign in through the real login form, the way a user would."""
    def _sign_in(user, password=PASSWORD):
        page.goto(url("accounts:login"))
        page.locator("input[name=username]").fill(user.username)
        page.locator("input[name=password]").fill(password)
        page.get_by_role("button", name="Sign in").click()
    return _sign_in