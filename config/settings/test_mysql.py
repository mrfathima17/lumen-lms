"""Run the whole test suite against a real MySQL or MariaDB server:

    DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=lumen DB_PASSWORD=... pytest --ds=config.settings.test_mysql

The user needs permission to create and drop databases (pytest makes a throwaway test_<name> database)."""
from .test import *  # noqa: F401,F403
from .base import env

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("DB_NAME", "lumen"),
        "USER": env("DB_USER", "lumen"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"},
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"},
    }
}
