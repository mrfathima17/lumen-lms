from django.conf import settings
from django.db import models


class Event(models.Model):
    """A calendar entry. With a course it is shown to the course's students and lecturers; without one it is private to its owner."""
    course = models.ForeignKey("courses.Course", null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "id"]

    def __str__(self):
        return self.title


class TimetableSlot(models.Model):
    """A weekly recurring class of a course."""

    class Weekday(models.IntegerChoices):
        MON = 0, "Monday"
        TUE = 1, "Tuesday"
        WED = 2, "Wednesday"
        THU = 3, "Thursday"
        FRI = 4, "Friday"
        SAT = 5, "Saturday"
        SUN = 6, "Sunday"

    class Kind(models.TextChoices):
        LECTURE = "lecture", "Lecture"
        LAB = "lab", "Lab"
        TUTORIAL = "tutorial", "Tutorial"

    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="timetable_slots")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.CharField(max_length=60, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.LECTURE)

    class Meta:
        ordering = ["weekday", "start_time", "id"]

    def __str__(self):
        return f"{self.course.code} {self.get_weekday_display()} {self.start_time:%H:%M}"


class TodoItem(models.Model):
    """A personal task. Deadlines from courses are shown beside these but are not stored here."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todos")
    title = models.CharField(max_length=200)
    due_date = models.DateField(null=True, blank=True)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "due_date", "id"]

    def __str__(self):
        return self.title
