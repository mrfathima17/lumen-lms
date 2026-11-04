from django.conf import settings
from django.db import models


class AttendanceSession(models.Model):
    """One class meeting (lecture, lab) for which the lecturer takes attendance."""
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="attendance_sessions")
    title = models.CharField(max_length=120)
    held_on = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-held_on", "-start_time", "-id"]

    def __str__(self):
        return f"{self.course.code} · {self.title} · {self.held_on}"


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"
        EXCUSED = "excused", "Excused"

    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name="records")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance_records")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PRESENT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "student"], name="one_record_per_student_per_session")]

    def __str__(self):
        return f"{self.student} · {self.session} · {self.status}"
