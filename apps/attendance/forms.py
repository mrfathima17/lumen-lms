from django import forms

from .models import AttendanceSession


class SessionForm(forms.ModelForm):
    class Meta:
        model = AttendanceSession
        fields = ["title", "held_on", "start_time"]
        widgets = {"held_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}
