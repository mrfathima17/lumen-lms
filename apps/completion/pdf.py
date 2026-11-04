"""Certificate PDF (reportlab, pure Python). Uses the built-in Helvetica/Times fonts, so characters outside
Latin (for example Sinhala or Tamil) will not print; set CERTIFICATE_FONT to a TTF path to change that."""
import io

from django.conf import settings
from django.utils import timezone
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def _fonts():
    path = getattr(settings, "CERTIFICATE_FONT", "")
    if path:
        pdfmetrics.registerFont(TTFont("LumenCert", path))
        return "LumenCert", "LumenCert"
    return "Times-Bold", "Helvetica"


def build_pdf(cert, site_name, verify_url, brand="#4f46e5"):
    buf = io.BytesIO()
    w, h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setTitle(f"Certificate {cert.code}")
    c.setAuthor(site_name)
    heading, body = _fonts()
    col = HexColor(brand)
    c.setStrokeColor(col)
    c.setLineWidth(6)
    c.rect(28, 28, w - 56, h - 56)
    c.setLineWidth(1)
    c.rect(40, 40, w - 80, h - 80)
    c.setFillColor(col)
    c.setFont(body, 16)
    c.drawCentredString(w / 2, h - 105, site_name.upper())
    c.setFillColor(HexColor("#171a2e"))
    c.setFont(heading, 40)
    c.drawCentredString(w / 2, h - 175, "Certificate of Completion")
    c.setFont(body, 15)
    c.drawCentredString(w / 2, h - 225, "This certifies that")
    c.setFont(heading, 34)
    name = cert.student_name
    while c.stringWidth(name, heading, 34) > w - 160 and len(name) > 10:
        name = name[:-1]
    c.drawCentredString(w / 2, h - 285, name)
    c.setFont(body, 15)
    c.drawCentredString(w / 2, h - 330, "has successfully completed the course")
    c.setFont(heading, 24)
    y = h - 372
    for line in simpleSplit(f"{cert.course_code} · {cert.course_title}", heading, 24, w - 160)[:2]:
        c.drawCentredString(w / 2, y, line)
        y -= 30
    c.setFont(body, 13)
    c.setFillColor(HexColor("#475069"))
    c.drawCentredString(w / 2, 120, f"Issued on {timezone.localtime(cert.issued_at):%d %B %Y}")
    c.drawCentredString(w / 2, 100, f"Certificate {cert.code}  ·  Verify at {verify_url}")
    if not cert.is_valid:
        c.saveState()
        c.setFillColor(HexColor("#b42318"))
        c.setFont("Helvetica-Bold", 70)
        c.translate(w / 2, h / 2)
        c.rotate(25)
        c.drawCentredString(0, 0, "REVOKED")
        c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()
