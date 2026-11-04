"""Development settings using SQLite, for working without a MySQL server."""
from .dev import *  # noqa: F401,F403
from .base import BASE_DIR

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

from .base import env_bool  # noqa: E402

CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_EAGER", True)  # True: no Redis needed locally, jobs run immediately
