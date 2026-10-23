"""Project settings (.hq/projects.json) and goals (goals/<slug>/README.md)."""
import datetime
import json
from pathlib import Path

import hq_core
from hq_core import HqError
from hq_fields import DEFAULT_PRIORITY, normalize, parse_area, parse_priority

GOAL_STATUSES = ("active", "done", "dropped")


def projects_path() -> Path:
    return hq_core.HQ_ROOT / ".hq" / "projects.json"


def load_projects() -> dict:
    path = projects_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise HqError(f"invalid JSON in {path}: {e}")
    if not isinstance(data, dict):
        raise HqError(f"invalid projects file {path}: expected an object")
    return data


def _save_projects(data: dict) -> None:
    path = projects_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    hq_core.atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _project_record(data: dict, project: str) -> dict:
    rec = data.get(project)
    if not isinstance(rec, dict):
        rec = {}
        data[project] = rec
    return rec


def record_repo(project: str, repo: Path) -> None:
    data = load_projects()
    rec = _project_record(data, project)
    repos = rec.get("repos")
    if not isinstance(repos, list):
        repos = []
    posix = Path(repo).as_posix()
    if posix in repos:
        return
    repos.append(posix)
    rec["repos"] = repos
    _save_projects(data)


def set_project_area(project: str, area: str) -> None:
    area = parse_area(area)
    data = load_projects()
    _project_record(data, project)["area"] = area
    _save_projects(data)
    hq_core.log_action("project-set", project=project, field="area", value=area)


def project_area(project: str, registry: dict | None = None) -> str:
    if registry is None:
        registry = load_projects()
    rec = registry.get(project)
    if isinstance(rec, dict) and rec.get("area") is not None:
        try:
            return parse_area(rec["area"])
        except HqError:
            pass
    return "personal" if project == "personal" else "work"


def goal_readme(slug: str) -> Path:
    return hq_core.HQ_ROOT / "goals" / slug / "README.md"


def create_goal(title: str, area: str = "work", target: str | None = None,
                priority: str | None = None, tags: list[str] | None = None) -> Path:
    slug = hq_core.slugify(title)
    if not slug:
        raise HqError(f"title produces an empty slug: {title!r}")
    area = parse_area(area)
    prio = parse_priority(priority) if priority is not None else None
    tgt = normalize("target", target) if target is not None else None
    path = goal_readme(slug)
    if path.parent.exists():
        raise HqError(f"goal already exists: {path.parent}")
    meta = {"kind": "goal", "area": area, "status": "active"}
    if prio:
        meta["priority"] = prio
    if tgt:
        meta["target"] = tgt
    meta["created"] = datetime.date.today().isoformat()
    meta["tags"] = tags or []
    path.parent.mkdir(parents=True)
    hq_core.atomic_write_text(path, hq_core.frontmatter_dump(meta, f"# {title}\n\n"))
    hq_core.log_action("goal", op="new", slug=slug)
    return path


def _goal_view(slug: str, path: Path) -> dict | None:
    try:
        meta, body = hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    try:
        area = parse_area(meta.get("area"))
    except HqError:
        area = "work"
    try:
        prio = parse_priority(meta.get("priority"))
    except HqError:
        prio = DEFAULT_PRIORITY
    status = meta.get("status")
    if status not in GOAL_STATUSES:
        status = "active"
    try:
        target = normalize("target", meta["target"]) if meta.get("target") else None
    except HqError:
        target = None
    tags = meta.get("tags", [])
    return {
        "slug": slug,
        "title": hq_core.extract_title(body) or slug,
        "area": area,
        "status": status,
        "priority": prio,
        "target": target,
        "created": meta.get("created", ""),
        "tags": tags if isinstance(tags, list) else [],
        "path": path,
    }


def list_goals(status: str | None = None, area: str | None = None) -> list[dict]:
    root = hq_core.HQ_ROOT / "goals"
    if not root.is_dir():
        return []
    goals = []
    for d in sorted(root.iterdir()):
        readme = d / "README.md"
        if not d.is_dir() or not readme.is_file():
            continue
        g = _goal_view(d.name, readme)
        if g is None:
            continue
        if status and g["status"] != status:
            continue
        if area and g["area"] != area:
            continue
        goals.append(g)
    return goals


def get_goal(slug: str) -> dict | None:
    path = goal_readme(slug)
    if not path.is_file():
        return None
    return _goal_view(slug, path)


def goal_areas() -> dict[str, str]:
    return {g["slug"]: g["area"] for g in list_goals()}


def finish_goal(slug: str, dropped: bool = False) -> Path:
    path = goal_readme(slug)
    if not path.is_file():
        raise HqError(f"no such goal: {slug}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise HqError(f"can't read {path}: {e}")
    meta, body = hq_core.frontmatter_parse(text)
    status = "dropped" if dropped else "done"
    meta["status"] = status
    hq_core.atomic_write_text(path, hq_core.frontmatter_dump(meta, body))
    hq_core.log_action("goal", op=status, slug=slug)
    return path
