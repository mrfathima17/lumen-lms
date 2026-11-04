from celery import shared_task


@shared_task
def issue_certificates():
    from .services import issue_due

    return issue_due()
