"""Password rules that the administrator sets on the System settings page."""
from django.core.exceptions import ValidationError


class SitePasswordPolicyValidator:
    def validate(self, password, user=None):
        from apps.core.models import SiteSettings

        try:
            cfg = SiteSettings.load()
        except Exception:  # database not ready (first migrate): fall back to the defaults
            cfg = SiteSettings()
        problems = []
        if len(password) < cfg.password_min_length:
            problems.append(f"be at least {cfg.password_min_length} characters long")
        if cfg.password_require_upper and not any(c.isupper() for c in password):
            problems.append("contain an uppercase letter")
        if cfg.password_require_number and not any(c.isdigit() for c in password):
            problems.append("contain a number")
        if cfg.password_require_symbol and not any(not c.isalnum() and not c.isspace() for c in password):
            problems.append("contain a symbol")
        if problems:
            raise ValidationError("The password must " + ", ".join(problems[:-1]) + (" and " if len(problems) > 1 else "") + problems[-1] + ".", code="site_policy")

    def get_help_text(self):
        from apps.core.models import SiteSettings

        try:
            n = SiteSettings.load().password_min_length
        except Exception:
            n = 10
        return f"Your password must be at least {n} characters and follow the site's password rules."
