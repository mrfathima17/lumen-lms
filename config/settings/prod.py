from .base import *  # noqa: F401,F403
from .base import env, env_bool

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")  # required in production
if not SECRET_KEY or SECRET_KEY.startswith("insecure"):
    raise RuntimeError("Set DJANGO_SECRET_KEY to a long random value in production.")

TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]  # Docker and monitors call it over plain HTTP
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = False

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

USE_ACCEL_REDIRECT = env_bool("USE_ACCEL_REDIRECT", True)
