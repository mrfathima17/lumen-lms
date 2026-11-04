from pathlib import Path

from django import template
from django.utils.html import format_html

from apps.accounts.navigation import nav_for

register = template.Library()

_NAMES = set((Path(__file__).resolve().parent.parent / "icon_names.txt").read_text().split())


@register.simple_tag
def icon(name, css=""):
    """Render one icon from the shared sprite: {% icon "search" %}."""
    if name not in _NAMES:
        name = "help"
    return format_html('<svg class="icon{}" aria-hidden="true"><use href="#i-{}"/></svg>', f" {css}" if css else "", name)


@register.inclusion_tag("partials/sidebar.html", takes_context=True)
def sidebar(context):
    request = context["request"]
    user = request.user
    match = request.resolver_match
    current = f"{match.namespace}:{match.url_name}" if match and match.namespace else (match.url_name if match else "")
    return {"items": nav_for(user.role, current, context.get("disabled_modules") or ()) if user.is_authenticated else [], "lumen_site": context.get("lumen_site")}


@register.filter
def audit_event(a):
    """The readable sentence for an audit log row."""
    from apps.core.audit_text import describe

    return describe(a)


@register.filter
def audit_user(a):
    from apps.core.audit_text import who

    return who(a)


@register.filter
def audit_time(dt):
    from apps.core.audit_text import when

    return when(dt)


@register.filter
def filesize(n):
    """Bytes as a short human string: 12 KB, 3.4 MB."""
    from apps.files.services import human

    try:
        return human(int(n))
    except (TypeError, ValueError):
        return ""


@register.filter
def get(mapping, key):
    """Dictionary lookup in templates; a missing key gives an empty list."""
    return (mapping or {}).get(key, [])


@register.filter
def get_one(mapping, key):
    return (mapping or {}).get(key, "")
