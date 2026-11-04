import base64
import os
import struct
import zlib

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import LOGIN_BACKGROUNDS, SiteSettings
from tests.test_administration2 import admin_client, theme_post  # noqa: F401  (fixture re-used)


def png_data_url(size=8):
    """A tiny valid PNG as a data: URL, like the browser's canvas produces."""
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def post(client, **over):
    return client.post(reverse("administration:theme"), theme_post(**over))


def test_new_fields_saved_and_sent_to_every_page(admin_client):
    r = post(admin_client, site_name="Campus", brand_color="#047857", brand_color2="#0f766e", font="Poppins", radius="20", login_bg=LOGIN_BACKGROUNDS[2])
    assert r.status_code == 302
    s = SiteSettings.load()
    assert (s.site_name, s.brand_color2, s.font, s.radius, s.login_bg) == ("Campus", "#0f766e", "Poppins", 20, LOGIN_BACKGROUNDS[2])
    page = admin_client.get(reverse("administration:theme")).content.decode()
    assert "Poppins" in page and 'value="#0f766e"' in page


@pytest.mark.parametrize("field,value", [("brand_color2", "#fde047"), ("font", "Comic Sans"), ("radius", "99"), ("radius", "2"),
                                         ("login_bg", "url(javascript:alert(1))"), ("login_bg", "#ffffe0"), ("site_name", "   ")])
def test_bad_values_refused(admin_client, field, value):
    before = SiteSettings.load().brand_color2
    r = post(admin_client, **{field: value})
    assert r.status_code == 200 and SiteSettings.load().brand_color2 == before and SiteSettings.load().login_bg == ""


def test_solid_login_colour_accepted(admin_client):
    assert post(admin_client, login_bg="#1E293B").status_code == 302
    assert SiteSettings.load().login_bg == "#1e293b"


def test_logo_upload_is_served_publicly_and_can_be_removed(admin_client, client):
    assert post(admin_client, logo_data=png_data_url()).status_code == 302
    s = SiteSettings.load()
    assert s.logo and s.logo.name.endswith(".png")
    anon = Client()  # signed out: the sign-in page needs the logo
    r = anon.get(reverse("core:brand-asset", args=["logo"]))
    assert r.status_code == 200 and r["Content-Type"] == "image/png" and r["X-Content-Type-Options"] == "nosniff"
    r.close()  # release the file handle, otherwise Windows refuses to delete the logo below
    assert b'class="has-img"' in anon.get(reverse("accounts:login")).content
    path = s.logo.path
    assert post(admin_client, remove_logo="1").status_code == 302
    s = SiteSettings.load()
    assert not s.logo
    assert not os.path.exists(path)
    assert anon.get(reverse("core:brand-asset", args=["logo"])).status_code == 404


@pytest.mark.parametrize("bad", ["data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "data:image/png;base64,AAAA", "data:text/html;base64,PGI+", "not-a-data-url",
                                 "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 400_000).decode()])
def test_bad_or_oversized_logo_refused(admin_client, bad):
    r = post(admin_client, logo_data=bad)
    assert r.status_code == 200 and not SiteSettings.load().logo


def test_background_image_replaces_preset_and_preset_replaces_image(admin_client):
    post(admin_client, login_bg=LOGIN_BACKGROUNDS[0])
    post(admin_client, login_bg="", login_bg_data=png_data_url())
    s = SiteSettings.load()
    assert s.login_bg_image and s.login_bg == "" and s.login_bg_css.startswith("url('/branding/login-bg/?v=")
    r = admin_client.get(reverse("core:brand-asset", args=["login-bg"]))
    assert r.status_code == 200
    r.close()  # release the file handle so Windows can delete the image below
    post(admin_client, login_bg=LOGIN_BACKGROUNDS[1], remove_login_image="1")
    s = SiteSettings.load()
    assert not s.login_bg_image and s.login_bg == LOGIN_BACKGROUNDS[1]


def test_reset_clears_everything_including_images(admin_client):
    post(admin_client, site_name="Campus", brand_color2="#0f766e", font="Nunito", radius="4", logo_data=png_data_url(), login_bg_data=png_data_url())
    admin_client.post(reverse("administration:theme"), {"reset": "1"})
    s = SiteSettings.load()
    assert (s.site_name, s.brand_color2, s.font, s.radius, s.login_bg) == ("Lumen", "#7c3aed", "system", 12, "")
    assert not s.logo and not s.login_bg_image


def test_unknown_asset_is_404(client, db):
    assert client.get("/branding/other/").status_code == 404


def test_theme_page_is_admin_only(client, student):
    client.force_login(student)
    assert client.get(reverse("administration:theme")).status_code == 403


def test_presets_pass_the_contrast_rules(admin_client):
    from apps.core.models import COLOUR_PRESETS

    for name, brand, brand2, sidebar in COLOUR_PRESETS:
        assert post(admin_client, brand_color=brand, brand_color2=brand2, sidebar_color=sidebar).status_code == 302, name
