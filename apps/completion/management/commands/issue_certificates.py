from django.core.management.base import BaseCommand

from apps.completion import services


class Command(BaseCommand):
    help = "Issue certificates to every student who has met a course's completion rules (courses with automatic certificates on). Also runs daily from Celery beat."

    def handle(self, *args, **opts):
        self.stdout.write(f"Issued {services.issue_due()} certificate(s).")
