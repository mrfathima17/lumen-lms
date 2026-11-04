from django import forms

from apps.courses import permissions as perm

from .models import Event, TimetableSlot, TodoItem

DT = "%Y-%m-%dT%H:%M"


class EventForm(forms.ModelForm):
    starts_at = forms.DateTimeField(label="Starts", input_formats=[DT], widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT))
    ends_at = forms.DateTimeField(label="Ends (optional)", required=False, input_formats=[DT], widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT))
    course = forms.ModelChoiceField(label="Share with course", queryset=None, required=False, empty_label="Only me (personal)")

    class Meta:
        model = Event
        fields = ["title", "starts_at", "ends_at", "description", "course"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user.role == "student":
            del self.fields["course"]  # students only add personal events
        else:
            self.fields["course"].queryset = perm.visible_courses_for(user)
            self.fields["course"].help_text = "Enrolled students see it on their calendar."

    def clean(self):
        data = super().clean()
        s, e = data.get("starts_at"), data.get("ends_at")
        if s and e and e <= s:
            self.add_error("ends_at", "The end must be after the start.")
        return data


class SlotForm(forms.ModelForm):
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    class Meta:
        model = TimetableSlot
        fields = ["kind", "weekday", "start_time", "end_time", "room"]

    def clean(self):
        data = super().clean()
        s, e = data.get("start_time"), data.get("end_time")
        if s and e and e <= s:
            self.add_error("end_time", "The end must be after the start.")
        return data


class TodoForm(forms.ModelForm):
    due_date = forms.DateField(label="Due (optional)", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    class Meta:
        model = TodoItem
        fields = ["title", "due_date"]
