from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.uploads import serve_file

from . import services
from .forms import UploadForm
from .models import PrivateFile


@login_required
def file_list(request):
    return render(request, "files/list.html", {"files": PrivateFile.objects.filter(owner=request.user), "usage": services.usage(request.user),
                                                "form": UploadForm(owner=request.user)})


@require_POST
@login_required
def upload(request):
    form = UploadForm(request.POST, request.FILES, owner=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "File uploaded.")
        return redirect("files:list")
    return render(request, "files/list.html", {"files": PrivateFile.objects.filter(owner=request.user), "usage": services.usage(request.user),
                                                "form": form}, status=400)


def _own(request, file_id):
    obj = get_object_or_404(PrivateFile, pk=file_id)
    if obj.owner_id != request.user.pk:
        raise PermissionDenied
    return obj


@login_required
def download(request, file_id):
    return serve_file(_own(request, file_id).file)


@require_POST
@login_required
def delete(request, file_id):
    _own(request, file_id).delete()
    messages.success(request, "File deleted.")
    return redirect("files:list")
