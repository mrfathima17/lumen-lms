"""App-level backups: one zip holding every table as JSON (dumpdata) plus the uploaded files.

This is portable between SQLite and MySQL, which makes it good for moving data and for a
nightly safety copy. For a large production database also take a native `mysqldump`.
"""
import io
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

NAME_RE = re.compile(r"^lumen-backup-\d{8}-\d{6}\.zip$")
# Sessions are temporary, contenttypes/permissions are rebuilt by migrate, axes rows are lockout state.
EXCLUDE = ["sessions", "contenttypes", "auth.permission", "admin.logentry", "axes"]


def backup_dir():
    d = settings.BACKUP_DIR
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:  # pragma: no cover
        pass
    return d


def valid_name(name):
    return bool(NAME_RE.match(name or ""))


def path_for(name):
    """Resolve a backup file name safely, or None. Only names we generate are accepted."""
    if not valid_name(name):
        return None
    p = backup_dir() / name
    return p if p.is_file() else None


def create_backup():
    """Write a new backup and return its file name."""
    when = timezone.now()
    while (backup_dir() / f"lumen-backup-{when:%Y%m%d-%H%M%S}.zip").exists():
        when += timedelta(seconds=1)  # never overwrite an existing backup (two in the same second, or a safety copy before a restore)
    name = f"lumen-backup-{when:%Y%m%d-%H%M%S}.zip"
    final = backup_dir() / name
    part = final.with_suffix(".part")
    buf = io.StringIO()
    call_command("dumpdata", exclude=EXCLUDE, indent=1, stdout=buf, use_natural_foreign_keys=False)
    media = settings.MEDIA_ROOT
    files = 0
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("data.json", buf.getvalue())
            if media.exists():
                for f in sorted(media.rglob("*")):
                    if f.is_file():
                        z.write(f, "media/" + f.relative_to(media).as_posix())
                        files += 1
            z.writestr("manifest.json", json.dumps({"created": timezone.now().isoformat(), "media_files": files, "format": 1}))
        part.replace(final)
    finally:
        if part.exists():
            part.unlink()
    return name


def list_backups():
    """Newest first."""
    out = []
    for p in backup_dir().iterdir():
        if valid_name(p.name) and p.is_file():
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "created": datetime.fromtimestamp(st.st_mtime, dt_timezone.utc)})
    return sorted(out, key=lambda b: b["name"], reverse=True)


def delete_backup(name):
    p = path_for(name)
    if not p:
        return False
    p.unlink()
    return True


def prune(keep):
    """Keep the newest `keep` backups; return how many were deleted."""
    old = list_backups()[max(keep, 1):]
    for b in old:
        delete_backup(b["name"])
    return len(old)


def prune_older_than(days):
    """Delete backups older than `days` days, but never the newest one. Returns how many were deleted."""
    cutoff = timezone.now() - timedelta(days=max(days, 1))
    old = [b for b in list_backups()[1:] if b["created"] < cutoff]
    for b in old:
        delete_backup(b["name"])
    return len(old)


def run_scheduled(now=None):
    """Called every few minutes by the scheduler: make the daily backup once the chosen time has passed, once per day.
    Returns the new backup's name, or None when nothing was due."""
    from apps.core.models import SiteSettings

    s = SiteSettings.load()
    if not s.backup_auto:
        return None
    now = timezone.localtime(now or timezone.now())
    due = now.replace(hour=s.backup_time.hour, minute=s.backup_time.minute, second=0, microsecond=0)
    if now < due or (s.last_auto_backup and timezone.localtime(s.last_auto_backup) >= due):
        return None
    name = create_backup()
    prune_older_than(s.backup_keep_days)
    SiteSettings.objects.filter(pk=1).update(last_auto_backup=timezone.now())
    return name


class RestoreError(Exception):
    """Raised before anything is changed when a backup cannot be used; the message is safe to show."""


def _open_checked(name):
    path = path_for(name)
    if not path:
        raise RestoreError("That backup no longer exists.")
    try:
        z = zipfile.ZipFile(path)
        manifest = json.loads(z.read("manifest.json"))
        json.loads(z.read("data.json"))  # must parse before we touch anything
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise RestoreError("This file is not a valid Lumen backup.") from None
    if manifest.get("format") != 1:
        raise RestoreError("This backup was made by an unknown version of Lumen.")
    return z


def _extract_media(z, dest):
    """Unpack media/ into dest, refusing any path that could escape it."""
    for info in z.infolist():
        if not info.filename.startswith("media/") or info.is_dir():
            continue
        rel = PurePosixPath(info.filename).relative_to("media")
        if rel.is_absolute() or ".." in rel.parts or "\\" in info.filename:
            raise RestoreError("The backup contains an unsafe file path, so it was not restored.")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def restore_backup(name):
    """Replace ALL data and uploaded files with the contents of a backup. Returns the name of the safety backup made first.

    Order matters: validate and unpack first (nothing changed yet), take a safety backup of the current state, then
    swap the data in one transaction, then the files. Everyone is signed out afterwards (sessions are not part of backups)."""
    from apps.core.models import SiteSettings

    z = _open_checked(name)
    with z, tempfile.TemporaryDirectory(dir=backup_dir()) as tmp:
        staged = Path(tmp) / "media"
        staged.mkdir()
        _extract_media(z, staged)
        data_file = Path(tmp) / "data.json"
        data_file.write_bytes(z.read("data.json"))
        safety = create_backup()
        was_on = SiteSettings.load().maintenance_mode
        SiteSettings.objects.filter(pk=1).update(maintenance_mode=True)  # keep users out while the data is swapped
        try:
            with transaction.atomic():
                call_command("flush", interactive=False, reset_sequences=False, verbosity=0)
                call_command("loaddata", str(data_file), verbosity=0)
        except Exception:
            SiteSettings.objects.filter(pk=1).update(maintenance_mode=was_on)
            raise
        media = settings.MEDIA_ROOT
        media.mkdir(parents=True, exist_ok=True)
        for child in list(media.iterdir()):
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        for child in staged.iterdir():
            shutil.move(str(child), str(media / child.name))
        SiteSettings.objects.filter(pk=1).update(maintenance_mode=was_on)
    return safety
