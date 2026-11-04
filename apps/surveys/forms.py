from django import forms

from apps.quizzes.forms import _dt

from .models import Survey, SurveyQuestion


class SurveyForm(forms.ModelForm):
    poll_question = forms.CharField(label="Poll question", max_length=300, required=False, help_text="Polls only. Surveys get their questions in the builder after you create them.")
    poll_options = forms.CharField(label="Options (one per line)", required=False, widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Tuesday 10:00 AM\nThursday 2:00 PM"}))
    opens_at = _dt("Opens")
    closes_at = _dt("Closes")

    class Meta:
        model = Survey
        fields = ["kind", "title", "description", "opens_at", "closes_at", "anonymous", "show_results", "is_visible"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        locked = kwargs.pop("locked", False)
        super().__init__(*args, **kwargs)
        if locked:  # answers exist: the rules they were given under must not change
            self.fields["anonymous"].disabled = True
            self.fields["kind"].disabled = True

    def clean(self):
        data = super().clean()
        o, c = data.get("opens_at"), data.get("closes_at")
        if o and c and c <= o:
            self.add_error("closes_at", "It must close after it opens.")
        q, opts = (data.get("poll_question") or "").strip(), self.poll_option_list(data)
        if self.instance.pk is None and (q or opts):
            if data.get("kind") != "poll":
                self.add_error("poll_question", "Only polls take a question here. Add survey questions in the builder.")
            elif not q:
                self.add_error("poll_question", "Enter the question.")
            elif len(opts) < 2:
                self.add_error("poll_options", "Give at least two options, one per line.")
        if data.get("kind") == "poll" and self.instance.pk and self.instance.questions.count() > 1:
            self.add_error("kind", "A poll has one question. Remove the extra questions first.")
        return data


    @staticmethod
    def poll_option_list(data):
        return list(dict.fromkeys(o.strip() for o in (data.get("poll_options") or "").splitlines() if o.strip()))


class QuestionForm(forms.ModelForm):
    class Meta:
        model = SurveyQuestion
        fields = ["text", "kind", "required", "choices"]
        widgets = {"choices": forms.Textarea(attrs={"rows": 5})}

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        if kind in ("single", "multiple"):
            lines = [c.strip() for c in (data.get("choices") or "").splitlines() if c.strip()]
            if len(lines) < 2:
                self.add_error("choices", "Give at least two choices, one per line.")
            elif len(lines) > 12 or any(len(c) > 200 for c in lines) or len(set(lines)) != len(lines):
                self.add_error("choices", "Use at most 12 different choices of up to 200 characters.")
            else:
                data["choices"] = "\n".join(lines)
        else:
            data["choices"] = ""
        return data
