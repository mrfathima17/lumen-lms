"""Optional modules an administrator can switch off. Core areas (courses, assignments, grading, messages,
announcements, notifications) are always on. A disabled module vanishes from the menus and its pages answer 404."""

# key -> label, description, URL prefixes, sidebar url names (exact or "namespace:" prefix)
MODULES = {
    "quizzes": ("Quizzes", "Timed quizzes, question editor and marking.", ("/quizzes/", "/quiz-manager/"), ("quizzes:",)),
    "attendance": ("Attendance", "Attendance sheets, reports and the 80% warning.", ("/attendance/", "/my-attendance/"), ("attendance:",)),
    "schedule": ("Calendar, timetable and to-do", "Month calendar, weekly timetable, personal to-do list and .ics export.", ("/calendar/", "/timetable/", "/todo/"), ("schedule:",)),
    "forums": ("Course forums", "Discussion forums per course.", ("/forums/",), ("messaging:forums", "messaging:forum", "messaging:topic")),
    "surveys": ("Polls and surveys", "Course polls and surveys with results.", ("/surveys/", "/survey-manager/"), ("surveys:",)),
    "files": ("Private files", "Personal file storage with a quota.", ("/files/",), ("files:",)),
}


def disabled_keys(request=None):
    """Set of switched-off module keys, looked up once per request."""
    if request is not None and hasattr(request, "_disabled_modules"):
        return request._disabled_modules
    from .models import ModuleSetting

    keys = set(ModuleSetting.objects.filter(enabled=False, key__in=MODULES).values_list("key", flat=True))
    if request is not None:
        request._disabled_modules = keys
    return keys


def module_for_path(path):
    for key, (_, _, prefixes, _) in MODULES.items():
        if any(path.startswith(p) for p in prefixes):
            return key
    return None


def module_for_url_name(url_name):
    if not url_name:
        return None
    for key, (_, _, _, names) in MODULES.items():
        if any(url_name == n or (n.endswith(":") and url_name.startswith(n)) or (not n.endswith(":") and url_name.startswith(n + "-")) for n in names):
            return key
    return None
