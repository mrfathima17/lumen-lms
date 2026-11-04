from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.core import audit
from apps.courses import permissions as perm
from apps.courses.models import Course

from . import bank
from .forms import BankQuestionForm
from .models import BankQuestion, Question, Quiz


def _course(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    return course


def _bank_question(request, pk):
    bq = get_object_or_404(BankQuestion.objects.select_related("course"), pk=pk)
    if not perm.can_manage(request.user, bq.course):
        raise PermissionDenied
    return bq


@role_required("lecturer", "admin")
def bank_courses(request):
    courses = perm.visible_courses_for(request.user).annotate(n=Count("bank_questions")).order_by("code")
    return render(request, "quizzes/bank_courses.html", {"courses": courses})


@role_required("lecturer", "admin")
def bank_list(request, course_id):
    course = _course(request, course_id)
    qs = BankQuestion.objects.filter(course=course)
    term, cat, kind = request.GET.get("q", "").strip(), request.GET.get("category", ""), request.GET.get("kind", "")
    if term:
        qs = qs.filter(Q(text__icontains=term) | Q(category__icontains=term))
    if cat:
        qs = qs.filter(category=cat)
    if kind in dict(Question.Kind.choices):
        qs = qs.filter(kind=kind)
    cats = BankQuestion.objects.filter(course=course).exclude(category="").order_by().values_list("category", flat=True).distinct()
    quizzes = [qz for qz in Quiz.objects.filter(course=course) if not qz.attempts.exists()]
    used = {}
    for text, title in Question.objects.filter(quiz__course=course).values_list("text", "quiz__title"):
        used.setdefault(text, [])
        if title not in used[text]:
            used[text].append(title)
    questions = list(qs)
    for q in questions:
        q.used_in = ", ".join(used.get(q.text, []))
    return render(request, "quizzes/bank_list.html", {
        "course": course, "questions": questions, "categories": sorted(cats), "quizzes": quizzes, "kinds": Question.Kind.choices,
        "term": term, "cat": cat, "kind": kind, "total": BankQuestion.objects.filter(course=course).count(),
    })


@role_required("lecturer", "admin")
def bank_edit(request, course_id=None, pk=None):
    bq = _bank_question(request, pk) if pk else None
    course = bq.course if bq else _course(request, course_id)
    form = BankQuestionForm(request.POST or None, instance=bq)
    if request.method == "POST" and form.is_valid():
        form.save_bank(course)
        audit.record(request, "bank_question_saved", target=course.code)
        messages.success(request, "Question saved to the bank.")
        return redirect("quizzes:bank-list", course_id=course.pk)
    return render(request, "quizzes/bank_form.html", {"form": form, "course": course, "bq": bq})


@require_POST
@role_required("lecturer", "admin")
def bank_delete(request, pk):
    bq = _bank_question(request, pk)
    bq.delete()
    messages.success(request, "Removed from the bank. Quizzes that already use it are not affected.")
    return redirect("quizzes:bank-list", course_id=bq.course_id)


@require_POST
@role_required("lecturer", "admin")
def bank_add_to_quiz(request, course_id):
    course = _course(request, course_id)
    quiz = Quiz.objects.filter(course=course, pk=request.POST.get("quiz") or 0).first()
    ids = [i for i in request.POST.getlist("pick") if i.isdigit()]
    picked = list(BankQuestion.objects.filter(course=course, pk__in=ids).order_by("id"))
    if not quiz or not picked:
        messages.error(request, "Choose a quiz and tick at least one question.")
    elif quiz.attempts.exists():
        messages.error(request, "Students have already started that quiz, so its questions are locked.")
    else:
        bank.add_to_quiz(picked, quiz)
        audit.record(request, "bank_questions_added", target=course.code, detail=f"{len(picked)} to {quiz.title}")
        messages.success(request, f"Added {len(picked)} question{'s' if len(picked) != 1 else ''} to {quiz.title}.")
        return redirect("quizzes:editor", pk=quiz.pk)
    return redirect("quizzes:bank-list", course_id=course.pk)


@require_POST
@role_required("lecturer", "admin")
def question_to_bank(request, question_id):
    q = get_object_or_404(Question.objects.select_related("quiz__course"), pk=question_id)
    if not perm.can_manage(request.user, q.quiz.course):
        raise PermissionDenied
    bank.from_quiz(q, q.quiz.course)
    messages.success(request, "Saved to the question bank.")
    return redirect("quizzes:editor", pk=q.quiz_id)


@role_required("lecturer", "admin")
def bank_import(request, course_id):
    course = _course(request, course_id)
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f or not f.name.lower().endswith(".csv"):
            messages.error(request, "Upload a .csv file.")
        else:
            raw = f.read()
            rows, error = bank.parse(raw)
            if error:
                messages.error(request, error)
            else:
                return render(request, "quizzes/bank_preview.html", {
                    "course": course, "rows": rows, "text": raw.decode("utf-8-sig"),
                    "ok": sum(1 for r in rows if not r["errors"]), "bad": sum(1 for r in rows if r["errors"])})
    return render(request, "quizzes/bank_import.html", {"course": course, "columns": bank.COLUMNS})


@require_POST
@role_required("lecturer", "admin")
def bank_import_confirm(request, course_id):
    course = _course(request, course_id)
    rows, error = bank.parse(request.POST.get("text", ""))  # re-checked on the server: the hidden field is never trusted
    if error:
        messages.error(request, error)
        return redirect("quizzes:bank-import", course_id=course.pk)
    n = bank.import_rows(rows, course)
    audit.record(request, "bank_imported", target=course.code, detail=f"{n} imported, {len(rows) - n} skipped")
    messages.success(request, f"Imported {n} question{'s' if n != 1 else ''}.")
    return redirect("quizzes:bank-list", course_id=course.pk)


@role_required("lecturer", "admin")
def bank_template(request):
    resp = HttpResponse(bank.TEMPLATE, content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="question-bank-template.csv"'
    return resp


@role_required("lecturer", "admin")
def bank_export(request, course_id):
    course = _course(request, course_id)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="question-bank-{course.code}.csv"'
    bank.export_csv(BankQuestion.objects.filter(course=course), resp)
    return resp
