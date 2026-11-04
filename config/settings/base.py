"""Shared settings. Environment-specific files (dev, prod, test) import from here."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-development-key-change-me")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "apps.core",
    "apps.accounts",
    "apps.courses",
    "apps.content",
    "apps.assignments",
    "apps.quizzes",
    "apps.grading",
    "apps.attendance",
    "apps.schedule",
    "apps.messaging",
    "apps.files",
    "apps.completion",
    "apps.surveys",
    "apps.administration",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Lumen request pipeline (order matters): maintenance -> network rules -> forced password change
    "apps.core.middleware.MaintenanceMiddleware",
    "apps.core.middleware.NetworkRulesMiddleware",
    "apps.core.middleware.ModuleMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "apps.accounts.middleware.TwoFactorRequiredMiddleware",
    "apps.accounts.middleware.PreviewMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
                "apps.messaging.context_processors.badges",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("DB_NAME", "lumen"),
        "USER": env("DB_USER", "lumen"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"},
        "CONN_MAX_AGE": 60,
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "apps.core.validators.SitePasswordPolicyValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
PASSWORD_RESET_TIMEOUT = 60 * 30  # reset links work for 30 minutes
LOGIN_REDIRECT_URL = "accounts:home"
LOGOUT_REDIRECT_URL = "core:public-home"

# Brute-force protection (django-axes): lock a username+IP pair after 5 failures for 15 minutes.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25  # hours
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "errors/locked.html"

LANGUAGE_CODE = "en"
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Colombo")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Only trust X-Forwarded-For when running behind our own nginx.
TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", False)

# Uploads: validated on the way in, served only after Django checks permission.
MAX_UPLOAD_MB = 20
ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "csv", "zip", "png", "jpg", "jpeg", "mp4", "py", "java", "sql", "md"}
USE_ACCEL_REDIRECT = env_bool("USE_ACCEL_REDIRECT", False)  # True behind nginx: it streams the file after Django approves
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 8
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_TIMEOUT = 20
# Used for links inside emails (notifications are sent from a background worker, which has no request to build a URL from).
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Lumen <no-reply@lumen.local>")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# Where app-level backups are written. Keep this OUTSIDE MEDIA_ROOT and never serve it from nginx.
BACKUP_DIR = Path(env("BACKUP_DIR", str(BASE_DIR / "backups")))

# Two-factor: a wrong code makes the next attempt wait 1, 2, 4... seconds, on top of the 5-try limit in the sign-in flow.
OTP_TOTP_THROTTLE_FACTOR = 1
OTP_STATIC_THROTTLE_FACTOR = 1


# ---------- background jobs (Celery + Redis) ----------
from celery.schedules import crontab  # noqa: E402

CELERY_BROKER_URL = env("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_EAGER", False)  # True runs jobs inside the request: for development without Redis
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_connect_timeout": 2, "socket_timeout": 2}
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "close-expired-quiz-attempts": {"task": "apps.quizzes.tasks.close_expired_attempts", "schedule": 60.0},
    # Checks every 5 minutes whether the daily backup chosen in Backup & maintenance is due (time, on/off and days kept are settings).
    "scheduled-backup": {"task": "apps.administration.tasks.scheduled_backup", "schedule": crontab(minute="*/5")},
    "purge-audit-log": {"task": "apps.administration.tasks.purge_audit_log", "schedule": crontab(hour=3, minute=10)},
    "issue-certificates": {"task": "apps.completion.tasks.issue_certificates", "schedule": crontab(hour=4, minute=0)},
}
EMAIL_FILE_PATH = env("EMAIL_FILE_PATH", "/tmp/mails")  # only used by the file-based email backend (handy for testing)
