from celery import shared_task
from django.utils import timezone


@shared_task
def close_expired_attempts():
    """Every minute: submit attempts whose time ran out, and record that the scheduler is alive."""
    from apps.core.models import JobHeartbeat

    from .services import expire_overdue

    JobHeartbeat.objects.update_or_create(name="scheduler", defaults={"last_run": timezone.now()})
    return expire_overdue()
