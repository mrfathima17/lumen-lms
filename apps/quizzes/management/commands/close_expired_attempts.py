from django.core.management.base import BaseCommand

from apps.quizzes.services import expire_overdue


class Command(BaseCommand):
    help = "Submit and mark every quiz attempt whose time has run out. Run every minute (cron now, Celery beat later)."

    def handle(self, *args, **opts):
        self.stdout.write(f"Closed {expire_overdue()} attempt(s).")
