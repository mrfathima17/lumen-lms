"""Sidebar items per role, mirroring the HTML prototype.

Each entry is (url_name, icon, label). url_name None means "not built yet" and renders disabled.
A string entry is a section heading. As pages are built, replace None with the real URL name.
"""

STUDENT = [
    ("accounts:student-dashboard", "home", "Dashboard"), ("courses:my-courses", "book", "My Courses"), ("courses:catalog", "search", "Course catalog"),
    ("completion:mine", "check-circle", "Course completion"), ("assignments:overview", "check-square", "Assignments"), ("schedule:calendar", "calendar", "Calendar"), ("schedule:timetable", "clock", "Timetable"), ("schedule:todo", "clipboard", "To-do"),
    "Results",
    ("grading:my-grades", "graduation", "Grades"), ("grading:my-results", "file-text", "Exam results & GPA"), ("attendance:my-attendance", "calendar-check", "Attendance"), ("completion:certificates", "award", "Certificates"),
    "Community",
    ("quizzes:student-list", "edit", "Quizzes"), ("surveys:student-list", "bar-chart", "Polls & surveys"), ("messaging:inbox", "message", "Messages"), ("messaging:forums", "messages", "Forums"), ("messaging:announcements", "megaphone", "Announcements"), ("files:list", "folder", "Private files"),
    "Account",
    ("messaging:notifications", "bell", "Notifications"), ("accounts:profile", "settings", "Profile & settings"), ("accounts:customise-dashboard", "layout", "Customise dashboard"), ("core:help", "help", "Help"),
]

LECTURER = [
    ("accounts:lecturer-dashboard", "home", "Dashboard"), ("courses:my-courses", "book", "My Courses"), ("assignments:overview", "upload", "Submissions"), ("schedule:calendar", "calendar", "Calendar"), ("schedule:timetable", "clock", "Timetable"),
    ("quizzes:manage-list", "edit", "Quiz Manager"), ("quizzes:bank-list-all", "archive", "Question bank"), ("courses:tool-students", "users", "Students"),
    ("grading:gradebook-list", "graduation", "Gradebook"), ("attendance:course-list", "calendar-check", "Attendance"), ("completion:manage-list", "check-circle", "Completion"), ("courses:tool-reports", "trending", "Reports"),
    "Course tools",
    ("courses:tool-add-material", "upload", "Add material"), ("courses:tool-settings", "wrench", "Course settings"), ("surveys:manage-list", "bar-chart", "Polls & surveys"),
    ("courses:tool-groups", "users", "Groups"), ("assignments:extensions-list", "timer", "Deadline extensions"), ("courses:preview", "eye", "View as student"),
    "Communication",
    ("messaging:announcements", "megaphone", "Announcements"), ("messaging:forums", "messages", "Forums"), ("messaging:inbox", "message", "Messages"), ("files:list", "folder", "Private files"),
    ("messaging:notifications", "bell", "Notifications"), ("accounts:profile", "settings", "Profile & settings"),
]

ADMIN = [
    ("accounts:admin-overview", "bar-chart", "Overview"),
    "People",
    ("administration:users", "users", "Users"), ("administration:import", "download", "Bulk user import"), ("administration:profile-fields", "file-list", "Custom profile fields"),
    ("administration:activity", "activity", "User activity"), ("administration:roles", "key", "Roles & permissions"),
    "Courses",
    ("courses:admin-courses", "book", "Courses"), ("courses:admin-categories", "building", "Departments & semesters"), ("administration:bulk-enrolment", "plus-circle", "Bulk enrolment"), ("messaging:announcements", "megaphone", "Announcements"),
    "Appearance & modules",
    ("administration:theme", "palette", "Theme & branding"), ("administration:modules", "layout", "Plugins & modules"), ("administration:email-templates", "mail", "Email templates"),
    "Security & monitoring",
    ("administration:access", "shield", "Access & IP rules"), ("administration:reports", "trending", "Reports"), ("administration:audit", "file-text", "Audit log"), ("administration:sessions", "monitor", "Active sessions"),
    "System",
    ("administration:backups", "save", "Backup & maintenance"), ("administration:settings", "settings", "System settings"), ("messaging:notifications", "bell", "Notifications"), ("accounts:profile", "settings", "Profile & settings"),
]

# Pages that live "inside" a sidebar item keep that item highlighted.
ACTIVE_ALIASES = {
    "courses:detail": "courses:my-courses", "courses:participants": "courses:my-courses", "courses:groups": "courses:my-courses",
    "assignments:detail": "assignments:overview", "assignments:submissions": "assignments:overview", "assignments:grade": "assignments:overview",
    "assignments:extensions": "assignments:extensions-list", "assignments:rubric": "assignments:overview", "assignments:criterion-new": "assignments:overview", "assignments:criterion-edit": "assignments:overview", "assignments:edit": "assignments:overview", "assignments:new": "assignments:overview",
    "quizzes:student-detail": "quizzes:student-list", "quizzes:attempt": "quizzes:student-list", "quizzes:result": "quizzes:student-list",
    "quizzes:editor": "quizzes:manage-list", "quizzes:edit": "quizzes:manage-list", "quizzes:new": "quizzes:manage-list", "quizzes:attempts": "quizzes:manage-list",
    "quizzes:grade": "quizzes:manage-list", "quizzes:question-new": "quizzes:manage-list", "quizzes:question-edit": "quizzes:manage-list",
    "grading:gradebook": "grading:gradebook-list", "grading:item-add": "grading:gradebook-list", "grading:item-edit": "grading:gradebook-list",
    "grading:manual-marks": "grading:gradebook-list",
    "attendance:course": "attendance:course-list", "attendance:session-new": "attendance:course-list", "attendance:sheet": "attendance:course-list",
    "schedule:event-new": "schedule:calendar", "schedule:course-timetable": "schedule:timetable",
    "messaging:sent": "messaging:inbox", "messaging:compose": "messaging:inbox", "messaging:detail": "messaging:inbox",
    "messaging:forum": "messaging:forums", "messaging:topic": "messaging:forums", "messaging:topic-new": "messaging:forums",
    "messaging:announcement-new": "messaging:announcements",
    "accounts:person": "accounts:profile", "accounts:two-factor": "accounts:profile", "completion:mine-course": "completion:mine", "surveys:student-detail": "surveys:student-list", "quizzes:bank-list": "quizzes:bank-list-all", "quizzes:bank-new": "quizzes:bank-list-all", "quizzes:bank-edit": "quizzes:bank-list-all", "quizzes:bank-import": "quizzes:bank-list-all", "surveys:editor": "surveys:manage-list", "surveys:edit": "surveys:manage-list", "surveys:new": "surveys:manage-list", "surveys:results": "surveys:manage-list", "surveys:question-new": "surveys:manage-list", "surveys:question-edit": "surveys:manage-list", "completion:manage": "completion:manage-list", "completion:issue-all": "completion:manage-list", "administration:user-new": "administration:users", "administration:user-activity": "administration:activity", "administration:profile-field": "administration:profile-fields", "administration:user-edit": "administration:users",
    "administration:import-confirm": "administration:import", "administration:import-result": "administration:import",
    "administration:grade-scale": "administration:settings", "administration:email-template": "administration:email-templates",
    "courses:admin-course-new": "courses:admin-courses", "courses:admin-course-edit": "courses:admin-courses",
}

from apps.core.modules import module_for_url_name  # noqa: E402

NAV = {"student": STUDENT, "lecturer": LECTURER, "admin": ADMIN}


def nav_for(role, current_url_name="", disabled=()):
    """Return a list of dicts for the template: kind is 'section' or 'link'."""
    current_url_name = ACTIVE_ALIASES.get(current_url_name, current_url_name)
    out = []
    for entry in NAV.get(role, STUDENT):
        if isinstance(entry, str):
            out.append({"kind": "section", "label": entry})
        else:
            url_name, icon, label = entry
            if disabled and module_for_url_name(url_name) in disabled:
                continue
            out.append({"kind": "link", "url_name": url_name, "icon": icon, "label": label, "active": url_name == current_url_name})
    return out
