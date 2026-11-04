"""Marking rubrics: a table of criteria, each with levels worth points. The mark is the points earned, scaled to the assignment's maximum."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from . import services
from .models import RubricCriterion, RubricLevel, RubricScore

MAX_CRITERIA = 12
MIN_LEVELS, MAX_LEVELS = 2, 6


def parse_levels(text):
    """One level per line as 'label | points | description'. Returns (levels, error)."""
    levels = []
    for n, line in enumerate((text or "").splitlines(), start=1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            return [], f"Line {n}: write it as  label | points | description  (the description is optional)."
        try:
            pts = Decimal(parts[1])
            if pts < 0 or pts > 1000 or pts != pts.quantize(Decimal("0.01")):
                raise InvalidOperation
        except InvalidOperation:
            return [], f"Line {n}: points must be a number from 0 to 1000 with at most two decimals."
        if len(parts[0]) > 80 or len(parts[2] if len(parts) > 2 else "") > 300:
            return [], f"Line {n}: the label can be 80 characters and the description 300."
        levels.append({"label": parts[0], "points": pts, "description": parts[2] if len(parts) > 2 else ""})
    if not MIN_LEVELS <= len(levels) <= MAX_LEVELS:
        return [], f"Give between {MIN_LEVELS} and {MAX_LEVELS} levels, one per line."
    if len({lv["points"] for lv in levels}) != len(levels):
        return [], "Two levels have the same points. Give each level its own points."
    return levels, None


def levels_text(criterion):
    lines = []
    for lv in criterion.levels.all():
        parts = [lv.label, format(lv.points.normalize(), "f")]
        if lv.description:
            parts.append(lv.description)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def total_points(assignment):
    return sum((c.max_points for c in assignment.criteria.prefetch_related("levels")), Decimal("0"))


def has_rubric(assignment):
    return assignment.criteria.exists()


def is_locked(assignment):
    """Once anything was marked with the rubric, its rows and points are fixed so earlier marks stay fair."""
    return RubricScore.objects.filter(criterion__assignment=assignment).exists()


def scaled_mark(points, assignment):
    total = total_points(assignment)
    if not total:
        return Decimal("0")
    return (Decimal(points) / total * assignment.max_mark).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@transaction.atomic
def save_criterion(assignment, criterion, title, description, levels, position=None):
    if criterion is None:
        last = assignment.criteria.order_by("-position").first()
        criterion = RubricCriterion(assignment=assignment, position=(last.position + 1) if last else 0)
    criterion.title, criterion.description = title, description
    if position is not None:
        criterion.position = position
    criterion.save()
    criterion.levels.all().delete()
    RubricLevel.objects.bulk_create([RubricLevel(criterion=criterion, **lv) for lv in levels])
    return criterion


@transaction.atomic
def copy_rubric(source, target):
    """Copy every criterion and level from one assignment to another that has no rubric yet."""
    n = 0
    for c in source.criteria.prefetch_related("levels"):
        nc = RubricCriterion.objects.create(assignment=target, position=c.position, title=c.title, description=c.description)
        RubricLevel.objects.bulk_create([RubricLevel(criterion=nc, label=lv.label, points=lv.points, description=lv.description) for lv in c.levels.all()])
        n += 1
    return n


class RubricError(ValueError):
    pass


@transaction.atomic
def grade(submission, picks, feedback, grader):
    """picks: {criterion_id: (level_id, comment)}. Every criterion needs a level. Returns the saved submission."""
    a = submission.assignment
    criteria = list(a.criteria.prefetch_related("levels"))
    if not criteria:
        raise RubricError("This assignment has no rubric.")
    earned, scores = Decimal("0"), []
    for c in criteria:
        level_id, comment = picks.get(c.pk, (None, ""))
        level = next((lv for lv in c.levels.all() if lv.pk == level_id), None)
        if level is None:
            raise RubricError(f"Pick a level for “{c.title}”.")
        earned += level.points
        scores.append(RubricScore(submission=submission, criterion=c, level=level, label=level.label, points=level.points, comment=(comment or "")[:500]))
    submission.rubric_scores.all().delete()
    RubricScore.objects.bulk_create(scores)
    return services.grade(submission, scaled_mark(earned, a), feedback, grader)
