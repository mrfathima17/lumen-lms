from celery import shared_task


@shared_task
def purge_audit_log():
    from .services import purge_audit_log as run

    return run()[0]


@shared_task
def make_backup(keep=14):
    from . import backups

    name = backups.create_backup()
    backups.prune(keep)
    return name


@shared_task
def scheduled_backup():
    """Runs every few minutes; makes the daily backup when the time chosen in Backup & maintenance has passed."""
    from . import backups

    return backups.run_scheduled()
