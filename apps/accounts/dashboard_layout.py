"""Which blocks a student's dashboard shows, and in what order. Stored on the user; no layout means the default."""

BLOCKS = [
    ("stats", "Key numbers", "Courses, deadlines, quizzes and GPA", True),
    ("courses", "My courses", "Course cards with progress and lecturer", True),
    ("deadlines", "Upcoming deadlines", "Assignments and quizzes due soon", False),
    ("announcements", "Announcements", "Latest news from lecturers", False),
    ("today", "Today's classes", "Classes today and the next one", False),
    ("progress", "Course progress", "Completion bar for each course", False),
]
IDS = [b[0] for b in BLOCKS]
INFO = {b[0]: {"id": b[0], "name": b[1], "desc": b[2], "full": b[3]} for b in BLOCKS}


def layout_for(user):
    """Return [{"id", "name", "desc", "full", "shown"}] in the user's order. Unknown ids are dropped, new blocks are appended."""
    saved = user.dashboard_layout if isinstance(user.dashboard_layout, dict) else {}
    order = [i for i in saved.get("order", []) if i in INFO]
    order += [i for i in IDS if i not in order]
    hidden = set(saved.get("hidden", []))
    return [dict(INFO[i], shown=i not in hidden) for i in order]


def save_layout(user, order, shown):
    order = [i for i in dict.fromkeys(order) if i in INFO]
    order += [i for i in IDS if i not in order]
    user.dashboard_layout = {"order": order, "hidden": [i for i in order if i not in set(shown)]}
    user.save(update_fields=["dashboard_layout"])


def move(order, block_id, step):
    if block_id not in order:
        return order
    i = order.index(block_id)
    j = i + step
    if 0 <= j < len(order):
        order[i], order[j] = order[j], order[i]
    return order
