from celery import shared_task


@shared_task(autoretry_for=(OSError,), retry_backoff=60, retry_backoff_max=900, max_retries=4)
def email_notifications(user_ids, text, url=""):
    """Email a notification to people who have an address and have not switched emails off. Sent from the worker, not the page."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core import mail

    from apps.core.models import SiteSettings

    site = SiteSettings.load().site_name
    link = f"{settings.SITE_URL}{url}" if url.startswith("/") else settings.SITE_URL
    users = get_user_model().objects.filter(pk__in=user_ids, is_active=True, email_notifications=True).exclude(email="")
    messages = []
    for u in users:
        body = (f"Hello {u.get_full_name() or u.username},\n\n{text}\n\nOpen it here: {link}\n\n"
                f"You get this email because email notifications are on for your {site} account. "
                f"Turn them off in Profile & settings: {settings.SITE_URL}/profile/\n")
        messages.append(mail.EmailMessage(subject=f"[{site}] {text}"[:150], body=body, to=[u.email]))
    if messages:
        with mail.get_connection() as conn:
            conn.send_messages(messages)
    return len(messages)
