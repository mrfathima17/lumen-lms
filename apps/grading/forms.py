from django import forms

from apps.assignments.models import Assignment
from apps.quizzes.models import Quiz

from .models import GradeItem


class GradeItemForm(forms.ModelForm):
    """Add a component: pick an assignment or quiz of this course, or create a manual one such as an exam."""
    assignment = forms.ModelChoiceField(queryset=Assignment.objects.none(), required=False, empty_label="—")
    quiz = forms.ModelChoiceField(queryset=Quiz.objects.none(), required=False, empty_label="—")

    class Meta:
        model = GradeItem
        fields = ["kind", "assignment", "quiz", "title", "max_mark", "weight"]

    def __init__(self, *args, course, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course
        used_a = GradeItem.objects.filter(assignment__isnull=False).values("assignment_id")
        used_q = GradeItem.objects.filter(quiz__isnull=False).values("quiz_id")
        self.fields["assignment"].queryset = Assignment.objects.filter(course=course).exclude(pk__in=used_a)
        self.fields["quiz"].queryset = Quiz.objects.filter(course=course).exclude(pk__in=used_q)
        self.fields["title"].required = False
        self.fields["title"].help_text = "Leave empty to use the assignment or quiz title."
        self.fields["max_mark"].help_text = "Manual items only: the mark that counts as 100%."

    def clean_weight(self):
        w = self.cleaned_data["weight"]
        if w <= 0 or w > 100:
            raise forms.ValidationError("Weight must be above 0 and at most 100.")
        return w

    def clean(self):
        d = super().clean()
        kind = d.get("kind")
        if kind == GradeItem.Kind.ASSIGNMENT:
            if not d.get("assignment"):
                self.add_error("assignment", "Choose an assignment.")
            else:
                d["title"] = d.get("title") or d["assignment"].title
            d["quiz"], d["max_mark"] = None, None
        elif kind == GradeItem.Kind.QUIZ:
            if not d.get("quiz"):
                self.add_error("quiz", "Choose a quiz.")
            else:
                d["title"] = d.get("title") or d["quiz"].title
            d["assignment"], d["max_mark"] = None, None
        elif kind == GradeItem.Kind.MANUAL:
            d["assignment"], d["quiz"] = None, None
            if not d.get("title"):
                self.add_error("title", "Give the item a title.")
            if not d.get("max_mark") or d["max_mark"] <= 0:
                self.add_error("max_mark", "Enter the maximum mark.")
        return d

    def save(self, commit=True):
        obj = super().save(commit=False)
        d = self.cleaned_data
        obj.course, obj.title = self.course, d["title"]
        obj.assignment, obj.quiz, obj.max_mark = d.get("assignment"), d.get("quiz"), d.get("max_mark")
        if not obj.pk:
            last = self.course.grade_items.order_by("-position").first()
            obj.position = last.position + 1 if last else 0
        if commit:
            obj.save()
        return obj


class WeightForm(forms.ModelForm):
    class Meta:
        model = GradeItem
        fields = ["title", "weight"]

    def clean_weight(self):
        w = self.cleaned_data["weight"]
        if w <= 0 or w > 100:
            raise forms.ValidationError("Weight must be above 0 and at most 100.")
        return w
