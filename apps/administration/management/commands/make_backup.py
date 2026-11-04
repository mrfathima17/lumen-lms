from django.core.management.base import BaseCommand

from apps.administration import backups


class Command(BaseCommand):
    help = "Create a backup (database as JSON plus uploaded files) in BACKUP_DIR. Run nightly from cron."

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=14, help="Keep this many newest backups (default 14).")

    def handle(self, *args, **opts):
        name = backups.create_backup()
        removed = backups.prune(opts["keep"])
        self.stdout.write(f"Created {name}; removed {removed} old backup(s).")
