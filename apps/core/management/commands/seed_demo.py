"""Create demo users, courses and enrolments for local development. Safe to run twice. Never use in production."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from datetime import timedelta

from django.utils import timezone

from apps.assignments.models import Assignment
from apps.content.models import Resource
from apps.quizzes.models import Choice, Question, Quiz
from apps.courses.models import Category, Course, Enrolment, Topic

PASSWORD = "Demo-pass-12345"


class Command(BaseCommand):
    help = "Create demo data for development."

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG on (development settings).")
        people = [
            ("admin", "admin", "System", "Admin", None), ("nperera", "lecturer", "Nimal", "Perera", None),
            ("s2026-0142", "student", "Amal", "Karunaratne", "2026-0142"), ("s2026-0150", "student", "Sara", "Fernando", "2026-0150"),
        ]
        users = {}
        for username, role, first, last, idx in people:
            u, created = User.objects.get_or_create(username=username, defaults={"role": role, "first_name": first, "last_name": last, "index_number": idx,
                                                                                  "is_superuser": role == "admin", "is_staff": role == "admin"})
            if created:
                u.set_password(PASSWORD)
                u.save()
            users[username] = u
        cs, _ = Category.objects.get_or_create(name="Computer Science", kind="department")
        sem, _ = Category.objects.get_or_create(name="Semester 3", kind="semester")
        for code, title in (("CS201", "Database Systems"), ("CS215", "Software Engineering"), ("CS230", "Computer Networks")):
            c, _ = Course.objects.get_or_create(code=code, defaults={"title": title, "department": cs, "semester": sem, "credits": 3,
                                                                     "summary": f"Lectures and labs for {title}.", "allow_self_enrol": code == "CS230"})
            c.lecturers.add(users["nperera"])
            if code != "CS230":
                for s in ("s2026-0142", "s2026-0150"):
                    Enrolment.objects.get_or_create(course=c, user=users[s])
            if not c.topics.exists():
                for i, t in enumerate(("Week 1: Introduction", "Week 2: Core concepts", "Week 3: Practice")):
                    Topic.objects.create(course=c, title=t, position=i, summary="Reading list and lab sheet." if i == 0 else "")
        first = Course.objects.get(code="CS201")
        topic = first.topics.first()
        Resource.objects.get_or_create(topic=topic, title="Course handbook (web)", defaults={"kind": "link", "url": "https://example.com/handbook"})
        Assignment.objects.get_or_create(course=first, title="ER Diagram Assignment", defaults={
            "topic": topic, "due_at": timezone.now() + timedelta(days=3), "description": "Draw an ER diagram for the library scenario and submit it as a PDF."})
        quiz, made = Quiz.objects.get_or_create(course=first, title="Quiz 1: Normalisation", defaults={"time_limit_minutes": 20, "max_attempts": 2,
            "closes_at": timezone.now() + timedelta(days=5), "description": "Covers the first three normal forms."})
        if made:
            q1 = Question.objects.create(quiz=quiz, kind="mcq", text="Which normal form removes partial dependencies?", marks=2, position=0)
            for i, (txt, ok) in enumerate((("1NF", False), ("2NF", True), ("3NF", False), ("BCNF", False))):
                Choice.objects.create(question=q1, text=txt, is_correct=ok, position=i)
            q2 = Question.objects.create(quiz=quiz, kind="tf", text="A table in 3NF is always in 2NF.", marks=1, position=1)
            Choice.objects.create(question=q2, text="True", is_correct=True, position=0)
            Choice.objects.create(question=q2, text="False", position=1)
            Question.objects.create(quiz=quiz, kind="short", text="What does the P in PK stand for?", marks=1, position=2, accepted_answers="primary")
            Question.objects.create(quiz=quiz, kind="essay", text="Explain why we normalise a database.", marks=6, position=3)
        self.stdout.write(self.style.SUCCESS(f"Demo data ready. Sign in as admin, nperera or s2026-0142 with password {PASSWORD}"))
