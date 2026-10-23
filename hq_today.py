"""The Today list and free-time picks (advanced mode). Pure functions over
hq_ops.entry_records() and hq_registry.list_goals(), shared by the browser
and (phase 2) `hq today` / `hq free`.

Sections, in order (an entry appears once, in its highest section):
  due      open entries due today or earlier
  planned  do-on today or earlier (a past do-on rolls forward)
  goals    entries in active goals whose target is within 7 days or past
  top      remaining active entries at P1/P2
  blocked  planning/active entries with a block reason
"Open" means planning or active and not blocked. Within a section: priority,
then earliest date, then created."""
from datetime import date, timedelta

SECTIONS = (
    ("due", "Overdue and due today"),
    ("planned", "Planned for today"),
    ("goals", "Goal deadlines this week"),
    ("top", "Top priority in progress"),
    ("blocked", "Blocked"),
)
OPEN = ("planning", "active")
GOAL_WINDOW_DAYS = 7
FREE_LIMIT = 5


def _days(a: str, b: date) -> int:
    """Days from b to the ISO date a (negative = in the past)."""
    return (date.fromisoformat(a) - b).days


def _sort_key(r: dict):
    dates = [d for d in (r["due"], r["do_on"]) if d]
    return (r["priority"], min(dates) if dates else "9999-12-31", str(r["created"]), r["slug"])


def _ago(n: int) -> str:
    return "yesterday" if n == 1 else f"{n} days ago"


def when(r: dict, section: str, today: date, goal_targets: dict) -> str:
    """A short human label for why an entry is in its section."""
    if section == "due" or (section == "blocked" and r["due"]):
        n = _days(r["due"], today)
        if n == 0:
            return "due today"
        if n < 0:
            return f"due {_ago(-n)}" if section == "due" else f"due {r['due']}"
        return f"due in {n}d"
    if section == "planned":
        n = _days(r["do_on"], today)
        return "today" if n == 0 else f"planned {_ago(-n)}"
    if section == "goals":
        n = _days(goal_targets[r["goal"]], today)
        if n == 0:
            return "goal due today"
        return f"goal due in {n}d" if n > 0 else f"goal {-n}d late"
    return ""


def active_goal_targets(goals: list[dict]) -> dict[str, str]:
    return {g["slug"]: g["target"] for g in goals if g["status"] == "active" and g.get("target")}


def build(records: list[dict], goals: list[dict], today: date | None = None,
          area: str | None = None) -> list[dict]:
    """The Today sections: [{key, title, items: [record + {"when": str}]}], empty ones omitted."""
    today = today or date.today()
    t = today.isoformat()
    soon = (today + timedelta(days=GOAL_WINDOW_DAYS)).isoformat()
    targets = active_goal_targets(goals)
    buckets: dict[str, list[dict]] = {key: [] for key, _ in SECTIONS}
    for r in records:
        if r["status"] not in OPEN or (area and r["area"] != area):
            continue
        if r["blocked"]:
            key = "blocked"
        elif r["due"] and r["due"] <= t:
            key = "due"
        elif r["do_on"] and r["do_on"] <= t:
            key = "planned"
        elif r["goal"] in targets and targets[r["goal"]] <= soon:
            key = "goals"
        elif r["status"] == "active" and r["priority"] in ("P1", "P2"):
            key = "top"
        else:
            continue
        buckets[key].append({**r, "when": when(r, key, today, targets)})
    return [{"key": key, "title": title, "items": sorted(buckets[key], key=_sort_key)}
            for key, title in SECTIONS if buckets[key]]


def free(records: list[dict], minutes: int, area: str | None = None,
         limit: int = FREE_LIMIT) -> list[dict]:
    """Open, unblocked entries whose estimate fits in `minutes`, best first.
    Entries without an estimate are never suggested."""
    picks = [r for r in records
             if r["status"] in OPEN and not r["blocked"] and r["est"]
             and r["est"] <= minutes and (not area or r["area"] == area)]
    picks.sort(key=lambda r: (r["priority"], r["due"] or "9999-12-31",
                              r["status"] != "active", str(r["created"]), r["slug"]))
    return picks[:limit]
