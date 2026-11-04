"""Rendering of the editable emails. Only the known placeholders are replaced, so a template can never read other data."""
import re

from .models import DEFAULTS, PLACEHOLDERS, EmailTemplate

_TOKEN = re.compile(r"\{([a-z_]+)\}")


def unknown_placeholders(text):
    return sorted({m for m in _TOKEN.findall(text) if m not in PLACEHOLDERS})


def fill(text, values):
    return _TOKEN.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def get_template(key):
    obj = EmailTemplate.objects.filter(key=key).first()
    if obj:
        return obj.subject, obj.body
    return DEFAULTS[key]


def render(key, values):
    subject, body = get_template(key)
    return fill(subject, values).replace("\n", " ")[:200], fill(body, values)
