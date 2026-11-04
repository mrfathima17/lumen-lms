from .services import unread_messages, unread_notifications


def badges(request):
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return {}
    return {"unread_messages": unread_messages(u), "unread_notifications": unread_notifications(u)}
