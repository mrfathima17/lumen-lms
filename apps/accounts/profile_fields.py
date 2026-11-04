"""Reading and writing custom profile values, with validation per field kind."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django import forms

from .models import ProfileField, ProfileValue


def fields_for(role):
    return [f for f in ProfileField.objects.filter(is_active=True) if f.applies_to_role(role)]


def values_for(user):
    return {v.field_id: v.value for v in ProfileValue.objects.filter(user=user)}


class ProfileValuesForm(forms.Form):
    """One form field per active custom field that applies to this user's role."""

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields_list = fields_for(user.role)
        current = values_for(user)
        for f in self.fields_list:
            name = f"f_{f.pk}"
            kw = {"label": f.label, "required": f.required, "initial": current.get(f.pk, "")}
            if f.kind == "number":
                self.fields[name] = forms.DecimalField(max_digits=12, decimal_places=2, **kw)
                if kw["initial"]:
                    try:
                        self.fields[name].initial = Decimal(kw["initial"]).normalize()
                    except InvalidOperation:
                        pass
            elif f.kind == "date":
                self.fields[name] = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), **kw)
                try:
                    self.fields[name].initial = date.fromisoformat(kw["initial"]) if kw["initial"] else None
                except ValueError:
                    self.fields[name].initial = None
            elif f.kind == "choice":
                opts = [("", "—")] + [(o, o) for o in f.options]
                self.fields[name] = forms.ChoiceField(choices=opts, **kw)
            else:
                self.fields[name] = forms.CharField(max_length=200, **kw)

    def save(self):
        for f in self.fields_list:
            raw = self.cleaned_data.get(f"f_{f.pk}")
            text = "" if raw in (None, "") else (raw.isoformat() if isinstance(raw, date) else str(raw))
            if text == "":
                ProfileValue.objects.filter(user=self.user, field=f).delete()
            else:
                ProfileValue.objects.update_or_create(user=self.user, field=f, defaults={"value": text})
