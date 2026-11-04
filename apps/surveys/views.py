import csv

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.core import audit
from apps.core.exports import safe_cell
from apps.courses import permissions as perm
from apps.courses.models import Course
from apps.messaging.services import notify

from . import services
from .forms import QuestionForm, SurveyForm
from .models import Survey, SurveyQuestion


# ---------------------------------------------------------------- student

@role_required("student")
def student_list(request):
    rows = []
    for s in services.visible_for_student(request.user).order_by("-created_at"):
        rows.append({"survey": s, "state": services.state(s), "answered": services.has_answered(s, request.user)})
    return render(request, "surveys/student_list.html", {"rows": rows})


@role_required("student")
def student_detail(request, pk):
    survey = get_object_or_404(services.visible_for_student(request.user), pk=pk)
    st, answered = services.state(survey), services.has_answered(survey, request.user)
    errors, kept = {}, {}
    if request.method == "POST":
        if answered or st != "open":
            messages.error(request, "You already answered this." if answered else "This is not open for answers.")
            return redirect("surveys:student-detail", pk=pk)
        clean, errors = services.parse(survey, request.POST)
        if not errors:
            if services.submit(survey, request.user, clean):
                messages.success(request, "Thank you, your answers were saved.")
            return redirect("surveys:student-detail", pk=pk)
        kept = clean
    show = services.can_see_results(survey, request.user)
    return render(request, "surveys/student_detail.html", {
        "survey": survey, "state": st, "answered": answered, "questions": list(survey.questions.all()),
        "errors": errors, "kept": kept, "results": services.results(survey) if show else None,
        "can_edit": perm.can_manage(request.user, survey.course),
    })


# ---------------------------------------------------------------- staff

def _survey(request, pk):
    survey = get_object_or_404(Survey.objects.select_related("course"), pk=pk)
    if not perm.can_manage(request.user, survey.course):
        raise PermissionDenied
    return survey


@role_required("lecturer", "admin")
def manage_list(request):
    surveys = Survey.objects.filter(course__in=perm.visible_courses_for(request.user)).select_related("course")
    rows = [{"survey": s, "state": services.state(s), "count": s.submissions.count()} for s in surveys]
    courses = perm.visible_courses_for(request.user).order_by("code")
    return render(request, "surveys/manage_list.html", {"rows": rows, "courses": courses})


@role_required("lecturer", "admin")
def survey_edit(request, course_id=None, pk=None):
    if pk:
        survey = _survey(request, pk)
        course = survey.course
    else:
        survey, course = None, get_object_or_404(Course, pk=course_id)
        if not perm.can_manage(request.user, course):
            raise PermissionDenied
    was_visible = bool(survey and survey.is_visible)
    form = SurveyForm(request.POST or None, instance=survey, locked=bool(survey and services.question_locked(survey)))
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.course = course
        if obj.is_visible and not obj.published_at:
            obj.published_at = timezone.now()
            first_publish = True
        else:
            first_publish = False
        obj.save()
        q = (form.cleaned_data.get("poll_question") or "").strip()
        if not pk and obj.kind == "poll" and q:
            SurveyQuestion.objects.create(survey=obj, position=0, text=q, kind=SurveyQuestion.Kind.SINGLE, required=True,
                                          choices="\n".join(form.poll_option_list(form.cleaned_data)))
        if first_publish:
            notify(services.enrolled_students(course), f"New {obj.get_kind_display().lower()} in {course.code}: {obj.title}", f"/surveys/{obj.pk}/")
        audit.record(request, "survey_saved", target=course.code, detail=obj.title)
        messages.success(request, "Saved.")
        return redirect("surveys:editor", pk=obj.pk)
    return render(request, "surveys/survey_form.html", {"form": form, "course": course, "survey": survey})


@role_required("lecturer", "admin")
def editor(request, pk):
    survey = _survey(request, pk)
    return render(request, "surveys/editor.html", {"survey": survey, "questions": survey.questions.all(), "locked": services.question_locked(survey), "state": services.state(survey)})


@role_required("lecturer", "admin")
def question_edit(request, pk=None, survey_id=None):
    if pk:
        question = get_object_or_404(SurveyQuestion.objects.select_related("survey__course"), pk=pk)
        survey = question.survey
    else:
        question, survey = None, get_object_or_404(Survey.objects.select_related("course"), pk=survey_id)
    if not perm.can_manage(request.user, survey.course):
        raise PermissionDenied
    if services.question_locked(survey):
        messages.error(request, "Students have already answered, so the questions can no longer change.")
        return redirect("surveys:editor", pk=survey.pk)
    if not question and survey.kind == "poll" and survey.questions.exists():
        messages.error(request, "A poll has one question. Change it to a survey to add more.")
        return redirect("surveys:editor", pk=survey.pk)
    form = QuestionForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        q = form.save(commit=False)
        q.survey = survey
        if not question:
            q.position = (survey.questions.order_by("-position").values_list("position", flat=True).first() or 0) + 1
        q.save()
        audit.record(request, "survey_question_saved", target=survey.course.code, detail=q.text[:80])
        messages.success(request, "Question saved.")
        return redirect("surveys:editor", pk=survey.pk)
    return render(request, "surveys/question_form.html", {"form": form, "survey": survey, "question": question})


@require_POST
@role_required("lecturer", "admin")
def question_delete(request, pk):
    q = get_object_or_404(SurveyQuestion.objects.select_related("survey__course"), pk=pk)
    if not perm.can_manage(request.user, q.survey.course):
        raise PermissionDenied
    if services.question_locked(q.survey):
        messages.error(request, "Students have already answered, so the questions can no longer change.")
    else:
        q.delete()
        messages.success(request, "Question removed.")
    return redirect("surveys:editor", pk=q.survey_id)


@require_POST
@role_required("lecturer", "admin")
def survey_delete(request, pk):
    survey = _survey(request, pk)
    course_code, title = survey.course.code, survey.title
    survey.delete()
    audit.record(request, "survey_deleted", target=course_code, detail=title)
    messages.success(request, "Deleted, with all its answers.")
    return redirect("surveys:manage-list")


@role_required("lecturer", "admin")
def staff_results(request, pk):
    survey = _survey(request, pk)
    took, missing = services.participants(survey)
    results = services.results(survey)
    ratings = [r["average"] for r in results["rows"] if r.get("average") is not None]
    total_students = len(took) + len(missing)
    stats = {"responses": results["total"], "students": total_students,
             "response_pct": round(100 * len(took) / total_students) if total_students else None,
             "average": round(sum(ratings) / len(ratings), 1) if ratings else None,
             "comments": sum(r["answered"] for r in results["rows"] if r.get("texts") is not None)}
    return render(request, "surveys/results.html", {"survey": survey, "results": results, "took": took, "missing": missing, "total_students": total_students, "stats": stats, "state": services.state(survey)})


@role_required("lecturer", "admin")
def export(request, pk):
    survey = _survey(request, pk)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="survey-{survey.pk}.csv"'
    w = csv.writer(resp)
    qs = list(survey.questions.all())
    w.writerow(["Student"] + [safe_cell(q.text) for q in qs])
    if survey.anonymous:  # answers carry no name: one row per submission cannot be rebuilt, so list answers per question
        w = csv.writer(resp)
        for q in qs:
            for v in sorted(q.answers.values_list("value", flat=True)):
                w.writerow(["(anonymous)"] + [safe_cell(v) if q.pk == x.pk else "" for x in qs])
        return resp
    for sub in survey.submissions.select_related("student").order_by("student__username"):
        by_q = {}
        for a in sub.answers.all():
            by_q.setdefault(a.question_id, []).append(a.value)
        w.writerow([safe_cell(sub.student.get_full_name() or sub.student.username)] + [safe_cell("; ".join(by_q.get(q.pk, []))) for q in qs])
    return resp
