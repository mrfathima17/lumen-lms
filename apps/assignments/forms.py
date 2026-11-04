from django import forms

from .models import Assignment, Extension, Submission

DT = "%Y-%m-%dT%H:%M"


class AssignmentForm(forms.ModelForm):
    due_at = forms.DateTimeField(label="Due date and time", input_formats=[DT], widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT))

    class Meta:
        model = Assignment
        fields = ["title", "topic", "description", "due_at", "max_mark", "allowed_types", "max_file_mb", "allow_late", "is_visible"]
        labels = {"description": "Instructions"}
        widgets = {"description": forms.Textarea(attrs={"rows": 6}), "allowed_types": forms.TextInput(attrs={"placeholder": "pdf, docx, zip"})}

    def __init__(self, *args, course, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = course.topics.all()
        self.fields["topic"].required = False
        self.fields["max_file_mb"].required = False

    def clean_allowed_types(self):
        from django.conf import settings
        raw = self.cleaned_data.get("allowed_types", "")
        exts = [e.strip().lstrip(".").lower() for e in raw.replace(";", ",").split(",") if e.strip()]
        bad = [e for e in exts if e not in settings.ALLOWED_UPLOAD_EXTENSIONS]
        if bad:
            raise forms.ValidationError("Not a supported file type: " + ", ".join(bad) + ".")
        return ", ".join(exts)

    def clean_max_file_mb(self):
        from django.conf import settings
        m = self.cleaned_data.get("max_file_mb") or settings.MAX_UPLOAD_MB
        if not 1 <= m <= settings.MAX_UPLOAD_MB:
            raise forms.ValidationError(f"Choose a size between 1 and {settings.MAX_UPLOAD_MB} MB.")
        return m

    def clean_max_mark(self):
        m = self.cleaned_data["max_mark"]
        if m <= 0:
            raise forms.ValidationError("The maximum mark must be above zero.")
        return m


class SubmissionForm(forms.ModelForm):
    own_work = forms.BooleanField(label="I confirm this is my own work.", error_messages={"required": "Tick the box to confirm this is your own work."})

    class Meta:
        model = Submission
        fields = ["file", "comment"]
        labels = {"file": "Your file", "comment": "Comments to lecturer (optional)"}
        widgets = {"comment": forms.Textarea(attrs={"rows": 3, "placeholder": "Anything you'd like to add…"})}

    def __init__(self, *args, assignment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignment = assignment

    def clean_file(self):
        f = self.cleaned_data["file"]
        a = self.assignment
        if a is not None:
            import os
            ext = os.path.splitext(f.name)[1].lstrip(".").lower()
            if a.allowed_extensions and ext not in a.allowed_extensions:
                raise forms.ValidationError("This assignment accepts only: " + ", ".join(a.allowed_extensions).upper() + ".")
            if f.size > a.max_file_mb * 1024 * 1024:
                raise forms.ValidationError(f"The file is larger than {a.max_file_mb} MB.")
        return f


class GradeForm(forms.Form):
    raw_mark = forms.DecimalField(label="Mark", max_digits=6, decimal_places=2, min_value=0)
    feedback = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, max_mark, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_mark = max_mark
        self.fields["raw_mark"].help_text = f"Out of {max_mark:g}"

    def clean_raw_mark(self):
        m = self.cleaned_data["raw_mark"]
        if m > self.max_mark:
            raise forms.ValidationError(f"The mark cannot be above {self.max_mark:g}.")
        return m


class ExtensionForm(forms.ModelForm):
    due_at = forms.DateTimeField(label="New due date and time", input_formats=[DT], widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT))

    class Meta:
        model = Extension
        fields = ["student", "due_at"]

    def __init__(self, *args, assignment, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignment = assignment
        self.fields["student"].queryset = assignment.course.enrolments.none()
        from django.contrib.auth import get_user_model

        self.fields["student"].queryset = get_user_model().objects.filter(enrolments__course=assignment.course, role="student").distinct()
        self.fields["student"].label_from_instance = lambda u: u.get_full_name() or u.username

    def clean_due_at(self):
        d = self.cleaned_data["due_at"]
        if d <= self.assignment.due_at:
            raise forms.ValidationError("An extension must be later than the original due date.")
        return d


class CriterionForm(forms.Form):
    title = forms.CharField(max_length=150)
    description = forms.CharField(max_length=300, required=False, help_text="What this row looks at.")
    levels = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "Excellent | 10 | Clear, complete and correct\nGood | 7 | Minor gaps\nWeak | 3 | Major gaps\nMissing | 0"}),
        help_text="One level per line: label | points | description (the description is optional). Between 2 and 6 levels.")
    position = forms.IntegerField(required=False, min_value=0, max_value=99, label="Order", help_text="Lower numbers come first. Leave empty to add at the end.")

    def clean_levels(self):
        from . import rubric

        levels, error = rubric.parse_levels(self.cleaned_data["levels"])
        if error:
            raise forms.ValidationError(error)
        self.parsed_levels = levels
        return self.cleaned_data["levels"]
