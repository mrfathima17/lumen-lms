from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.courses import permissions as perm
from apps.courses.models import Course

from . import services
from .forms import QuestionForm, QuizForm
from .models import Answer, Attempt, Question, Quiz


def _quiz_for_staff(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related("course"), pk=pk)
    if not perm.can_manage(request.user, quiz.course):
        raise PermissionDenied
    return quiz


def _quiz_for_student(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related("course"), pk=pk)
    if not (quiz.is_visible and perm.can_view(request.user, quiz.course)) or request.user.role != "student":
        raise PermissionDenied
    return quiz


def _own_attempt(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("quiz__course"), pk=attempt_id)
    if attempt.student_id != request.user.pk:
        raise PermissionDenied
    if attempt.status == Attempt.Status.IN_PROGRESS and services.expired(attempt):
        services.finish_attempt(attempt)  # time ran out while the student was away
        attempt.refresh_from_db()
    return attempt


# ------------------------------------------------------------------ student side (/quizzes/)

@login_required
def student_list(request):
    if request.user.role != "student":
        return redirect("quizzes:manage-list")
    now = timezone.now()
    rows = []
    for quiz in Quiz.objects.filter(is_visible=True, course__in=perm.visible_courses_for(request.user)).select_related("course"):
        mine = list(quiz.attempts.filter(student=request.user))
        ok, reason = services.availability(quiz, now)
        rows.append({"quiz": quiz, "open": ok, "reason": reason, "attempts": mine, "running": any(a.status == "in_progress" for a in mine)})
    return render(request, "quizzes/student_list.html", {"rows": rows})


@login_required
def student_detail(request, pk):
    quiz = _quiz_for_student(request, pk)
    services.expire_overdue()
    attempts = list(quiz.attempts.filter(student=request.user))
    ok, reason = services.availability(quiz)
    running = services.in_progress_attempt(quiz, request.user)
    left = quiz.max_attempts - len(attempts)
    previous = []
    for other in Quiz.objects.filter(course=quiz.course, is_visible=True).exclude(pk=quiz.pk):
        best = Attempt.objects.filter(quiz=other, student=request.user, status="graded").order_by("-score").first()
        if best:
            previous.append({"quiz": other, "score": best.score, "total": other.total_marks})
    return render(request, "quizzes/student_detail.html", {
        "quiz": quiz, "attempts": attempts, "open": ok, "reason": reason, "running": running, "attempts_left": max(0, left),
        "total_marks": quiz.total_marks, "count": quiz.questions.count(), "previous": previous, "used": len(attempts),
    })


@require_POST
@login_required
def start(request, pk):
    quiz = _quiz_for_student(request, pk)
    try:
        attempt = services.start_attempt(quiz, request.user)
    except services.QuizError as exc:
        messages.error(request, str(exc))
        return redirect("quizzes:student-detail", pk=quiz.pk)
    audit.record(request, "quiz_started", target=quiz.course.code, detail=f"{quiz.title} #{attempt.number}")
    return redirect("quizzes:attempt", attempt_id=attempt.pk)


@login_required
def attempt_view(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return redirect("quizzes:result", attempt_id=attempt.pk)
    saved = {a.question_id: a for a in attempt.answers.all()}
    questions = []
    for q in attempt.quiz.questions.prefetch_related("choices"):
        a = saved.get(q.pk)
        questions.append({"q": q, "choice_id": a.choice_id if a else None, "text": a.text if a else "",
                          "done": bool(a and (a.choice_id or (a.text or "").strip()))})
    return render(request, "quizzes/attempt.html", {"attempt": attempt, "quiz": attempt.quiz, "questions": questions, "left": services.seconds_left(attempt)})


@require_POST
@login_required
def save_answer(request, attempt_id, question_id):
    """HTMX autosave. Re-checks ownership, the clock and the question on every call."""
    attempt = _own_attempt(request, attempt_id)
    question = get_object_or_404(Question, pk=question_id)
    try:
        services.save_answer(attempt, question, choice_id=request.POST.get("choice"), text=request.POST.get("text", ""))
    except services.QuizError as exc:
        return HttpResponse(f'<span class="pill bad">{exc}</span>', status=409)
    return HttpResponse('<span class="pill ok">Saved</span>')


@require_POST
@login_required
def finish(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    if attempt.status == Attempt.Status.IN_PROGRESS:
        services.finish_attempt(attempt)
        audit.record(request, "quiz_submitted", target=attempt.quiz.course.code, detail=f"{attempt.quiz.title} #{attempt.number}")
    return redirect("quizzes:result", attempt_id=attempt.pk)


@login_required
def result(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    if attempt.status == Attempt.Status.IN_PROGRESS:
        return redirect("quizzes:attempt", attempt_id=attempt.pk)
    quiz = attempt.quiz
    review = services.review_allowed(quiz, attempt)
    rows = []
    if review:
        saved = {a.question_id: a for a in attempt.answers.select_related("choice")}
        for q in quiz.questions.prefetch_related("choices"):
            a = saved.get(q.pk)
            rows.append({"q": q, "a": a, "correct": [c for c in q.choices.all() if c.is_correct]})
    total = quiz.total_marks
    percent = int(round(attempt.score / total * 100)) if attempt.status == "graded" and attempt.score is not None and total else None
    return render(request, "quizzes/result.html", {"attempt": attempt, "quiz": quiz, "review": review, "rows": rows, "total": total, "percent": percent})


# ------------------------------------------------------------------ staff side (/quiz-manager/)

@login_required
def manage_list(request):
    if request.user.role == "student":
        raise PermissionDenied
    quizzes = Quiz.objects.filter(course__in=perm.visible_courses_for(request.user)).select_related("course")
    return render(request, "quizzes/manage_list.html", {"quizzes": quizzes})


@login_required
def quiz_edit(request, course_id=None, pk=None):
    if pk:
        quiz = _quiz_for_staff(request, pk)
        course = quiz.course
    else:
        quiz, course = None, get_object_or_404(Course, pk=course_id)
        if not perm.can_manage(request.user, course):
            raise PermissionDenied
    form = QuizForm(request.POST or None, instance=quiz)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.course = course
        obj.save()
        audit.record(request, "quiz_saved", target=course.code, detail=obj.title)
        messages.success(request, "Quiz saved.")
        return redirect("quizzes:editor", pk=obj.pk)
    return render(request, "quizzes/quiz_form.html", {"form": form, "course": course, "quiz": quiz})


@login_required
def editor(request, pk):
    quiz = _quiz_for_staff(request, pk)
    return render(request, "quizzes/editor.html", {
        "quiz": quiz, "questions": quiz.questions.prefetch_related("choices"), "total": quiz.total_marks,
        "locked": quiz.attempts.exists(), "attempt_count": quiz.attempts.count(),
    })


@require_POST
@login_required
def quiz_action(request, pk, action):
    quiz = _quiz_for_staff(request, pk)
    if action == "toggle-visible":
        quiz.is_visible = not quiz.is_visible
    elif action == "toggle-enabled":
        quiz.is_enabled = not quiz.is_enabled
    elif action == "release-review":
        quiz.review_released = not quiz.review_released
    else:
        raise PermissionDenied
    quiz.save()
    from apps.messaging.services import safe_next

    return redirect(safe_next(request.POST.get("next", "")) or reverse("quizzes:editor", args=[quiz.pk]))


@login_required
def question_edit(request, pk=None, question_id=None):
    if question_id:
        question = get_object_or_404(Question.objects.select_related("quiz__course"), pk=question_id)
        quiz = question.quiz
    else:
        question, quiz = None, _quiz_for_staff(request, pk)
    if not perm.can_manage(request.user, quiz.course):
        raise PermissionDenied
    if quiz.attempts.exists():
        messages.error(request, "Students have already started this quiz, so its questions can no longer be changed.")
        return redirect("quizzes:editor", pk=quiz.pk)
    form = QuestionForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        form.save_with_choices(quiz)
        messages.success(request, "Question saved.")
        return redirect("quizzes:editor", pk=quiz.pk)
    return render(request, "quizzes/question_form.html", {"form": form, "quiz": quiz, "question": question})


@require_POST
@login_required
def question_delete(request, question_id):
    question = get_object_or_404(Question.objects.select_related("quiz__course"), pk=question_id)
    if not perm.can_manage(request.user, question.quiz.course):
        raise PermissionDenied
    if question.quiz.attempts.exists():
        messages.error(request, "Students have already started this quiz, so its questions can no longer be changed.")
    else:
        question.delete()
        messages.success(request, "Question deleted.")
    return redirect("quizzes:editor", pk=question.quiz_id)


@login_required
def attempts_list(request, pk):
    quiz = _quiz_for_staff(request, pk)
    services.expire_overdue()
    attempts = list(quiz.attempts.select_related("student"))
    total = quiz.total_marks
    marked = [a for a in attempts if a.status == "graded" and a.score is not None]
    pcts = [a.score / total * 100 for a in marked] if total else []
    waiting = Answer.objects.filter(attempt__quiz=quiz, attempt__status=Attempt.Status.SUBMITTED, awarded__isnull=True).count()
    stats = {"students": len({a.student_id for a in attempts if a.status != "in_progress"}), "enrolled": quiz.course.enrolments.filter(status="active").count(),
             "average": round(sum(pcts) / len(pcts)) if pcts else None, "highest": round(max(pcts)) if pcts else None,
             "needs": sum(1 for a in attempts if a.status == "submitted"), "waiting": waiting}
    return render(request, "quizzes/attempts.html", {"quiz": quiz, "attempts": attempts, "total": total, "stats": stats})


@login_required
def grade_attempt(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("quiz__course", "student"), pk=attempt_id)
    quiz = attempt.quiz
    if not perm.can_manage(request.user, quiz.course):
        raise PermissionDenied
    if attempt.status == Attempt.Status.IN_PROGRESS:
        messages.error(request, "This attempt is still in progress.")
        return redirect("quizzes:attempts", pk=quiz.pk)
    answers = list(attempt.answers.select_related("question", "choice").filter(question__quiz=quiz))
    if request.method == "POST":
        marks, notes, errors = {}, {}, []
        for a in answers:
            raw = request.POST.get(f"mark_{a.pk}", "").strip()
            if raw == "":
                continue
            try:
                m = Decimal(raw)
            except InvalidOperation:
                errors.append(f"“{raw}” is not a number.")
                continue
            if m < 0 or m > a.question.marks:
                errors.append(f"A mark must be between 0 and {a.question.marks:g}.")
                continue
            marks[a.pk] = m
            notes[a.pk] = request.POST.get(f"note_{a.pk}", "")[:300]
        if errors:
            for e in dict.fromkeys(errors):
                messages.error(request, e)
        else:
            services.manual_grade(attempt, marks, notes)
            audit.record(request, "quiz_graded", target=quiz.course.code, detail=f"{quiz.title}: {attempt.student.username}")
            messages.success(request, "Marks saved.")
            return redirect("quizzes:attempts", pk=quiz.pk)
    return render(request, "quizzes/grade.html", {"attempt": attempt, "quiz": quiz, "answers": answers, "total": quiz.total_marks})


@require_POST
@login_required
def regrade_attempt(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("quiz__course", "student"), pk=attempt_id)
    if not perm.can_manage(request.user, attempt.quiz.course):
        raise PermissionDenied
    if attempt.status == Attempt.Status.IN_PROGRESS:
        messages.error(request, "This attempt is still in progress.")
    else:
        services.regrade(attempt)
        audit.record(request, "quiz_regraded", target=attempt.quiz.course.code, detail=f"{attempt.quiz.title}: {attempt.student.username}")
        messages.success(request, "Automatic marks recalculated.")
    return redirect("quizzes:attempts", pk=attempt.quiz_id)


@require_POST
@login_required
def reset_attempt(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("quiz__course", "student"), pk=attempt_id)
    if not perm.can_manage(request.user, attempt.quiz.course):
        raise PermissionDenied
    audit.record(request, "quiz_attempt_reset", target=attempt.quiz.course.code, detail=f"{attempt.quiz.title}: {attempt.student.username} attempt {attempt.number}")
    attempt.delete()
    messages.success(request, "Attempt removed. The student can try again if attempts remain.")
    return redirect("quizzes:attempts", pk=attempt.quiz_id)


@login_required
def marking(request, pk):
    """Mark one question at a time across every student (written answers waiting for the lecturer)."""
    quiz = _quiz_for_staff(request, pk)
    waiting = Answer.objects.filter(attempt__quiz=quiz, attempt__status=Attempt.Status.SUBMITTED, question__quiz=quiz).select_related("question", "attempt__student")
    qids = list(dict.fromkeys(waiting.filter(awarded__isnull=True).order_by("question__position", "question_id").values_list("question_id", flat=True)))
    picked = request.GET.get("q", "")
    qid = int(picked) if picked.isdigit() else (qids[0] if qids else None)
    question = quiz.questions.filter(pk=qid).first() if qid else None
    answers = list(waiting.filter(question=question).order_by("attempt__student__first_name", "attempt__student__username")) if question else []
    if request.method == "POST" and question:
        marks, errors = {}, []
        for a in answers:
            raw = request.POST.get(f"mark_{a.pk}", "").strip()
            if raw == "":
                continue
            try:
                m = Decimal(raw)
            except InvalidOperation:
                errors.append(f"“{raw}” is not a number.")
                continue
            if m < 0 or m > question.marks:
                errors.append(f"A mark must be between 0 and {question.marks:g}.")
                continue
            marks[a.pk] = m
        if errors:
            for e in dict.fromkeys(errors):
                messages.error(request, e)
        else:
            for a in answers:
                if a.pk in marks:
                    services.manual_grade(a.attempt, {a.pk: marks[a.pk]})
            audit.record(request, "quiz_graded", target=quiz.course.code, detail=f"{quiz.title}: question {question.position + 1}, {len(marks)} marked")
            messages.success(request, f"{len(marks)} mark{'s' if len(marks) != 1 else ''} saved.")
            later = [i for i in qids if i != question.pk]
            return redirect(f"{reverse('quizzes:marking', args=[quiz.pk])}?q={later[0]}" if later else reverse("quizzes:attempts", args=[quiz.pk]))
    number = list(quiz.questions.values_list("pk", flat=True)).index(question.pk) + 1 if question else None
    return render(request, "quizzes/marking.html", {"quiz": quiz, "question": question, "number": number, "answers": answers, "left": waiting.filter(awarded__isnull=True).count(), "qids": qids})
