"""Artifacts (advanced mode): files kept next to an entry's or goal's README,
with what each one is and why it exists, in <folder>/.artifacts.json
(hidden, so classic's board ignores it): [{file, about, why, added}].
`about` and `why` come from the user; agents ask rather than invent them."""
import datetime
import json
import shutil
from pathlib import Path

import hq_core
from hq_core import HqError

INDEX = ".artifacts.json"


def _load(folder: Path) -> list[dict]:
    path = folder / INDEX
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    return [a for a in data if isinstance(a, dict) and isinstance(a.get("file"), str)] \
        if isinstance(data, list) else []


def for_folder(folder: Path) -> list[dict]:
    """Every visible file in the folder (README aside), registered ones with
    their about/why, then registered files that are missing (missing: true)."""
    registered = {a["file"]: a for a in _load(folder)}
    out = []
    for p in sorted(folder.iterdir()):
        if p.name == "README.md" or p.name.startswith("."):
            continue
        a = registered.pop(p.name, None)
        out.append({"file": p.name, "about": (a or {}).get("about"), "why": (a or {}).get("why"),
                    "added": (a or {}).get("added"), "dir": p.is_dir()})
    for name, a in registered.items():
        out.append({"file": name, "about": a.get("about"), "why": a.get("why"),
                    "added": a.get("added"), "missing": True})
    return out


def _folder(ref: str, project: str | None):
    import hq_ops

    r = hq_ops.resolve_ref(ref, project=project)
    return r, r.path.parent


def list_for(ref: str, project: str | None = None) -> list[dict]:
    return for_folder(_folder(ref, project)[1])


def add(ref: str, file: str, about: str, why: str, project: str | None = None) -> Path:
    about, why = " ".join((about or "").split()), " ".join((why or "").split())
    if not about or not why:
        raise HqError("--about and --why are both required (ask the user if you don't know)")
    r, folder = _folder(ref, project)
    src = Path(file).expanduser()
    inside = folder / src.name
    if src.name in ("README.md", INDEX) or src.name.startswith("."):
        raise HqError(f"can't register {src.name!r} as an artifact")
    if inside.exists() and (not src.exists() or src.resolve() == inside.resolve()):
        dest = inside  # already in the folder (given by name or full path)
    elif src.exists():
        if inside.exists():
            raise HqError(f"{folder} already has a file named {src.name!r}")
        if src.is_dir():
            shutil.copytree(src, inside)
        else:
            shutil.copy2(src, inside)
        dest = inside
    else:
        raise HqError(f"no such file: {file}")
    items = [a for a in _load(folder) if a["file"] != dest.name]
    items.append({"file": dest.name, "about": about, "why": why,
                  "added": datetime.date.today().isoformat()})
    items.sort(key=lambda a: a["file"])
    hq_core.atomic_write_text(folder / INDEX, json.dumps(items, indent=2, ensure_ascii=False) + "\n")
    ids = {"goal": r.slug} if r.kind == "goal" else {"project": r.project, "slug": r.slug}
    hq_core.log_action("artifact", **ids, file=dest.name, about=about)
    return dest


def dangling() -> list[tuple[Path, str]]:
    """(index path, file) for every registered artifact whose file is gone."""
    out = []
    roots = [hq_core.HQ_ROOT / "projects", hq_core.HQ_ROOT / "goals"]
    for root in roots:
        if not root.is_dir():
            continue
        for index in root.rglob(INDEX):
            for a in _load(index.parent):
                if not (index.parent / a["file"]).exists():
                    out.append((index, a["file"]))
    return out
