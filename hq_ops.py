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
    A `goal/` prefix restricts to goals; empty `statuses` means goals only.
    Exact matches are looked up across every status: an exact slug in an
    excluded status is an error, never a fall-through to substring matching."""
    text = ref.strip()
    goals_only = text.startswith("goal/")
    if goals_only:
        text = text[len("goal/"):]
        goals = True
    every: list[Ref] = []
    if not goals_only:
        for e in hq_core.list_entries(project=project):
            every.append(Ref("entry", e["slug"], e["project"], e["status"], e["path"]))
    if goals:
        every.extend(_goal_refs())
    candidates = [c for c in every if c.kind == "goal" or c.status in statuses]

    needle = text.lower()
    exact = [c for c in every if c.slug == text] if text else []
    matches = [c for c in exact if c in candidates]
    if exact and not matches:
        found = "/".join(st for st in hq_core.STATUSES
                         if any(c.status == st for c in exact))
        wanted = "/".join(statuses) or "a goal"
        raise HqError(f"'{text}' is {found}, not {wanted}")
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


def _noun(ref: Ref) -> str:
    return "goal" if ref.kind == "goal" else "entry"


def _read(ref: Ref) -> tuple[dict, str]:
    try:
        return hq_core.frontmatter_parse(ref.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise HqError(f"can't read {ref.path}: {e}")


def _log_id(ref: Ref) -> dict:
    if ref.kind == "goal":
        return {"goal": ref.slug}
    return {"project": ref.project, "slug": ref.slug}


def set_field(ref: str, field: str, value: str, project: str | None = None) -> Path:
    r = resolve_ref(ref, project=project)
    allowed = hq_fields.GOAL_SET_FIELDS if r.kind == "goal" else hq_fields.ENTRY_SET_FIELDS
    if field not in allowed:
        raise HqError(f"can't set '{field}' on a {_noun(r)} (allowed: {', '.join(allowed)})")
    clear = str(value).strip().lower() == "none"
    new = None if clear else hq_fields.normalize(field, value)
    if field == "goal" and new is not None and hq_registry.get_goal(new) is None:
        raise HqError(f"unknown goal '{new}'")
    meta, body = _read(r)
    old = meta.get(field)
    if clear:
        meta.pop(field, None)
    else:
        meta[field] = new
    hq_core.atomic_write_text(r.path, hq_core.frontmatter_dump(meta, body))
    hq_core.log_action("set", **_log_id(r), field=field, **{"from": old, "to": new})
    return r.path


def add_note(ref: str, text: str, project: str | None = None) -> None:
    if not text or not text.strip():
        raise HqError("note text is empty")
    r = resolve_ref(ref, project=project)
    hq_core.log_action("note", **_log_id(r), text=text)


def block(ref: str, reason: str, project: str | None = None) -> Path:
    if not reason or not reason.strip():
        raise HqError("block reason is empty")
    r = resolve_ref(ref, project=project, goals=False)
    if r.status not in ("planning", "active"):
        raise HqError(f"can't block '{r.slug}': it is {r.status}")
    meta, body = _read(r)
    meta["blocked"] = reason.strip()
    hq_core.atomic_write_text(r.path, hq_core.frontmatter_dump(meta, body))
    hq_core.log_action("block", project=r.project, slug=r.slug, reason=reason.strip())
    return r.path


def unblock(ref: str, project: str | None = None) -> Path:
    r = resolve_ref(ref, project=project, goals=False)
    meta, body = _read(r)
    if not str(meta.get("blocked", "")).strip():
        raise HqError(f"'{r.slug}' is not blocked")
    del meta["blocked"]
    hq_core.atomic_write_text(r.path, hq_core.frontmatter_dump(meta, body))
    hq_core.log_action("unblock", project=r.project, slug=r.slug)
    return r.path


def unstart(ref: str, reason: str | None = None, project: str | None = None) -> Path:
    r = resolve_ref(ref, project=project, goals=False)
    if r.status != "active":
        raise HqError(f"'{r.slug}' is not active")
    meta, body = _read(r)
    meta["status"] = "planning"
    src = r.path.parent
    dest = hq_core.task_path(r.project, "planning", r.slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    hq_core.atomic_write_text(dest / "README.md", hq_core.frontmatter_dump(meta, body))
    hq_core.log_action("unstart", project=r.project, slug=r.slug, reason=reason or None)
    return dest / "README.md"


def show(ref: str, project: str | None = None, log_limit: int = 10) -> dict:
    r = resolve_ref(ref, project=project)
    meta, body = _read(r)
    files = sorted(p.name for p in r.path.parent.iterdir()
                   if p.name != "README.md" and not p.name.startswith("."))
    out = {"kind": r.kind}
    if r.kind == "goal":
        record = hq_registry.get_goal(r.slug)
        if record is None:
            raise HqError(f"can't read {r.path}")
        lines = [e for e in hq_core.read_log()
                 if (e.get("slug") == r.slug and not e.get("project")) or e.get("goal") == r.slug]
        tasks = [{"project": t["project"], "status": t["status"], "slug": t["slug"],
                  "title": t["title"], "blocked": t["blocked"]}
                 for t in entry_records() if t["goal"] == r.slug]
    else:
        record = next((t for t in entry_records(project=r.project, status=r.status)
                       if t["slug"] == r.slug), None)
        if record is None:
            raise HqError(f"can't read {r.path}")
        lines = [e for e in hq_core.read_log()
                 if e.get("slug") == r.slug and e.get("project") == r.project]
        tasks = None
    out.update(record=record, body=body.strip("\n"), files=files,
               log=lines[-log_limit:] if log_limit > 0 else [])
    if tasks is not None:
        out["tasks"] = tasks
    return out
