from django.db import models

from apps.core.uploads import upload_path, validate_upload
from apps.courses.models import Topic


class Resource(models.Model):
    class Kind(models.TextChoices):
        FILE = "file", "File"
        LINK = "link", "Link"

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="resources")
    kind = models.CharField(max_length=4, choices=Kind.choices, default=Kind.FILE)
    title = models.CharField(max_length=150)
    description = models.CharField(max_length=300, blank=True)
    file = models.FileField(upload_to=upload_path("resources"), blank=True, validators=[validate_upload])
    url = models.URLField(blank=True)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.title

    @property
    def course(self):
        return self.topic.course


class ResourceDone(models.Model):
    """A student's own "mark as done" tick on a material. Personal progress only; no rule or grade reads it."""

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="done_by")
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["resource", "user"], name="uniq_resource_done")]
