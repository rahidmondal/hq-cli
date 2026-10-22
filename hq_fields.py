"""Pure field parsing, validation and read-time defaults for advanced mode.

No filesystem access and no HQ_ROOT use.
"""
import datetime
import re
from pathlib import Path

from hq_core import HqError, slugify

PRIORITIES = ("P1", "P2", "P3", "P4")
DEFAULT_PRIORITY = "P3"
AREAS = ("work", "personal")
ENTRY_SET_FIELDS = ("priority", "due", "do-on", "est", "goal", "area")
GOAL_SET_FIELDS = ("priority", "target", "area")

_ISO_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_REL_RE = re.compile(r"\A\+(\d+)([dw])\Z")
_EST_RE = re.compile(r"\A(?:(\d+)h)?(?:(\d+)m)?\Z")


def parse_priority(s: str) -> str:
    t = str(s).strip().upper()
    if t.isdigit():
        t = "P" + t
    if t not in PRIORITIES:
        raise HqError(f"bad priority {s!r} (use P1-P4)")
    return t


def _iso(s: str):
    if not _ISO_RE.match(s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def parse_date(s: str, today=None) -> str:
    if today is None:
        today = datetime.date.today()
    t = str(s).strip().lower()
    if t == "today":
        return today.isoformat()
    if t == "tomorrow":
        return (today + datetime.timedelta(days=1)).isoformat()
    m = _REL_RE.match(t)
    if m:
        n = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
        try:
            return (today + datetime.timedelta(days=n)).isoformat()
        except OverflowError:
            pass
    else:
        d = _iso(t)
        if d:
            return d.isoformat()
    raise HqError(f"bad date {s!r} (use YYYY-MM-DD, today, tomorrow, +Nd, +Nw)")


def parse_est(s: str) -> int:
    t = str(s).strip().lower()
    minutes = None
    if t.isdigit():
        minutes = int(t)
    else:
        m = _EST_RE.match(t)
        if m and t:
            minutes = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    if not minutes:
        raise HqError(f"bad estimate {s!r} (use 20m, 1h, 1h30m or minutes; must be > 0)")
    return minutes


def format_est(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return (f"{h}h" if h else "") + (f"{m}m" if m or not h else "")


def parse_area(s: str) -> str:
    t = str(s).strip().lower()
    if t not in AREAS:
        raise HqError(f"bad area {s!r} (use work or personal)")
    return t


def normalize(field: str, value: str, today=None) -> str:
    if field == "priority":
        return parse_priority(value)
    if field in ("due", "do-on", "target"):
        return parse_date(value, today)
    if field == "est":
        return format_est(parse_est(value))
    if field == "goal":
        slug = slugify(str(value))
        if not slug:
            raise HqError(f"bad goal {value!r} (use a goal title or slug)")
        return slug
    if field == "area":
        return parse_area(value)
    raise HqError(f"unknown field {field!r}")


def _try(fn, value):
    if value is None:
        return None
    try:
        return fn(str(value))
    except HqError:
        return None


def _strict_date(s: str):
    d = _iso(s.strip())
    return d.isoformat() if d else None


def _text(value):
    if value is None:
        return None
    t = str(value).strip()
    return t or None


def entry_view(meta: dict, *, project: str, status: str, slug: str, title: str,
               path: Path, goal_areas: dict, project_area: str) -> dict:
    goal = _text(meta.get("goal"))
    area = _try(parse_area, meta.get("area")) or goal_areas.get(goal) or project_area
    est = _try(parse_est, meta.get("est"))
    return {
        "project": project,
        "status": status,
        "slug": slug,
        "kind": meta.get("kind", ""),
        "title": title,
        "created": meta.get("created", ""),
        "tags": meta.get("tags", []),
        "path": path,
        "priority": _try(parse_priority, meta.get("priority")) or DEFAULT_PRIORITY,
        "area": area,
        "goal": goal,
        "due": _try(_strict_date, meta.get("due")),
        "do_on": _try(_strict_date, meta.get("do-on")),
        "est": est,
        "blocked": _text(meta.get("blocked")),
        "outcome": _text(meta.get("outcome")),
    }
