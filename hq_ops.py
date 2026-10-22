"""Entry/goal refs and advanced-mode entry records and filters."""
from dataclasses import dataclass
from pathlib import Path

import hq_core
import hq_fields
import hq_registry
from hq_core import HqError


@dataclass
class Ref:
    kind: str  # "entry" or "goal"
    slug: str
    project: str | None
    status: str | None
    path: Path

    def label(self) -> str:
        if self.kind == "goal":
            return f"goal/{self.slug}"
        return f"{self.project}/{self.status}/{self.slug}"


def _goal_refs() -> list[Ref]:
    root = hq_core.HQ_ROOT / "goals"
    if not root.is_dir():
        return []
    refs = []
    for d in sorted(root.iterdir()):
        readme = d / "README.md"
        if d.is_dir() and readme.is_file():
            refs.append(Ref("goal", d.name, None, None, readme))
    return refs


def resolve_ref(ref: str, project: str | None = None, goals: bool = True,
                statuses: tuple = hq_core.STATUSES) -> Ref:
    """Resolve a slug (exact first, then substring) to one entry or goal.
    A `goal/` prefix restricts to goals; empty `statuses` means goals only."""
    text = ref.strip()
    goals_only = text.startswith("goal/")
    if goals_only:
        text = text[len("goal/"):]
        goals = True
    candidates: list[Ref] = []
    if not goals_only:
        for st in statuses:
            for e in hq_core.list_entries(project=project, status=st):
                candidates.append(Ref("entry", e["slug"], e["project"], e["status"], e["path"]))
    if goals:
        candidates.extend(_goal_refs())

    needle = text.lower()
    matches = [c for c in candidates if c.slug == text] if text else []
    if not matches:
        matches = [c for c in candidates if needle and needle in c.slug.lower()]
    if not matches:
        raise HqError(f"nothing matches '{ref}'")
    if len(matches) > 1:
        labels = ", ".join(sorted(m.label() for m in matches))
        raise HqError(f"ambiguous ref '{ref}': {labels} (be more specific or use --project)")
    return matches[0]


def entry_records(project: str | None = None, status: str | None = None) -> list[dict]:
    areas = hq_registry.goal_areas()
    registry = hq_registry.load_projects()
    records = []
    for e in hq_core.list_entries(project=project, status=status):
        try:
            meta, _ = hq_core.frontmatter_parse(e["path"].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            meta = {}
        records.append(hq_fields.entry_view(
            meta, project=e["project"], status=e["status"], slug=e["slug"],
            title=e["title"], path=e["path"], goal_areas=areas,
            project_area=hq_registry.project_area(e["project"], registry),
        ))
    return records


def filter_records(records, area=None, goal=None, priority=None,
                   due_before: str | None = None) -> list[dict]:
    if area is not None:
        area = hq_fields.parse_area(area)
    if priority is not None:
        priority = hq_fields.parse_priority(priority)
    if goal is not None:
        goal = hq_core.slugify(goal)
    cutoff = hq_fields.parse_date(due_before) if due_before is not None else None
    out = []
    for r in records:
        if area is not None and r["area"] != area:
            continue
        if goal is not None and r["goal"] != goal:
            continue
        if priority is not None and r["priority"] != priority:
            continue
        if cutoff is not None and not (r["due"] and r["due"] < cutoff):
            continue
        out.append(r)
    return out
