from . import modules
from .models import SiteSettings


def site(request):
    s = SiteSettings.load()
    theme = {"brand": s.brand_color, "brand2": s.brand_color2, "sidebar": s.sidebar_color, "font": s.font, "radius": s.radius,
             "loginBg": s.login_bg_css, "defaultMode": s.default_mode, "allowDark": s.allow_dark_mode}
    out = {"lumen_site": s, "lumen_theme": theme, "disabled_modules": modules.disabled_keys(request)}
    user = getattr(request, "user", None)
    pid = getattr(user, "preview_course_id", None)
    if pid:
        from apps.courses.models import Course

        out["preview_course"] = Course.objects.filter(pk=pid).first()
    return out
