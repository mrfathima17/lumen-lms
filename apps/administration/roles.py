"""A read-only description of what each role can do. It documents the rules the code enforces;
changing it here does not change behaviour (tests check the important rows against the real views)."""

ROLES = [("student", "Student"), ("lecturer", "Lecturer"), ("admin", "Administrator")]

# (area, capability, student, lecturer, admin)  — values: True, False or a short note.
MATRIX = [
    ("Courses", "See courses they are enrolled in", True, "Courses they teach", True),
    ("Courses", "Create, edit and archive courses", False, False, True),
    ("Courses", "Add content, assignments and quizzes", False, "Own courses", True),
    ("Courses", "Enrol and suspend students", False, "Own courses", True),
    ("Assignments", "Submit work", True, False, False),
    ("Assignments", "Mark work and grant extensions", False, "Own courses", "All courses"),
    ("Quizzes", "Attempt quizzes", True, False, False),
    ("Quizzes", "Build and mark quizzes", False, "Own courses", "All courses"),
    ("Grades", "See own grades, GPA and attendance", True, False, False),
    ("Grades", "Run the gradebook and publish results", False, "Own courses", "All courses"),
    ("Grades", "Edit the grade scale", False, False, True),
    ("Completion", "Earn and download certificates", True, False, False),
    ("Completion", "Set completion rules, issue and revoke certificates", False, "Own courses", "All courses"),
    ("Attendance", "Take attendance", False, "Own courses", "All courses"),
    ("Messaging", "Message people who share a course", True, True, "Anyone"),
    ("Messaging", "Post announcements", False, "Own courses", "Whole site"),
    ("Account", "Two-factor sign-in (own account)", True, True, True),
    ("Administration", "Require two-factor by role, reset someone's two-factor", False, False, True),
    ("Files", "Private files (owner only, even admins cannot open them)", True, True, True),
    ("Administration", "Create and disable users, reset passwords", False, False, True),
    ("Administration", "Bulk import, audit log, reports", False, False, True),
    ("Administration", "IP rules, theme, email templates, modules, profile fields, settings", False, False, True),
    ("Administration", "Active sessions and backups", False, False, True),
]
