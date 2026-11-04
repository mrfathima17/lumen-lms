from django.conf import settings
from django.db import models
from django.utils import timezone


class Category(models.Model):
    """A faculty, a department or a semester. A department can sit in a faculty; courses point to a department and a semester."""

    class Kind(models.TextChoices):
        FACULTY = "faculty", "Faculty"
        DEPARTMENT = "department", "Department"
        SEMESTER = "semester", "Semester"

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.DEPARTMENT)
    faculty = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="departments",
                                limit_choices_to={"kind": "faculty"})
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [models.UniqueConstraint(fields=["name", "kind"], name="uniq_category_name_kind")]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    @property
    def span(self):
        """Semesters only: 'Aug – Dec 2026', or 'Nov 2026 – Feb 2027' when it crosses a year."""
        if not (self.start_date and self.end_date):
            return ""
        a, b = self.start_date, self.end_date
        if a.year == b.year:
            return f"{a:%b} \u2013 {b:%b %Y}"
        return f"{a:%b %Y} \u2013 {b:%b %Y}"

    @property
    def status(self):
        """Semesters only: upcoming, current or archived, worked out from the dates. Empty when no dates are set."""
        if self.kind != self.Kind.SEMESTER or not (self.start_date and self.end_date):
            return ""
        today = timezone.localdate()
        if today < self.start_date:
            return "upcoming"
        return "current" if today <= self.end_date else "archived"


class Course(models.Model):
    code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=150)
    summary = models.TextField(blank=True)
    department = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="department_courses",
                                   limit_choices_to={"kind": "department"})
    semester = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="semester_courses",
                                 limit_choices_to={"kind": "semester"})
    credits = models.PositiveSmallIntegerField(default=3)
    lecturers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="teaching_courses",
                                       limit_choices_to={"role": "lecturer"})
    is_visible = models.BooleanField(default=True, help_text="Hidden courses are only seen by staff.")
    allow_self_enrol = models.BooleanField(default=False)
    enrol_key = models.CharField(max_length=40, blank=True, help_text="Optional key students must enter to enrol themselves.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.title}"

    @property
    def tone(self):
        """1 to 6: picks the colour of the course's cover so each course keeps the same one everywhere."""
        return self.pk % 6 + 1 if self.pk else 1


class Topic(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="topics")
    title = models.CharField(max_length=150)
    summary = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.title


class Enrolment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrolments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrolments")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__last_name", "user__first_name", "user__username"]
        constraints = [models.UniqueConstraint(fields=["course", "user"], name="uniq_enrolment")]

    def __str__(self):
        return f"{self.user} in {self.course.code}"


class Group(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="groups")
    name = models.CharField(max_length=80)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="course_groups")

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["course", "name"], name="uniq_group_name_per_course")]

    def __str__(self):
        return f"{self.course.code} · {self.name}"
