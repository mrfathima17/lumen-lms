from django import forms

from .models import Category, Course, Group, Topic


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["code", "title", "summary", "department", "semester", "credits", "lecturers", "is_visible", "allow_self_enrol", "enrol_key"]
        widgets = {"summary": forms.Textarea(attrs={"rows": 3}), "lecturers": forms.CheckboxSelectMultiple}

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()

    def clean_credits(self):
        c = self.cleaned_data["credits"]
        if not 1 <= c <= 30:
            raise forms.ValidationError("Credits must be between 1 and 30.")
        return c


class CategoryForm(forms.ModelForm):
    """Add or edit a faculty, department or semester. The kind is fixed once it exists."""

    class Meta:
        model = Category
        fields = ["name", "kind", "faculty", "start_date", "end_date"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        labels = {"start_date": "Starts", "end_date": "Ends"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["kind"].disabled = True
        self.fields["faculty"].queryset = Category.objects.filter(kind="faculty")
        self.fields["faculty"].empty_label = "No faculty"
        kind = self.instance.kind if self.instance.pk else (self.data.get("kind") if self.is_bound else self.initial.get("kind"))
        self.fields["name"].widget.attrs.update({"placeholder": f"New {kind} name" if kind in ("faculty", "department", "semester") and not self.instance.pk else "", "autocomplete": "off"})
        for key, label in (("faculty", "Faculty"), ("start_date", "Start date"), ("end_date", "End date")):
            self.fields[key].widget.attrs["aria-label"] = label

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean(self):
        data = super().clean()
        kind = data.get("kind") or self.instance.kind
        if kind != "department":
            data["faculty"] = None
        if kind != "semester":
            data["start_date"] = data["end_date"] = None
        else:
            start, end = data.get("start_date"), data.get("end_date")
            if bool(start) != bool(end):
                self.add_error("end_date" if start else "start_date", "Give both dates, or leave both empty.")
            elif start and end and end < start:
                self.add_error("end_date", "The end date must be after the start date.")
        name = data.get("name")
        if name and kind:
            clash = Category.objects.filter(kind=kind, name__iexact=name).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("name", f"A {Category.Kind(kind).label.lower()} called \u201c{name}\u201d already exists.")
        return data


class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ["title", "summary"]
        widgets = {"summary": forms.Textarea(attrs={"rows": 2})}


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name"]


class BulkEnrolForm(forms.Form):
    identifiers = forms.CharField(label="Usernames or index numbers", widget=forms.Textarea(attrs={"rows": 5, "placeholder": "One per line, or separated by commas"}))


class SelfEnrolForm(forms.Form):
    key = forms.CharField(required=False, label="Enrolment key")


class CourseSettingsForm(forms.ModelForm):
    """What a lecturer may change about their own course. Code, department, semester and lecturers stay with administrators."""

    class Meta:
        model = Course
        fields = ["title", "summary", "credits", "is_visible", "allow_self_enrol", "enrol_key"]
        widgets = {"summary": forms.Textarea(attrs={"rows": 3})}
        labels = {"is_visible": "Course visible to students", "allow_self_enrol": "Students can enrol themselves"}

    clean_credits = CourseForm.clean_credits
