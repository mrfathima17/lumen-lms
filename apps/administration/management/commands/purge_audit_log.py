from django.core.management.base import BaseCommand

from apps.administration.services import purge_audit_log


class Command(BaseCommand):
    help = "Delete audit log entries older than the retention period in the site settings (default 12 months). Also runs daily from Celery beat."

    def handle(self, *args, **options):
        n, months = purge_audit_log()
        self.stdout.write(f"Deleted {n} audit log entries older than {months} months.")
