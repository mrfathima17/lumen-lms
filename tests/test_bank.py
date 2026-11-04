import io

import pytest
from django.test import Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.quizzes import bank
from apps.quizzes.models import Attempt, BankQuestion, Quiz, Question
from django.utils import timezone


def as_user(u):
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def quiz(course):
    return Quiz.objects.create(course=course, title="Midterm")


CSV = bank.TEMPLATE


def test_import_preview_then_confirm(lecturer, course):
    c = as_user(lecturer)
    r = c.post(reverse("quizzes:bank-import", args=[course.pk]), {"file": SimpleUploadedFile("q.csv", CSV.encode())})
    assert r.status_code == 200 and b"4</b><span>Rows" in r.content and BankQuestion.objects.count() == 0
    c.post(reverse("quizzes:bank-import-confirm", args=[course.pk]), {"text": CSV})
    assert BankQuestion.objects.count() == 4
    mcq = BankQuestion.objects.get(kind="mcq")
    assert mcq.choices[1] == {"text": "2NF", "correct": True} and mcq.category == "Normalisation"
    assert BankQuestion.objects.get(kind="short").accepted_answers == "Structured Query Language\nstructured query language"


def test_bad_rows_are_skipped_and_explained():
    raw = "kind,text,marks,choice1,choice2,correct\nmcq,Q1,1,a,,1\nmcq,Q2,0,a,b,3\ntf,Q3,1,,,maybe\nfoo,,1,,,\nmcq,Good,1,a,b,2\n"
    rows, err = bank.parse(raw)
    assert err is None and [bool(r["errors"]) for r in rows] == [True, True, True, True, False]
    assert any("two choices" in e for e in rows[0]["errors"]) and any("marks" in e for e in rows[1]["errors"])


def test_file_problems():
    assert bank.parse(b"\xff\xfe")[1] and bank.parse("a,b\n1,2\n")[1] and bank.parse("")[1]
    assert bank.parse("kind,text\n")[1] == "The file has no questions."
    assert bank.parse(b"x" * (bank.MAX_BYTES + 1))[1]


def test_confirm_revalidates(lecturer, course):
    as_user(lecturer).post(reverse("quizzes:bank-import-confirm", args=[course.pk]), {"text": "kind,text,correct\nmcq,Tampered,9\ntf,Fine,true\n"})
    assert list(BankQuestion.objects.values_list("text", flat=True)) == ["Fine"]


def test_add_to_quiz_copies_independently(lecturer, course, quiz):
    c = as_user(lecturer)
    c.post(reverse("quizzes:bank-import-confirm", args=[course.pk]), {"text": CSV})
    ids = [BankQuestion.objects.get(kind="mcq").pk, BankQuestion.objects.get(kind="tf").pk]
    r = c.post(reverse("quizzes:bank-add-to-quiz", args=[course.pk]), {"quiz": quiz.pk, "pick": ids})
    assert r.status_code == 302 and quiz.questions.count() == 2
    q = quiz.questions.get(kind="mcq")
    assert q.choices.count() == 4 and q.choices.filter(is_correct=True).get().text == "2NF"
    BankQuestion.objects.filter(pk=ids[0]).update(text="changed")
    assert Question.objects.get(pk=q.pk).text != "changed"


def test_locked_quiz_refuses(lecturer, enrolled, course, quiz):
    Attempt.objects.create(quiz=quiz, student=enrolled, started_at=timezone.now())
    bq = BankQuestion.objects.create(course=course, kind="essay", text="Why?")
    as_user(lecturer).post(reverse("quizzes:bank-add-to-quiz", args=[course.pk]), {"quiz": quiz.pk, "pick": [bq.pk]})
    assert quiz.questions.count() == 0


def test_quiz_question_to_bank_and_round_trip(lecturer, course, quiz):
    c = as_user(lecturer)
    c.post(reverse("quizzes:question-new", args=[quiz.pk]), {"kind": "mcq", "text": "=SUM(A1)", "marks": "2", "choice_1": "a", "choice_2": "b", "correct": "2"})
    q = quiz.questions.get()
    c.post(reverse("quizzes:question-to-bank", args=[q.pk]))
    bq = BankQuestion.objects.get()
    assert bq.choices == [{"text": "a", "correct": False}, {"text": "b", "correct": True}]
    body = c.get(reverse("quizzes:bank-export", args=[course.pk])).content.decode()
    assert "'=SUM(A1)" in body
    rows, _ = bank.parse(body.replace("'=SUM", "=SUM"))
    assert not rows[0]["errors"] and rows[0]["data"]["choices"][1]["correct"]


def test_bank_form_crud_and_search(lecturer, course):
    c = as_user(lecturer)
    r = c.post(reverse("quizzes:bank-new", args=[course.pk]), {"category": "Keys", "kind": "tf", "text": "PKs are unique.", "marks": "1", "tf_correct": "true"})
    assert r.status_code == 302
    bq = BankQuestion.objects.get()
    c.post(reverse("quizzes:bank-edit", args=[bq.pk]), {"category": "Keys", "kind": "tf", "text": "PKs are unique!", "marks": "1", "tf_correct": "false"})
    bq.refresh_from_db()
    assert bq.text.endswith("!") and bq.choices[1]["correct"]
    assert b"PKs are unique!" in c.get(reverse("quizzes:bank-list", args=[course.pk]) + "?q=unique").content
    assert b"PKs are unique!" not in c.get(reverse("quizzes:bank-list", args=[course.pk]) + "?q=zzz").content
    bad = c.post(reverse("quizzes:bank-new", args=[course.pk]), {"kind": "mcq", "text": "x", "marks": "1"})
    assert bad.status_code == 200 and BankQuestion.objects.count() == 1
    c.post(reverse("quizzes:bank-delete", args=[bq.pk]))
    assert not BankQuestion.objects.exists()


def test_permissions(enrolled, course, make_user):
    bq = BankQuestion.objects.create(course=course, kind="essay", text="Secret")
    s = as_user(enrolled)
    for name, args in [("quizzes:bank-list-all", []), ("quizzes:bank-list", [course.pk]), ("quizzes:bank-edit", [bq.pk]), ("quizzes:bank-export", [course.pk]), ("quizzes:bank-import", [course.pk])]:
        assert s.get(reverse(name, args=args)).status_code == 403
    other = as_user(make_user("lect2", "lecturer"))
    assert other.get(reverse("quizzes:bank-list", args=[course.pk])).status_code == 403
    assert other.post(reverse("quizzes:bank-delete", args=[bq.pk])).status_code == 403 and BankQuestion.objects.exists()
