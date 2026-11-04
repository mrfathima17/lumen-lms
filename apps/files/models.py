from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.core.uploads import original_filename, upload_path, validate_upload


class PrivateFile(models.Model):
    """A file in one person's private space. Only the owner can open it; nobody else, including administrators."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="private_files")
    file = models.FileField(upload_to=upload_path("private"), validators=[validate_upload])
    size = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name

    @property
    def name(self):
        return original_filename(self.file.name)


@receiver(post_delete, sender=PrivateFile)
def remove_stored_file(sender, instance, **kwargs):
    """Deleting a row (or its owner) also removes the bytes from disk, so the quota is not just cosmetic."""
    if instance.file:
        instance.file.delete(save=False)
