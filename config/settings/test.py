"""Test settings: SQLite so the suite runs anywhere without a MySQL server."""
from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-key"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
ALLOWED_HOSTS = ["testserver", "localhost"]
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]

OTP_TOTP_THROTTLE_FACTOR = 0
OTP_STATIC_THROTTLE_FACTOR = 0

CELERY_TASK_ALWAYS_EAGER = True  # no Redis needed here: jobs run immediately
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
