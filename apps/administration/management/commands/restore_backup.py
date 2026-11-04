from django.core.management.base import BaseCommand, CommandError

from apps.administration import backups


class Command(BaseCommand):
    help = "Replace ALL data and uploaded files with a backup from BACKUP_DIR. A safety backup of the current state is made first."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Backup file name, e.g. lumen-backup-20261020-020000.zip")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")

    def handle(self, *args, **opts):
        if not opts["yes"] and input("This replaces ALL current data. Type RESTORE to continue: ").strip() != "RESTORE":
            raise CommandError("Cancelled.")
        try:
            safety = backups.restore_backup(opts["name"])
        except backups.RestoreError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Restored {opts['name']}. The previous state was saved as {safety}.")
