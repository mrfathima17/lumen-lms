from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.uploads import serve_file
from apps.courses import permissions as perm
from apps.courses.models import Course

from .forms import ResourceForm
from .models import Resource, ResourceDone


@login_required
def add_resource(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    if not course.topics.exists():
        messages.error(request, "Add a topic to the course first; materials live inside topics.")
        return redirect("courses:detail", pk=course.pk)
    form = ResourceForm(request.POST or None, request.FILES or None, course=course)
    if request.method == "POST" and form.is_valid():
        res = form.save(commit=False)
        res.is_visible = "draft" not in request.POST
        res.save()
        audit.record(request, "resource_added", target=course.code, detail=res.title + ("" if res.is_visible else " (draft)"))
        messages.success(request, "Material added." if res.is_visible else "Saved as a draft. Students cannot see it until you show it.")
        return redirect("courses:detail", pk=course.pk)
    return render(request, "content/resource_form.html", {"form": form, "course": course})


@require_POST
@login_required
def resource_action(request, resource_id, action):
    res = get_object_or_404(Resource.objects.select_related("topic__course"), pk=resource_id)
    course = res.topic.course
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    if action == "toggle":
        res.is_visible = not res.is_visible
        res.save(update_fields=["is_visible"])
    elif action == "delete":
        if res.file:
            res.file.delete(save=False)
        res.delete()
        messages.success(request, "Material deleted.")
    else:
        raise PermissionDenied
    return redirect("courses:detail", pk=course.pk)


def _resource_for(request, resource_id, **filters):
    res = get_object_or_404(Resource.objects.select_related("topic__course"), pk=resource_id, **filters)
    course = res.topic.course
    manage = perm.can_manage(request.user, course)
    if not perm.can_view(request.user, course):
        raise PermissionDenied
    if (not res.is_visible or not res.topic.is_visible) and not manage:
        raise PermissionDenied
    return res, course, manage


@login_required
def download(request, resource_id):
    res, _, _ = _resource_for(request, resource_id, kind="file")
    return serve_file(res.file)


# Only types a browser shows harmlessly are ever served inline. Everything else (Office files, text, zips) stays a download.
PREVIEW = {"pdf": "pdf", "png": "image", "jpg": "image", "jpeg": "image", "mp4": "video"}


def _ext(res):
    import os

    return os.path.splitext(res.file.name)[1].lstrip(".").lower() if res.file else ""


@login_required
@xframe_options_sameorigin
def raw(request, resource_id):
    res, _, _ = _resource_for(request, resource_id, kind="file")
    if _ext(res) not in PREVIEW:
        raise Http404
    return serve_file(res.file, inline=True)


@login_required
def viewer(request, resource_id):
    from apps.core.uploads import original_filename

    res, course, manage = _resource_for(request, resource_id)
    siblings = res.topic.resources.all() if manage else res.topic.resources.filter(is_visible=True)
    ids = list(siblings.values_list("pk", flat=True))
    pos = ids.index(res.pk) if res.pk in ids else 0
    prev_id = ids[pos - 1] if pos > 0 else None
    next_id = ids[pos + 1] if pos + 1 < len(ids) else None
    done_ids = set(ResourceDone.objects.filter(user=request.user, resource_id__in=ids).values_list("resource_id", flat=True))
    kind = PREVIEW.get(_ext(res)) if res.kind == "file" else None
    return render(request, "content/viewer.html", {
        "res": res, "course": course, "manage": manage, "preview": kind, "filename": original_filename(res.file.name) if res.file else "",
        "siblings": siblings, "prev_id": prev_id, "next_id": next_id, "pos": pos + 1, "total": len(ids), "done_ids": done_ids, "is_done": res.pk in done_ids, "assignments": res.topic.assignments.filter(is_visible=True) if hasattr(res.topic, "assignments") else [],
    })


@require_POST
@login_required
def toggle_done(request, resource_id):
    res, _, _ = _resource_for(request, resource_id)
    obj, created = ResourceDone.objects.get_or_create(resource=res, user=request.user)
    if not created:
        obj.delete()
    if request.POST.get("back") == "completion":
        return redirect("completion:mine-course", course_id=res.topic.course_id)
    return redirect("content:view", resource_id=res.pk)
