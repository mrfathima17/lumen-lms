"""Shared upload helpers: validation and safe storage paths."""
import os
import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponse
from django.utils.deconstruct import deconstructible
from django.utils.text import get_valid_filename


def validate_upload(f):
    ext = os.path.splitext(f.name)[1].lstrip(".").lower()
    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationError(f"Files of type .{ext or '?'} are not allowed.")
    if f.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(f"The file is larger than {settings.MAX_UPLOAD_MB} MB.")


@deconstructible
class upload_path:
    """upload_to callable that stores files as <folder>/<random>_<clean name>. A class so migrations can serialise it."""

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, instance, filename):
        clean = get_valid_filename(os.path.basename(filename))[:100]
        return f"{self.folder}/{uuid.uuid4().hex[:12]}_{clean}"

    def __eq__(self, other):
        return isinstance(other, upload_path) and other.folder == self.folder


def original_filename(stored_name):
    """Strip the folder and the random prefix we add on upload, giving the name the user chose."""
    return re.sub(r"^[0-9a-f]{12}_", "", os.path.basename(stored_name))


def serve_file(field_file, download_name=None, inline=False):
    """Send a stored file after the caller has checked permission. nginx streams it when X-Accel is on."""
    name = download_name or original_filename(field_file.name)
    if settings.USE_ACCEL_REDIRECT:
        resp = HttpResponse()
        resp["X-Accel-Redirect"] = f"/media/{field_file.name}"
        resp["Content-Type"] = ""
    else:
        resp = FileResponse(field_file.open("rb"))
    resp["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{get_valid_filename(name)}"'
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
