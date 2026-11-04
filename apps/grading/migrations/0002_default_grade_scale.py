from decimal import Decimal

from django.db import migrations

# Default scale. Lee can change it in the Django admin until the settings screen is built.
SCALE = [("85", "A+", "4.00"), ("75", "A", "4.00"), ("70", "A-", "3.70"), ("65", "B+", "3.30"), ("60", "B", "3.00"), ("55", "B-", "2.70"),
         ("50", "C+", "2.30"), ("45", "C", "2.00"), ("40", "C-", "1.70"), ("35", "D+", "1.30"), ("30", "D", "1.00"), ("0", "E", "0.00")]


def add_scale(apps, schema_editor):
    GradeBand = apps.get_model("grading", "GradeBand")
    if not GradeBand.objects.exists():
        for m, letter, pts in SCALE:
            GradeBand.objects.create(min_percent=Decimal(m), letter=letter, points=Decimal(pts))


class Migration(migrations.Migration):
    dependencies = [("grading", "0001_initial")]
    operations = [migrations.RunPython(add_scale, migrations.RunPython.noop)]
