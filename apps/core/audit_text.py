"""Turns raw audit rows (action + target + detail) into the sentence shown in the audit log, and groups actions into filter categories.

The raw action names stay in the database; only the display changes. Unknown actions fall back to a tidied version of their name,
so a new audit.record() call never shows up blank."""
import re

from django.db.models import Q
from django.utils import timezone
from django.utils.dateformat import format as date_format

ROLES = {"student": "Student", "lecturer": "Lecturer", "admin": "Administrator"}

# Setting / form field names -> words an administrator would use.
FIELD_NAMES = {
    "site_name": "site name", "brand_color": "primary colour", "brand_color2": "secondary colour", "sidebar_color": "sidebar colour",
    "font": "font", "radius": "corner roundness", "login_bg": "login background", "default_mode": "default appearance",
    "allow_dark_mode": "dark mode option", "logo_data": "logo", "login_bg_data": "login background image",
    "remove_logo": "logo removed", "remove_login_image": "login image removed",
    "late_penalty_percent_per_day": "late penalty", "quiz_review_policy": "quiz review", "attendance_warning_percent": "attendance warning",
    "private_files_quota_mb": "private files quota", "audit_log_retention_months": "audit log retention", "two_factor_policy": "two-factor policy",
    "maintenance_mode": "maintenance mode", "maintenance_message": "maintenance message", "maintenance_at": "scheduled time",
    "backup_auto": "automatic backup", "backup_time": "backup time", "backup_keep_days": "days to keep",
}


def _fields(detail):
    names = [FIELD_NAMES.get(n.strip(), n.strip().replace("_", " ")) for n in (detail or "").split(",") if n.strip()]
    return ", ".join(dict.fromkeys(names))  # no repeats, order kept


def _in(course, text=""):
    return f" ({course})" if course else text


def _user_updated(a):
    m = re.match(r"role (\w+) → (\w+)", a.detail or "")
    return f"Changed role: {a.target} → {ROLES.get(m.group(2), m.group(2).title())}" if m else f"Edited user {a.target}"


def _user_created(a):
    m = re.match(r"role (\w+)", a.detail or "")
    return f"Created user {a.target}" + (f" ({ROLES.get(m.group(1), m.group(1))})" if m else "")


def _sign_in(a):
    return "Signed in" + (f" ({a.detail})" if a.detail else "")


def _with(label, a, extra_in_target=True):
    """'<label> <detail> (<target>)' - the common shape for course-related events."""
    t = f"{label} {a.detail}".strip() if a.detail else label
    return t + (_in(a.target) if extra_in_target else "")


# action -> function(row) giving the sentence
EVENTS = {
    "sign_in": _sign_in,
    "sign_out": lambda a: "Signed out",
    "sign_out_others": lambda a: "Signed out of other sessions" + (f" ({a.detail})" if a.detail else ""),
    "login_failed": lambda a: f"Failed login ({a.detail or 'wrong password'})",
    "audit_exported": lambda a: "Exported the audit log",
    "ip_blocked": lambda a: f"Tried to open {a.target}",
    "two_factor_failed": lambda a: "Wrong two-factor code",
    "two_factor_enabled": lambda a: "Turned on two-factor sign-in",
    "two_factor_disabled": lambda a: "Turned off two-factor sign-in",
    "two_factor_reset": lambda a: f"Reset two-factor sign-in for {a.target}",
    "two_factor_codes_renewed": lambda a: "Made new two-factor backup codes",
    "preview_started": lambda a: f"Started previewing {a.target} as a student",
    "preview_ended": lambda a: f"Stopped previewing {a.target}",
    "password_change": lambda a: "Changed own password",
    "password_reset": lambda a: f"Reset password for {a.target}",
    "password_reset_requested": lambda a: f"Asked for a password reset link ({a.target})",
    "password_reset_done": lambda a: "Chose a new password from a reset link",
    "session_ended": lambda a: "Ended a session",
    "sessions_ended": lambda a: f"Ended sessions for {a.target}" + (f" ({a.detail})" if a.detail else ""),
    "user_created": _user_created,
    "user_updated": _user_updated,
    "user_enabled": lambda a: f"Enabled user {a.target}",
    "user_disabled": lambda a: f"Disabled user {a.target}",
    "users_imported": lambda a: f"Imported users: {a.detail}",
    "profile_updated": lambda a: "Updated own profile",
    "profile_field_added": lambda a: f"Added profile field {a.target}",
    "profile_field_updated": lambda a: f"Changed profile field {a.target}",
    "profile_field_deleted": lambda a: f"Deleted profile field {a.target}" + (f" ({a.detail})" if a.detail else ""),
    "settings_changed": lambda a: "Changed settings: " + _fields(a.detail) if a.detail else "Changed settings",
    "theme_changed": lambda a: "Changed theme: " + _fields(a.detail) if a.detail else "Changed theme",
    "theme_reset": lambda a: "Reset theme to the defaults",
    "modules_changed": lambda a: f"Changed modules: {a.detail}",
    "grade_scale_changed": lambda a: "Changed the grade scale" + (f" ({a.detail})" if a.detail else ""),
    "email_template_changed": lambda a: f"Changed email template {a.target}",
    "email_template_reset": lambda a: f"Reset email template {a.target}",
    "ip_rule_added": lambda a: f"Added IP rule {a.target}" + (f" ({a.detail})" if a.detail else ""),
    "ip_rule_deleted": lambda a: f"Deleted IP rule {a.target}",
    "ip_rule_enabled": lambda a: f"Enabled IP rule {a.target}",
    "ip_rule_disabled": lambda a: f"Disabled IP rule {a.target}",
    "backup_created": lambda a: f"Created backup {a.target}",
    "backup_deleted": lambda a: f"Deleted backup {a.target}",
    "backup_downloaded": lambda a: f"Downloaded backup {a.target}",
    "backup_restored": lambda a: f"Restored backup {a.target}",
    "backup_settings_changed": lambda a: "Changed backup settings: " + _fields(a.detail) if a.detail else "Changed backup settings",
    "maintenance_changed": lambda a: "Changed maintenance mode: " + _fields(a.detail) if a.detail else "Changed maintenance mode",
    "report_exported": lambda a: f"Exported {a.target}",
    "course_created": lambda a: f"Created course {a.target}",
    "course_updated": lambda a: f"Updated course {a.target}",
    "category_created": lambda a: f"Added {a.detail or 'category'} {a.target}",
    "category_updated": lambda a: f"Updated {a.detail or 'category'} {a.target}",
    "category_deleted": lambda a: f"Deleted {a.detail or 'category'} {a.target}",
    "self_enrol": lambda a: f"Enrolled in {a.target}",
    "unenrol": lambda a: f"Unenrolled {a.detail} from {a.target}",
    "bulk_enrol": lambda a: f"Bulk enrolment{_in(a.target)}: {a.detail}",
    "announcement_posted": lambda a: _with("Posted announcement", a),
    "announcement_edited": lambda a: _with("Edited announcement", a),
    "resource_added": lambda a: _with("Added resource", a),
    "forum_topic_deleted": lambda a: _with("Deleted forum topic", a),
    "attendance_saved": lambda a: _with("Saved attendance", a),
    "attendance_session_deleted": lambda a: _with("Deleted attendance session", a),
    "completion_rule_saved": lambda a: f"Saved completion rule{_in(a.target)}",
    "certificates_issued": lambda a: f"Issued certificates{_in(a.target)}: {a.detail}",
    "certificate_revoked": lambda a: f"Revoked certificate {a.target}" + (f" ({a.detail})" if a.detail else ""),
    "assignment_saved": lambda a: _with("Saved assignment", a),
    "assignment_submitted": lambda a: _with("Submitted assignment", a),
    "extension_granted": lambda a: f"Granted extension{_in(a.target)}: {a.detail}",
    "extension_removed": lambda a: f"Removed extension{_in(a.target)}: {a.detail}",
    "rubric_saved": lambda a: _with("Saved rubric for", a),
    "rubric_copied": lambda a: f"Copied rubric{_in(a.target)}: {a.detail}",
    "quiz_saved": lambda a: _with("Saved quiz", a),
    "quiz_started": lambda a: _with("Started quiz", a),
    "quiz_submitted": lambda a: _with("Submitted quiz", a),
    "quiz_regraded": lambda a: f"Regraded quiz attempt{_in(a.target)}: {a.detail}",
    "quiz_attempt_reset": lambda a: f"Reset quiz attempt{_in(a.target)}: {a.detail}",
    "quiz_graded": lambda a: f"Graded quiz{_in(a.target)}: {a.detail}",
    "bank_imported": lambda a: f"Imported question bank{_in(a.target)}: {a.detail}",
    "bank_question_saved": lambda a: f"Saved a bank question{_in(a.target)}",
    "bank_questions_added": lambda a: f"Added bank questions to a quiz{_in(a.target)}: {a.detail}",
    "survey_saved": lambda a: _with("Saved survey", a),
    "survey_question_saved": lambda a: _with("Saved survey question", a),
    "survey_deleted": lambda a: _with("Deleted survey", a),
    "grade_item_added": lambda a: _with("Added grade item", a),
    "manual_marks_saved": lambda a: _with("Saved marks for", a),
    "results_published": lambda a: f"Published results{_in(a.target)}: {a.detail}",
    "submission_graded": lambda a: f"Graded submission{_in(a.target)}: {a.detail}",
}


def describe(a):
    """The sentence for one AuditLog row."""
    fn = EVENTS.get(a.action)
    if fn:
        try:
            return fn(a)
        except Exception:  # pragma: no cover
            pass
    text = a.action.replace("_", " ").capitalize()
    return text + (f" {a.target}" if a.target else "") + (f" ({a.detail})" if a.detail else "")


def who(a):
    """The username shown in the User column. A failed login has no user row, only the account name that was tried."""
    if a.user_id:
        return a.user.username
    return a.target if a.action == "login_failed" and a.target else "—"


def when(dt):
    """'27 Oct, 3:30 PM', with the year only when it is not this year."""
    local = timezone.localtime(dt)
    return date_format(local, "j M, g:i A" if local.year == timezone.localtime().year else "j M Y, g:i A")


# Filter dropdown: key, label, Q. Anything not listed still appears under "All events".
CATEGORIES = [
    ("logins", "Logins", Q(action__in=["sign_in", "sign_out", "sign_out_others", "login_failed", "two_factor_failed"])),
    ("roles", "Role changes", Q(action="user_updated", detail__startswith="role ")),
    ("blocked", "Blocked IPs", Q(result="blocked") | Q(action__startswith="ip_rule_")),
    ("user_created", "User created", Q(action__in=["user_created", "users_imported"])),
    ("settings", "Settings changed", Q(action__in=["settings_changed", "theme_changed", "theme_reset", "modules_changed", "grade_scale_changed",
                                                  "maintenance_changed", "backup_settings_changed", "email_template_changed", "email_template_reset", "profile_field_added", "profile_field_updated", "profile_field_deleted"])),
    ("security", "Passwords & security", (Q(action__startswith="two_factor_") & ~Q(action="two_factor_failed"))
     | Q(action__in=["password_change", "password_reset", "password_reset_requested", "password_reset_done", "session_ended", "sessions_ended"])),
    ("accounts", "Account changes", Q(action__in=["user_enabled", "user_disabled", "profile_updated"]) | (Q(action="user_updated") & ~Q(detail__startswith="role "))),
    ("courses", "Courses & enrolment", Q(action__in=["course_created", "course_updated", "category_created", "category_updated", "category_deleted", "self_enrol", "unenrol", "bulk_enrol", "announcement_posted", "announcement_edited", "resource_added",
                                                      "forum_topic_deleted", "attendance_saved", "attendance_session_deleted", "completion_rule_saved",
                                                      "certificates_issued", "certificate_revoked"])),
    ("assessments", "Quizzes & assignments", Q(action__startswith="quiz_") | Q(action__startswith="bank_") | Q(action__startswith="assignment_")
     | Q(action__startswith="rubric_") | Q(action__startswith="survey_") | Q(action__startswith="extension_")),
    ("grades", "Grades", Q(action__in=["grade_item_added", "manual_marks_saved", "results_published", "submission_graded", "quiz_graded", "quiz_regraded", "quiz_attempt_reset"])),
    ("data", "Backups & exports", (Q(action__startswith="backup_") & ~Q(action="backup_settings_changed")) | Q(action="report_exported")),
]
CATEGORY_LABELS = [(k, label) for k, label, _ in CATEGORIES]


def category_q(key):
    for k, _, q in CATEGORIES:
        if k == key:
            return q
    return None
