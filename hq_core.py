import datetime
import json
import os
import re
import subprocess
from pathlib import Path


class HqError(Exception):
    pass


KINDS = ("task", "bug", "presentation", "learning", "skill")
STATUSES = ("planning", "active", "archive")

MODES = ("classic", "advanced")
ACTORS = ("user", "agent", "web")
ACTOR = None  # set by the CLI in advanced mode; tags log lines with "by"

HQ_ROOT = Path(os.environ.get("HQ_ROOT", Path.home() / ".hq"))


def config_path() -> Path:
    return HQ_ROOT / ".hq" / "config.json"


def load_config() -> dict:
    try:
        cfg = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def save_config(cfg: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(cfg, indent=2) + "\n")


def mode() -> str:
    return "advanced" if load_config().get("mode") == "advanced" else "classic"


def slugify(title: str) -> str:
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


_YAML_RESERVED = {"true", "false", "yes", "no", "null", "~", "on", "off"}
_YAML_BAD_START = tuple("[]{}&*!|>'\"%@`#,?")


def yaml_scalar(value: str) -> str:
    """Return value as-is when it is plain-YAML safe, else a double-quoted
    (JSON-escaped) string. The empty string stays empty (v1 wrote `key: `)."""
    if not isinstance(value, str):
        value = str(value)
    if value == "":
        return value
    needs_quote = (
        "\n" in value
        or "\r" in value
        or ": " in value
        or " #" in value
        or value.endswith(":")
        or value.startswith(_YAML_BAD_START)
        or value.startswith("- ")
        or value == "-"
        or value != value.strip()
        or value.lower() in _YAML_RESERVED
    )
    return json.dumps(value, ensure_ascii=False) if needs_quote else value


def _unquote(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        if isinstance(decoded, str):
            return decoded
    return value


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to path via a sibling temp file and os.replace."""
    path = Path(path)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _yaml_safe(yaml_safe: bool | None) -> bool:
    """None means: YAML quoting on in advanced mode, raw v1 behavior in classic."""
    return mode() == "advanced" if yaml_safe is None else yaml_safe


def frontmatter_parse(text: str, yaml_safe: bool | None = None) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    unq = _unquote if _yaml_safe(yaml_safe) else (lambda v: v)
    raw, body = match.group(1), match.group(2)
    meta: dict = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [unq(v.strip()) for v in value[1:-1].split(",") if v.strip()]
            meta[key] = items
        else:
            meta[key] = unq(value)
    return meta, body


def frontmatter_dump(meta: dict, body: str, yaml_safe: bool | None = None) -> str:
    q = yaml_scalar if _yaml_safe(yaml_safe) else (lambda v: v)
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(q(v) for v in value)}]")
        else:
            lines.append(f"{key}: {q(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def task_path(project: str, status: str, slug: str) -> Path:
    return HQ_ROOT / "projects" / project / status / slug


def learning_path(slug: str) -> Path:
    return HQ_ROOT / "learnings" / f"{slug}.md"


def skill_path(slug: str) -> Path:
    return HQ_ROOT / "skills" / slug


def detect_project(cwd: Path, override: str | None) -> str:
    if override:
        return slugify(override)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, check=True,
        )
        root = Path(result.stdout.strip())
        return slugify(root.name)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return slugify(Path(cwd).name)


def detect_repo_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    out = result.stdout.strip()
    return Path(out) if out else None


def find_task(slug: str, project: str | None = None) -> list[Path]:
    projects_dir = HQ_ROOT / "projects"
    if not projects_dir.exists():
        return []
    project_dirs = [projects_dir / project] if project else sorted(
        p for p in projects_dir.iterdir() if p.is_dir()
    )
    matches = []
    for proj_dir in project_dirs:
        if not proj_dir.is_dir():
            continue
        for status in STATUSES:
            candidate = proj_dir / status / slug
            if candidate.is_dir():
                matches.append(candidate)
    return matches


def extract_title(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def log_action(action: str, **fields) -> None:
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "action": action,
        **fields,
    }
    if ACTOR is not None:
        entry["by"] = ACTOR
    log_path = HQ_ROOT / ".log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_log(project: str | None = None, since: str | None = None) -> list[dict]:
    log_path = HQ_ROOT / ".log.jsonl"
    if not log_path.exists():
        return []
    results = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if project and entry.get("project") != project:
            continue
        if since and entry.get("ts", "") < since:
            continue
        results.append(entry)
    return results


def save(kind: str, title: str, project_override: str | None = None,
          tags: list[str] | None = None, cwd: Path | None = None,
          fields: dict | None = None) -> Path:
    if kind not in KINDS:
        raise HqError(f"unknown kind: {kind!r} (expected one of {KINDS})")
    slug = slugify(title)
    if not slug:
        raise HqError(f"title produces an empty slug: {title!r}")
    if kind in ("learning", "skill") and project_override is not None:
        raise HqError(f"kind={kind!r} is cross-project and does not take --project")
    created = datetime.date.today().isoformat()
    tags = tags or []

    if kind == "learning":
        path = learning_path(slug)
        if path.exists():
            raise HqError(f"learning already exists: {path}")
        meta = {"kind": "learning", "created": created, "tags": tags}
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, frontmatter_dump(meta, f"# {title}\n\n"))
        log_action("save", kind=kind, slug=slug, project=None, status=None)
        return path

    if kind == "skill":
        dir_path = skill_path(slug)
        if dir_path.exists():
            raise HqError(f"skill already exists: {dir_path}")
        dir_path.mkdir(parents=True, exist_ok=True)
        meta = {"kind": "skill", "created": created, "tags": tags}
        readme = dir_path / "README.md"
        atomic_write_text(
            readme,
            frontmatter_dump(meta, f"# {title}\n\nNotes about this skill (not the skill body itself — see SKILL.md).\n"),
        )
        skill_meta = {"name": slug, "description": title}
        atomic_write_text(
            dir_path / "SKILL.md",
            frontmatter_dump(skill_meta, f"# {title}\n\nSkill body goes here.\n"),
        )
        log_action("save", kind=kind, slug=slug, project=None, status=None)
        return readme

    project = detect_project(cwd or Path.cwd(), project_override)
    if find_task(slug, project=project):
        raise HqError(f"slug already exists for project {project!r}: {slug}")
    status = "planning"
    dir_path = task_path(project, status, slug)
    dir_path.mkdir(parents=True, exist_ok=True)
    meta = {"project": project, "kind": kind, "status": status,
             "created": created, "tags": tags}
    if fields:
        meta.update(fields)
    readme = dir_path / "README.md"
    atomic_write_text(readme, frontmatter_dump(meta, f"# {title}\n\n"))
    log_action("save", kind=kind, project=project, slug=slug, status=status)
    return readme


def _find_unique(slug: str, allowed_statuses: tuple, project_override: str | None):
    if slug != slugify(slug):
        raise HqError(f"invalid slug: {slug!r}")
    matches = [m for m in find_task(slug, project=project_override)
               if m.parent.name in allowed_statuses]
    if not matches:
        raise HqError(f"no task in {allowed_statuses} found for slug: {slug!r}")
    if len(matches) > 1:
        projects = ", ".join(m.parent.parent.name for m in matches)
        raise HqError(f"ambiguous slug {slug!r} found in projects: {projects} (use --project)")
    return matches[0]


def start(slug: str, project_override: str | None = None) -> Path:
    src = _find_unique(slug, ("planning",), project_override)
    project = src.parent.parent.name
    readme_src = src / "README.md"
    if not readme_src.is_file():
        raise HqError(f"task has no README.md: {src}")
    meta, body = frontmatter_parse(readme_src.read_text(encoding="utf-8"))
    meta["status"] = "active"
    dest = task_path(project, "active", slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    atomic_write_text(dest / "README.md", frontmatter_dump(meta, body))
    log_action("start", project=project, slug=slug, from_status="planning", to_status="active")
    return dest


def archive(slug: str, project_override: str | None = None,
            outcome: str | None = None) -> Path:
    src = _find_unique(slug, ("planning", "active"), project_override)
    from_status = src.parent.name
    project = src.parent.parent.name
    readme_src = src / "README.md"
    if not readme_src.is_file():
        raise HqError(f"task has no README.md: {src}")
    meta, body = frontmatter_parse(readme_src.read_text(encoding="utf-8"))
    meta["status"] = "archive"
    if outcome:
        meta["outcome"] = outcome
    dest = task_path(project, "archive", slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    atomic_write_text(dest / "README.md", frontmatter_dump(meta, body))
    extra = {"outcome": outcome} if outcome else {}
    log_action("archive", project=project, slug=slug, from_status=from_status,
               to_status="archive", **extra)
    return dest


def list_entries(project: str | None = None, status: str | None = None,
                 tolerant: bool = False) -> list[dict]:
    """tolerant=True (advanced callers only) lists a README that is not valid
    UTF-8 with empty frontmatter and title = slug instead of raising."""
    projects_dir = HQ_ROOT / "projects"
    if not projects_dir.exists():
        return []
    project_dirs = [projects_dir / project] if project else sorted(
        p for p in projects_dir.iterdir() if p.is_dir()
    )
    statuses = (status,) if status else STATUSES
    entries = []
    for proj_dir in project_dirs:
        if not proj_dir.is_dir():
            continue
        for st in statuses:
            status_dir = proj_dir / st
            if not status_dir.is_dir():
                continue
            for task_dir in sorted(status_dir.iterdir()):
                readme = task_dir / "README.md"
                if not readme.is_file():
                    continue
                try:
                    text = readme.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    if not tolerant:
                        raise
                    text = ""
                meta, body = frontmatter_parse(text)
                entries.append({
                    "project": proj_dir.name,
                    "slug": task_dir.name,
                    "status": st,
                    "kind": meta.get("kind", ""),
                    "title": extract_title(body) or task_dir.name,
                    "created": meta.get("created", ""),
                    "tags": meta.get("tags", []),
                    "path": readme,
                })
    return entries


def iter_all_entries():
    """Yields (project, status, slug, kind_hint, path). kind_hint is None for
    project-scoped entries (kind comes from their own frontmatter instead)."""
    projects_dir = HQ_ROOT / "projects"
    if projects_dir.exists():
        for proj_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
            for status in STATUSES:
                status_dir = proj_dir / status
                if not status_dir.is_dir():
                    continue
                for task_dir in sorted(status_dir.iterdir()):
                    readme = task_dir / "README.md"
                    if readme.is_file():
                        yield proj_dir.name, status, task_dir.name, None, readme

    learnings_dir = HQ_ROOT / "learnings"
    if learnings_dir.exists():
        for f in sorted(learnings_dir.glob("*.md")):
            yield None, None, f.stem, "learning", f

    skills_dir = HQ_ROOT / "skills"
    if skills_dir.exists():
        for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            skill_file = d / "SKILL.md"
            if skill_file.is_file():
                yield None, None, d.name, "skill", skill_file


def search_entries(query: str) -> list[dict]:
    needle = query.lower()
    results = []
    for project, status, slug, kind_hint, path in iter_all_entries():
        text = path.read_text(encoding="utf-8")
        meta, body = frontmatter_parse(text)
        meta_text = " ".join(str(v) for v in meta.values())
        haystack = "\n".join([slug, meta_text, body]).lower()
        if needle in haystack:
            results.append({
                "project": project,
                "status": status,
                "slug": slug,
                "kind": kind_hint or meta.get("kind", ""),
                "title": extract_title(body) or slug,
                "path": path,
            })
    return results
