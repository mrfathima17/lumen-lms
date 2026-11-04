from django.db import models


class EmailTemplate(models.Model):
    """Editable text of the emails Lumen sends. Placeholders in {braces} are filled in when sending."""

    class Key(models.TextChoices):
        WELCOME = "welcome", "Welcome (new account)"
        PASSWORD_RESET = "password_reset", "Password reset by an administrator"

    key = models.CharField(max_length=30, choices=Key.choices, unique=True)
    subject = models.CharField(max_length=150)
    body = models.TextField(max_length=5000)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.get_key_display()


PLACEHOLDERS = ["name", "username", "password", "site", "login_url"]
DEFAULTS = {
    "welcome": ("Your {site} account",
                "Hello {name},\n\nAn account has been created for you on {site}.\n\nUsername: {username}\nSample password: {password}\n\n"
                "Sign in at {login_url}. You will be asked to choose your own password at your first sign-in.\n"),
    "password_reset": ("Your {site} password was reset",
                       "Hello {name},\n\nAn administrator reset your password on {site}.\n\nUsername: {username}\nSample password: {password}\n\n"
                       "Sign in at {login_url}. You will be asked to choose a new password at your next sign-in.\n"),
}
