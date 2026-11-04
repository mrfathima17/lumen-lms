"""Question bank: copying between bank and quizzes, and CSV import and export."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.core.exports import safe_cell

from .models import BankQuestion, Choice, Question

MAX_BYTES = 1_000_000
MAX_ROWS = 500
COLUMNS = ["category", "kind", "text", "marks", "choice1", "choice2", "choice3", "choice4", "correct", "accepted"]
KINDS = {"mcq": Question.Kind.MCQ, "tf": Question.Kind.TF, "short": Question.Kind.SHORT, "essay": Question.Kind.ESSAY}


def to_quiz(bq, quiz):
    """Copy a bank question into a quiz as a new, independent question."""
    last = quiz.questions.order_by("-position").first()
    q = Question.objects.create(quiz=quiz, kind=bq.kind, text=bq.text, marks=bq.marks, position=last.position + 1 if last else 0,
                                accepted_answers=bq.accepted_answers if bq.kind == Question.Kind.SHORT else "")
    for i, c in enumerate(bq.choices or []):
        Choice.objects.create(question=q, text=c["text"], is_correct=bool(c["correct"]), position=i)
    return q


@transaction.atomic
def add_to_quiz(bank_questions, quiz):
    return [to_quiz(b, quiz) for b in bank_questions]


def from_quiz(question, course):
    return BankQuestion.objects.create(
        course=course, kind=question.kind, text=question.text, marks=question.marks,
        accepted_answers=question.accepted_answers, choices=[{"text": c.text, "correct": c.is_correct} for c in question.choices.all()])


def parse(raw):
    """raw: bytes or str. Returns (rows, error); each row has line, data (BankQuestion fields) and errors."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            return [], "The file is larger than 1 MB."
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return [], "The file is not UTF-8 text. Save it as CSV (UTF-8) and try again."
    elif len(raw.encode()) > MAX_BYTES:
        return [], "The file is larger than 1 MB."
    reader = csv.DictReader(io.StringIO(raw.lstrip("﻿")))
    if not reader.fieldnames:
        return [], "The file is empty."
    reader.fieldnames = [(h or "").strip().lower() for h in reader.fieldnames]
    if "text" not in reader.fieldnames or "kind" not in reader.fieldnames:
        return [], "The first row must be a header containing at least: kind, text."
    rows = []
    for line, r in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            return [], f"At most {MAX_ROWS} questions can be imported at once."
        r = {k: (v or "").strip() for k, v in r.items() if isinstance(k, str) and isinstance(v, (str, type(None)))}
        if not any(r.values()):
            continue
        rows.append(_check(line, r))
    if not rows:
        return [], "The file has no questions."
    return rows, None


def _check(line, r):
    errors = []
    kind = KINDS.get(r.get("kind", "").lower())
    text = r.get("text", "")
    if not kind:
        errors.append("kind must be mcq, tf, short or essay")
    if not text:
        errors.append("text is empty")
    try:
        marks = Decimal(r.get("marks") or "1")
        if marks <= 0 or marks > 1000:
            raise InvalidOperation
    except InvalidOperation:
        marks = Decimal("1")
        errors.append("marks must be a number above zero")
    choices, accepted = [], ""
    correct = r.get("correct", "").lower()
    if kind == Question.Kind.MCQ:
        texts = [r.get(f"choice{i}", "") for i in range(1, 5)]
        if any(len(t) > 300 for t in texts):
            errors.append("a choice is longer than 300 characters")
        if sum(1 for t in texts if t) < 2:
            errors.append("give at least two choices")
        if correct not in {"1", "2", "3", "4"}:
            errors.append("correct must be 1, 2, 3 or 4")
        elif not texts[int(correct) - 1]:
            errors.append("the correct choice is empty")
        else:
            choices = [{"text": t, "correct": str(i) == correct} for i, t in enumerate(texts, start=1) if t]
    elif kind == Question.Kind.TF:
        if correct not in ("true", "false"):
            errors.append("correct must be true or false")
        else:
            choices = [{"text": "True", "correct": correct == "true"}, {"text": "False", "correct": correct == "false"}]
    elif kind == Question.Kind.SHORT:
        accepted = "\n".join(a.strip() for a in r.get("accepted", "").split("|") if a.strip())
    data = {"category": r.get("category", "")[:80], "kind": kind or "", "text": text, "marks": marks, "accepted_answers": accepted, "choices": choices}
    return {"line": line, "data": data, "errors": errors}


@transaction.atomic
def import_rows(rows, course):
    made = [BankQuestion(course=course, **r["data"]) for r in rows if not r["errors"]]
    BankQuestion.objects.bulk_create(made)
    return len(made)


def export_csv(questions, fileobj):
    w = csv.writer(fileobj)
    w.writerow(COLUMNS)
    for q in questions:
        ch = q.choices or []
        texts = [c["text"] for c in ch] + [""] * 4
        if q.kind == Question.Kind.MCQ:
            correct = next((str(i + 1) for i, c in enumerate(ch) if c["correct"]), "")
        elif q.kind == Question.Kind.TF:
            correct = "true" if any(c["correct"] and c["text"] == "True" for c in ch) else "false"
        else:
            correct = ""
        w.writerow([safe_cell(q.category), q.kind, safe_cell(q.text), format(q.marks.normalize(), "f"),
                    *([safe_cell(t) for t in texts[:4]] if q.kind == Question.Kind.MCQ else ["", "", "", ""]), correct,
                    safe_cell("|".join(q.accepted_answers.splitlines()))])


TEMPLATE = (
    "category,kind,text,marks,choice1,choice2,choice3,choice4,correct,accepted\n"
    "Normalisation,mcq,Which normal form removes partial dependencies?,2,1NF,2NF,3NF,BCNF,2,\n"
    "Keys,tf,A primary key may contain NULL.,1,,,,,false,\n"
    "Keys,short,What does SQL stand for?,1,,,,,,Structured Query Language|structured query language\n"
    "Design,essay,Explain the purpose of an ER diagram.,5,,,,,,\n"
)
