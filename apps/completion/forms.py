from django import forms

from .models import CompletionRule


class RuleForm(forms.ModelForm):
    class Meta:
        model = CompletionRule
        fields = ["require_assignments", "min_quiz_percent", "min_attendance_percent", "min_final_percent", "auto_certificate"]
        labels = {"require_assignments": "Submit every assignment", "min_quiz_percent": "Quiz average at least (%)",
                  "min_attendance_percent": "Attendance at least (%)", "min_final_percent": "Course mark at least (%)",
                  "auto_certificate": "Issue certificates automatically"}
