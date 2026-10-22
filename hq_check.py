"""`hq check`: read-only consistency scan of the store. Never writes, never logs."""
import os
import re
from pathlib import Path

import hq_core
import hq_fields
import hq_registry
from hq_core import HqError

_STRICT_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_BAD = (HqError, ValueError, TypeError, AttributeError, OverflowError)


def _rel(path) -> str:
    try:
        return path.relative_to(hq_core.HQ_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _ok(fn, v) -> bool:
    try:
        fn(v)
        return True
    except _BAD:
        return False


def _strict_date_ok(v) -> bool:
    return isinstance(v, str) and bool(_STRICT_DATE.match(v.strip())) and _ok(hq_fields.parse_date, v)


def _field_problems(meta: dict, fields) -> list[str]:
    out = []
    for key in fields:
        v = meta.get(key)
        if _empty(v):
            continue
        if key == "priority":
            if isinstance(v, list) or not _ok(hq_fields.parse_priority, v):
                out.append(f"bad priority '{v}'")
        elif key in ("due", "do-on", "target"):
            if not _strict_date_ok(v):
                out.append(f"bad date in {key} '{v}'")
        elif key == "est":
            if isinstance(v, list) or not _ok(hq_fields.parse_est, v):
                out.append(f"bad est '{v}'")
        elif key == "area":
            if isinstance(v, list) or not _ok(hq_fields.parse_area, v):
                out.append(f"bad area '{v}'")
    return out


def _read(path):
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return None


def run_checks() -> list[dict]:
    problems = []

    def add(path, problem):
        problems.append({"path": _rel(path) if not isinstance(path, str) else path,
                         "problem": problem})

    root = hq_core.HQ_ROOT
    goals_dir = root / "goals"

    def goal_exists(g) -> bool:
        if not isinstance(g, str) or not g or "/" in g or "\\" in g or g in (".", ".."):
            return False
        return hq_registry.goal_readme(g).is_file()

    for project, status, slug, kind_hint, path in hq_core.iter_all_entries():
        if project is None:
            continue
        text = _read(path)
        if text is None:
            continue
        if not hq_core._FRONTMATTER_RE.match(text):
            add(path, "missing frontmatter")
            continue
        meta, _ = hq_core.frontmatter_parse(text)
        meta_status = meta.get("status")
        if not _empty(meta_status) and meta_status != status:
            add(path, f"status '{meta_status}' does not match folder '{status}'")
        for p in _field_problems(meta, ("priority", "due", "do-on", "est", "area")):
            add(path, p)
        goal = meta.get("goal")
        if not _empty(goal) and not goal_exists(goal):
            add(path, f"unknown goal '{goal}'")

    if goals_dir.is_dir():
        for d in sorted(goals_dir.iterdir()):
            readme = d / "README.md"
            if not d.is_dir() or not readme.is_file():
                continue
            text = _read(readme)
            if text is None:
                continue
            meta, _ = hq_core.frontmatter_parse(text)
            st = meta.get("status")
            if not _empty(st) and st not in hq_registry.GOAL_STATUSES:
                add(readme, f"goal status '{st}' is not one of "
                            f"{', '.join(hq_registry.GOAL_STATUSES)}")
            for p in _field_problems(meta, ("priority", "target", "area")):
                add(readme, p)

    try:
        hq_registry.load_projects()
    except HqError:
        add(hq_registry.projects_path(), "projects.json is not valid JSON")

    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                low = name.lower()
                if ".sync-conflict-" in low or "conflicted copy" in low:
                    add(Path(dirpath) / name, "sync conflict copy")

    problems.sort(key=lambda p: (p["path"], p["problem"]))
    return problems
