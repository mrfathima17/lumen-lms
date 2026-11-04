"""List and end signed-in sessions. Django stores sessions in the database, so this works on any host."""
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.utils import timezone

User = get_user_model()


def active_sessions():
    """Every unexpired session that belongs to a signed-in user, newest expiry first."""
    rows = []
    for s in Session.objects.filter(expire_date__gt=timezone.now()).order_by("-expire_date"):
        try:
            uid = SessionStore(session_key=s.session_key).load().get(SESSION_KEY)
        except Exception:  # pragma: no cover - a corrupt session is simply ignored
            continue
        if uid:
            rows.append({"key": s.session_key, "user_id": int(uid), "expires": s.expire_date})
    users = User.objects.in_bulk([r["user_id"] for r in rows])
    return [dict(r, user=users[r["user_id"]]) for r in rows if r["user_id"] in users]


def end_session(key):
    return Session.objects.filter(session_key=key).delete()[0] > 0


def end_user_sessions(user, keep_key=None):
    """Sign a user out everywhere (optionally sparing one session). Returns how many were ended."""
    n = 0
    for r in active_sessions():
        if r["user_id"] == user.pk and r["key"] != keep_key:
            n += end_session(r["key"])
    return n
