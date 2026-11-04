from django import forms
from django.db import transaction

from .models import BankQuestion, Choice, Question, Quiz

DT = "%Y-%m-%dT%H:%M"


def _dt(label, required=False):
    return forms.DateTimeField(label=label, required=required, input_formats=[DT], widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT))


class QuizForm(forms.ModelForm):
    opens_at = _dt("Opens")
    closes_at = _dt("Closes")

    class Meta:
        model = Quiz
        fields = ["title", "description", "time_limit_minutes", "opens_at", "closes_at", "max_attempts", "review_policy", "is_visible", "is_enabled"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        data = super().clean()
        o, c = data.get("opens_at"), data.get("closes_at")
        if o and c and c <= o:
            self.add_error("closes_at", "The quiz must close after it opens.")
        if data.get("max_attempts") is not None and not 1 <= data["max_attempts"] <= 20:
            self.add_error("max_attempts", "Attempts must be between 1 and 20.")
        t = data.get("time_limit_minutes")
        if t is not None and not 1 <= t <= 600:
            self.add_error("time_limit_minutes", "The time limit must be between 1 and 600 minutes.")
        return data


class QuestionForm(forms.ModelForm):
    """One form for all question kinds: four choice boxes for multiple choice, a True/False pick, or accepted answers."""
    choice_1 = forms.CharField(required=False, label="Choice 1", max_length=300)
    choice_2 = forms.CharField(required=False, label="Choice 2", max_length=300)
    choice_3 = forms.CharField(required=False, label="Choice 3", max_length=300)
    choice_4 = forms.CharField(required=False, label="Choice 4", max_length=300)
    correct = forms.ChoiceField(required=False, label="Correct choice", choices=[("", "—"), ("1", "Choice 1"), ("2", "Choice 2"), ("3", "Choice 3"), ("4", "Choice 4")])
    tf_correct = forms.ChoiceField(required=False, label="Correct answer (true or false)", choices=[("", "—"), ("true", "True"), ("false", "False")])

    class Meta:
        model = Question
        fields = ["kind", "text", "marks", "accepted_answers"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3}), "accepted_answers": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        q = self.instance
        if q.pk:
            choices = list(q.choices.all())
            for i, c in enumerate(choices[:4], start=1):
                self.fields[f"choice_{i}"].initial = c.text
                if c.is_correct:
                    self.fields["correct"].initial = str(i)
                    if q.kind == Question.Kind.TF:
                        self.fields["tf_correct"].initial = "true" if c.text == "True" else "false"

    def clean_marks(self):
        m = self.cleaned_data["marks"]
        if m <= 0 or m > 1000:
            raise forms.ValidationError("Marks must be above zero.")
        return m

    def clean(self):
        d = super().clean()
        kind = d.get("kind")
        if kind == Question.Kind.MCQ:
            texts = [d.get(f"choice_{i}", "").strip() for i in range(1, 5)]
            filled = [t for t in texts if t]
            if len(filled) < 2:
                self.add_error("choice_2", "Give at least two choices.")
            if not d.get("correct"):
                self.add_error("correct", "Pick the correct choice.")
            elif not texts[int(d["correct"]) - 1]:
                self.add_error("correct", "The correct choice cannot be empty.")
        elif kind == Question.Kind.TF and not d.get("tf_correct"):
            self.add_error("tf_correct", "Pick the correct answer.")
        return d

    @transaction.atomic
    def save_with_choices(self, quiz):
        q = super().save(commit=False)
        q.quiz = quiz
        if not q.pk:
            last = quiz.questions.order_by("-position").first()
            q.position = last.position + 1 if last else 0
        if q.kind != Question.Kind.SHORT:
            q.accepted_answers = ""
        q.save()
        q.choices.all().delete()
        d = self.cleaned_data
        if q.kind == Question.Kind.MCQ:
            pos = 0
            for i in range(1, 5):
                text = d.get(f"choice_{i}", "").strip()
                if text:
                    Choice.objects.create(question=q, text=text, is_correct=str(i) == d["correct"], position=pos)
                    pos += 1
        elif q.kind == Question.Kind.TF:
            Choice.objects.create(question=q, text="True", is_correct=d["tf_correct"] == "true", position=0)
            Choice.objects.create(question=q, text="False", is_correct=d["tf_correct"] == "false", position=1)
        return q


class BankQuestionForm(QuestionForm):
    """Same fields and checks as a quiz question, plus a topic label; stores choices in the bank row."""

    class Meta:
        model = BankQuestion
        fields = ["category", "kind", "text", "marks", "accepted_answers"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3}), "accepted_answers": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        forms.ModelForm.__init__(self, *args, **kwargs)
        q = self.instance
        if q.pk:
            for i, c in enumerate((q.choices or [])[:4], start=1):
                self.fields[f"choice_{i}"].initial = c["text"]
                if c["correct"]:
                    self.fields["correct"].initial = str(i)
                    if q.kind == Question.Kind.TF:
                        self.fields["tf_correct"].initial = "true" if c["text"] == "True" else "false"

    def save_bank(self, course):
        q = forms.ModelForm.save(self, commit=False)
        q.course = course
        d = self.cleaned_data
        if q.kind != Question.Kind.SHORT:
            q.accepted_answers = ""
        if q.kind == Question.Kind.MCQ:
            q.choices = [{"text": d[f"choice_{i}"].strip(), "correct": str(i) == d["correct"]} for i in range(1, 5) if d.get(f"choice_{i}", "").strip()]
        elif q.kind == Question.Kind.TF:
            q.choices = [{"text": "True", "correct": d["tf_correct"] == "true"}, {"text": "False", "correct": d["tf_correct"] == "false"}]
        else:
            q.choices = []
        q.save()
        return q
