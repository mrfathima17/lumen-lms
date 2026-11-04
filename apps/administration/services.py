"""User administration rules: creating accounts with a sample password, resetting it, and the guards that keep an administrator from locking everyone out."""
import csv
import io
import secrets
import string

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q

from apps.core.models import SiteSettings
from apps.courses.models import Course, Enrolment

User = get_user_model()

ROLES = {v.lower(): k for k, v in User.Role.choices} | {k: k for k, _ in User.Role.choices}  # "Administrator" and "admin" both accepted
MAX_ROWS = 1000
MAX_CSV_BYTES = 1024 * 1024
COLUMNS = ["username", "first_name", "last_name", "email", "role", "index_number", "faculty", "courses"]
HEADER_ALIASES = {"course_codes": "courses", "course_code": "courses", "course": "courses"}  # other spellings of the courses column


def generate_password(length=14):
    """Random sample password with at least one lower case, upper case and digit (passes the password validators)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def send_welcome(user, password, login_url, key="welcome"):
    """Send the account email (welcome, or password reset) built from the editable template. Returns True when an email was sent."""
    if not user.email:
        return False
    from .email_templates import render

    values = {"name": user.get_full_name() or user.username, "username": user.username, "password": password,
              "site": SiteSettings.load().site_name, "login_url": login_url}
    subject, body = render(key, values)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
    return True


def active_admin_count(excluding=None):
    qs = User.objects.filter(role="admin", is_active=True)
    return qs.exclude(pk=excluding.pk).count() if excluding else qs.count()


def check_can_change(actor, user, new_role=None, new_active=None):
    """Raise PermissionDenied for changes that would remove the last working administrator or lock the actor out."""
    if user.pk == actor.pk and ((new_role is not None and new_role != "admin") or new_active is False):
        raise PermissionDenied
    removes_admin = user.role == "admin" and user.is_active and ((new_role is not None and new_role != "admin") or new_active is False)
    if removes_admin and active_admin_count(excluding=user) == 0:
        raise PermissionDenied


@transaction.atomic
def create_user(data, login_url, password=None, send_email=True, force_change=True):
    """Create an account. By default: a random sample password, a welcome email (if there is an address) and a forced change at first sign-in.
    Returns (user, password, emailed) where emailed is True, False (no address) or "off" (email switched off)."""
    password = password or generate_password()
    user = User(**data)
    user.set_password(password)
    user.must_change_password = force_change
    user.save()
    emailed = send_welcome(user, password, login_url) if send_email else "off"
    return user, password, emailed


def reset_password(user, login_url):
    password = generate_password()
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    return password, send_welcome(user, password, login_url, key="password_reset")


def search_users(q="", role="", status=""):
    qs = User.objects.all().order_by("first_name", "last_name", "username")
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(index_number__icontains=q))
    if role in ROLES.values():
        qs = qs.filter(role=role)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "disabled":
        qs = qs.filter(is_active=False)
    return qs


# ---------- CSV import ----------

def parse_csv(raw):
    """raw: bytes or str. Returns (rows, error). Each row is a dict of the known columns; unknown columns are ignored."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_CSV_BYTES:
            return [], "The file is larger than 1 MB."
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return [], "The file is not UTF-8 text. Save it as CSV (UTF-8) and try again."
    elif len(raw.encode()) > MAX_CSV_BYTES:
        return [], "The file is larger than 1 MB."
    raw = raw.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return [], "The file is empty."
    reader.fieldnames = [HEADER_ALIASES.get(h, h) for h in ((h or "").strip().lower() for h in reader.fieldnames)]
    if "username" not in reader.fieldnames:
        return [], "The first row must be a header containing at least: username."
    rows = []
    for i, r in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            return [], f"At most {MAX_ROWS} users can be imported at once."
        if not any((v or "").strip() for v in r.values() if isinstance(v, str)):
            continue
        rows.append({"line": i, **{c: (r.get(c) or "").strip() for c in COLUMNS}})
    if not rows:
        return [], "The file has no users."
    return rows, None


DUPLICATE_ERRORS = ("username already exists", "username appears twice in the file", "index number already used")
SHORT_LABELS = [("username is missing", "Missing username"), ("username may only", "Bad username"), ("username is too long", "Bad username"),
                ("role must be", "Bad role"), ("email is not valid", "Bad email"), ("unknown course", "Unknown course"),
                ("only students can be enrolled", "Courses need student"), ("too long", "Too long")]


def _label(errors):
    """(status, short label) shown in the preview's Result column."""
    if not errors:
        return "ok", "OK"
    if any(e in DUPLICATE_ERRORS for e in errors):
        return "duplicate", "Duplicate"
    for needle, label in SHORT_LABELS:
        if any(needle in e for e in errors):
            return "error", label
    return "error", "Problem"


def validate_rows(rows, default_role="student"):
    """Annotate each row with .errors (list), .role, .course_objs, .status ("ok", "duplicate" or "error") and .label. Nothing is written.
    A blank role cell gets `default_role`."""
    names_seen, idx_seen = set(), set()
    existing_names = {n.lower() for n in User.objects.values_list("username", flat=True)}
    existing_idx = set(User.objects.exclude(index_number__isnull=True).values_list("index_number", flat=True))
    courses = {c.code.lower(): c for c in Course.objects.all()}
    username_field = User._meta.get_field("username")
    for r in rows:
        errs = []
        u = r["username"]
        if not u:
            errs.append("username is missing")
        else:
            try:
                username_field.run_validators(u)
            except ValidationError:
                errs.append("username may only contain letters, digits and @/./+/-/_")
            if len(u) > 150:
                errs.append("username is too long")
            if u.lower() in existing_names:
                errs.append("username already exists")
            if u.lower() in names_seen:
                errs.append("username appears twice in the file")
            names_seen.add(u.lower())
        role = ROLES.get((r["role"] or default_role).lower())
        if role is None:
            errs.append("role must be student, lecturer or administrator")
        r["role"] = role or ""
        if r["email"]:
            try:
                validate_email(r["email"])
            except ValidationError:
                errs.append("email is not valid")
        if r["index_number"]:
            if r["index_number"] in existing_idx or r["index_number"] in idx_seen:
                errs.append("index number already used")
            idx_seen.add(r["index_number"])
        for f, n in (("first_name", 150), ("last_name", 150), ("faculty", 100), ("index_number", 30)):
            if len(r[f]) > n:
                errs.append(f"{f} is too long")
        objs, codes = [], [c for c in (x.strip() for x in r["courses"].split(";")) if c]
        for code in codes:
            if code.lower() not in courses:
                errs.append(f"unknown course {code}")
            else:
                objs.append(courses[code.lower()])
        if objs and r["role"] != "student":
            errs.append("only students can be enrolled by import")
        r["errors"], r["course_objs"] = errs, objs
        r["status"], r["label"] = _label(errs)
    return rows


@transaction.atomic
def import_rows(rows, login_url, password=None, send_email=True, force_change=True):
    """Create every valid row; rows with errors are skipped. `password` (optional) is given to everyone, otherwise each person gets a
    random one. Returns [(row, user, password, emailed)] for the created users."""
    out = []
    for r in rows:
        if r["errors"]:
            continue
        data = {"username": r["username"], "first_name": r["first_name"], "last_name": r["last_name"], "email": r["email"],
                "role": r["role"], "index_number": r["index_number"] or None, "faculty": r["faculty"]}
        user, pw, emailed = create_user(data, login_url, password=password, send_email=send_email, force_change=force_change)
        for c in r["course_objs"]:
            Enrolment.objects.get_or_create(course=c, user=user)
        out.append((r, user, pw, emailed))
    return out


def purge_audit_log():
    """Delete audit entries older than the retention setting. Returns (count, months)."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.models import AuditLog

    months = SiteSettings.load().audit_log_retention_months
    n, _ = AuditLog.objects.filter(created_at__lt=timezone.now() - timedelta(days=30 * months)).delete()
    return n, months
