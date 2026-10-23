"""Days (advanced mode): the static bundle of what happened on a local date
(`hq day`), the saved end-of-day file days/<date>.md (`hq day end`), and the
week/month timeline. No AI: agents add prose through --summary-file.

A day file has three fixed sections:
  ## Summary   replaced on rerun only by a new --summary-file, or by a fresh
               template when the existing summary was itself templated
  ## My notes  never rewritten; --summary appends a line (no duplicates)
  ## Facts     regenerated every time from the bundle"""
import calendar
import html
import datetime
import re
import subprocess
from pathlib import Path

import hq_core
import hq_items
import hq_ops
import hq_registry
from hq_core import HqError

TEMPLATE_MARK = "<!-- hq:template -->"
SECTIONS = ("Summary", "My notes", "Facts")
_GIT_TIMEOUT = 15


def day_path(day: str) -> Path:
    return hq_core.HQ_ROOT / "days" / f"{day}.md"


def parse_day(text: str | None) -> datetime.date:
    if not text:
        return datetime.date.today()
    import hq_fields

    return datetime.date.fromisoformat(hq_fields.parse_date(text))


def _local(ts: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(ts).astimezone()
    except (TypeError, ValueError):
        return None


# ---- what happened ----------------------------------------------------------

def _describe(e: dict) -> str:
    a = e.get("action")
    if a == "save":
        return f"saved ({e.get('kind')})"
    if a == "start":
        return "started"
    if a == "archive":
        return "dropped" if e.get("outcome") == "dropped" else "finished"
    if a == "unstart":
        return "moved back to planning" + (f": {e['reason']}" if e.get("reason") else "")
    if a == "block":
        return f"blocked: {e.get('reason')}"
    if a == "unblock":
        return "unblocked"
    if a == "set":
        frm = e.get("from") if e.get("from") is not None else "-"
        to = e.get("to") if e.get("to") is not None else "-"
        return f"{e.get('field')} {frm} → {to}"
    if a == "note":
        return f"note: {e.get('text')}"
    if a == "goal":
        return {"new": "goal created", "done": "goal done", "dropped": "goal dropped"}.get(e.get("op"), "goal")
    if a == "read":
        return {"add": "saved link", "read": "read", "dropped": "dropped link"}.get(e.get("op"), "read")
    if a == "dump":
        return "captured"
    if a == "triage":
        return f"triaged to {e.get('to')}"
    if a == "event":
        return f"event {'added' if e.get('op') == 'add' else 'removed'}: {e.get('title')}"
    if a == "project-set":
        return f"project {e.get('field')} → {e.get('value')}"
    if a == "artifact":
        return f"artifact {e.get('file')}"
    return str(a)


class _Context:
    """Lookups to label log lines: entry titles/areas/goals, goal titles, links."""

    def __init__(self):
        self.entries = {(r["project"], r["slug"]): r for r in hq_ops.entry_records()}
        self.goals = {g["slug"]: g for g in hq_registry.list_goals()}
        self.reading = {i["slug"]: i for i in hq_items.list_reading()}
        try:
            self.registry = hq_registry.load_projects()
        except HqError:
            self.registry = {}

    def place(self, e: dict) -> tuple[str | None, str | None, str | None, str | None]:
        """(area, group, item title, ref) for an entry/goal log line, else Nones."""
        if e.get("action") == "goal" or (e.get("goal") and not e.get("slug")):
            slug = e.get("goal") or e.get("slug")
            g = self.goals.get(slug)
            title = g["title"] if g else slug
            return (g["area"] if g else "work"), f"goal: {title}", "(the goal itself)", f"goal/{slug}"
        project, slug = e.get("project"), e.get("slug")
        if not project or not slug:
            return None, None, None, None
        r = self.entries.get((project, slug))
        if r is None:
            return hq_registry.project_area(project, self.registry), project, slug, f"{project}/{slug}"
        if r["goal"] and r["goal"] in self.goals:
            group = f"goal: {self.goals[r['goal']]['title']}"
        else:
            group = project
        return r["area"], group, r["title"], f"{project}/{slug}"


def _lines_between(start: datetime.date, end: datetime.date) -> list[tuple[datetime.datetime, dict]]:
    out = []
    for e in hq_core.read_log():
        when = _local(e.get("ts", ""))
        if when and start <= when.date() <= end:
            out.append((when, e))
    return out


def _repos() -> list[tuple[str, str]]:
    try:
        registry = hq_registry.load_projects()
    except HqError:
        return []
    seen, out = set(), []
    for project, rec in sorted(registry.items()):
        repos = rec.get("repos") if isinstance(rec, dict) else None
        for repo in repos if isinstance(repos, list) else []:
            if isinstance(repo, str) and repo not in seen:
                seen.add(repo)
                out.append((project, repo))
    return out


def _git(repo: str, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=_GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def commits(start: datetime.date, end: datetime.date) -> list[dict]:
    """Your commits (author = each repo's user.email) in every recorded repo, all branches."""
    out = []
    until = end + datetime.timedelta(days=1)
    for project, repo in _repos():
        if not Path(repo).is_dir():
            continue
        email = (_git(repo, "config", "user.email") or "").strip()
        if not email:
            continue
        log = _git(repo, "log", "--all", "--no-merges", f"--author={email}",
                   f"--since={start.isoformat()} 00:00", f"--until={until.isoformat()} 00:00",
                   "--date=format:%Y-%m-%d %H:%M", "--format=%h%x1f%ad%x1f%s")
        for line in (log or "").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                day, _, time = parts[1].partition(" ")
                out.append({"project": project, "repo": repo, "hash": parts[0],
                            "date": day, "time": time, "subject": parts[2]})
    out.sort(key=lambda c: (c["date"], c["time"], c["project"]))
    return out


def bundle(day: datetime.date, with_git: bool = True) -> dict:
    """Everything recorded on a local date, grouped by area -> goal/project -> item."""
    ctx = _Context()
    lines = _lines_between(day, day)
    areas: dict[str, dict[str, dict[str, dict]]] = {}
    counts = {k: [] for k in ("saved", "started", "finished", "dropped", "blocked", "unblocked")}
    reading, inbox, notes = [], [], 0
    flat = []
    for when, e in lines:
        a = e.get("action")
        if a == "day-end":
            continue
        text = _describe(e)
        row = {"time": when.strftime("%H:%M"), "action": a, "text": text, "by": e.get("by")}
        if a == "read":
            item = ctx.reading.get(e.get("slug"))
            reading.append({**row, "slug": e.get("slug"), "op": e.get("op"),
                            "title": item["title"] if item else e.get("slug")})
            flat.append({**row, "ref": f"reading/{e.get('slug')}"})
            continue
        if a in ("dump", "triage"):
            inbox.append({**row, "slug": e.get("slug"), "title": e.get("text") or e.get("target") or e.get("slug")})
            flat.append({**row, "ref": f"inbox/{e.get('slug')}"})
            continue
        area, group, title, ref = ctx.place(e)
        if group is None:
            flat.append({**row, "ref": None})
            continue
        items = areas.setdefault(area or "work", {}).setdefault(group, {})
        item = items.setdefault(ref, {"title": title, "ref": ref, "lines": []})
        item["lines"].append(row)
        flat.append({**row, "ref": ref, "area": area, "group": group, "title": title})
        notes += a == "note"
        key = {"save": "saved", "start": "started", "block": "blocked", "unblock": "unblocked"}.get(a)
        if a == "archive":
            key = "dropped" if e.get("outcome") == "dropped" else "finished"
        if key and ref:
            counts[key].append({"ref": ref, "title": title})
    events = hq_items.occurrences(day, day)
    return {
        "date": day.isoformat(),
        "areas": [{"area": area, "groups": [
            {"group": g, "items": list(items.values())} for g, items in sorted(groups.items())]}
            for area, groups in sorted(areas.items())],
        **counts,
        "notes": notes,
        "reading": reading,
        "inbox": inbox,
        "commits": commits(day, day) if with_git else [],
        "events": [{k: o.get(k) for k in ("title", "time", "end_time", "area", "id", "start", "end",
                                          "repeat", "until", "all_day", "span_days", "notes")}
                   for o in events],
        "lines": flat,
    }


# ---- rendering ---------------------------------------------------------------

def _titles(items: list[dict], n: int = 4) -> str:
    names = [f"\"{_md(i['title'])}\"" for i in items[:n]]
    more = len(items) - n
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")


def template_summary(b: dict) -> str:
    parts = []
    for key, verb in (("finished", "Finished"), ("started", "started"), ("dropped", "dropped"),
                      ("blocked", "blocked")):
        if b[key]:
            parts.append(f"{verb} {len(b[key])}")
    if parts:
        parts[0] = parts[0][0].upper() + parts[0][1:]
    extra = []
    if b["commits"]:
        extra.append(f"{len(b['commits'])} commit{'s' if len(b['commits']) != 1 else ''}")
    read = [r for r in b["reading"] if r["op"] == "read"]
    if read:
        extra.append(f"read {len(read)} link{'s' if len(read) != 1 else ''}")
    if b["notes"]:
        extra.append(f"{b['notes']} note{'s' if b['notes'] != 1 else ''}")
    head = ", ".join(parts + extra)
    if not head:
        return f"{TEMPLATE_MARK}\nNothing recorded."
    out = [TEMPLATE_MARK, head[0].upper() + head[1:] + "."]
    by_area: dict[str, list[str]] = {}
    for area in b["areas"]:
        for g in area["groups"]:
            done = [i for i in g["items"] if any(l["action"] == "archive" and l["text"] == "finished"
                                                 for l in i["lines"])]
            started = [i for i in g["items"] if any(l["action"] == "start" for l in i["lines"])]
            bits = []
            if done:
                bits.append(f"finished {_titles(done)}")
            if started:
                bits.append(f"started {_titles(started)}")
            if not bits:
                n = sum(len(i["lines"]) for i in g["items"])
                bits.append(f"{n} update{'s' if n != 1 else ''}")
            by_area.setdefault(area["area"], []).append(f"{_md(g['group'])}: {'; '.join(bits)}")
    if by_area:
        out.append("")
        for area, rows in by_area.items():
            out.append(f"- **{area.capitalize()}**: " + " · ".join(rows))
    return "\n".join(out)


def _md(text) -> str:
    """Escape text going into Markdown that the app renders as HTML."""
    return html.escape(str(text), quote=False)


def facts_markdown(b: dict) -> str:
    out = []
    for area in b["areas"]:
        out.append(f"### {area['area'].capitalize()}")
        for g in area["groups"]:
            out.append(f"**{_md(g['group'])}**")
            for item in g["items"]:
                for line in item["lines"]:
                    label = item["title"] if item["title"] != "(the goal itself)" else "goal"
                    out.append(f"- {line['time']} {_md(label)}: {_md(line['text'])}")
            out.append("")
    if b["commits"]:
        out.append("### Commits")
        for c in b["commits"]:
            out.append(f"- {c['time']} {_md(c['project'])} `{c['hash']}` {_md(c['subject'])}")
        out.append("")
    if b["reading"]:
        out.append("### Reading")
        for r in b["reading"]:
            out.append(f"- {r['time']} {_md(r['text'])}: {_md(r['title'])}")
        out.append("")
    if b["inbox"]:
        out.append("### Inbox")
        for r in b["inbox"]:
            out.append(f"- {r['time']} {_md(r['text'])}: {_md(r['title'])}")
        out.append("")
    if b["events"]:
        out.append("### Calendar")
        for e in b["events"]:
            when = f"{e['time']}–{e['end_time']}" if e["time"] else "all day"
            out.append(f"- {when} {_md(e['title'])}")
        out.append("")
    return "\n".join(out).strip() or "Nothing recorded."


def split_sections(body: str) -> tuple[str, dict[str, str]]:
    """(text before the first '## ' heading, {heading: content}) in order."""
    pre, sections, current = [], {}, None
    for line in body.splitlines():
        m = re.match(r"\A## (.+?)\s*\Z", line)
        if m:
            current = m.group(1)
            sections[current] = []
        elif current is None:
            pre.append(line)
        else:
            sections[current].append(line)
    return "\n".join(pre), {k: "\n".join(v).strip("\n") for k, v in sections.items()}


def read_day(day: str) -> dict | None:
    """{date, summary, notes, facts, templated, updated, path} or None."""
    path = day_path(day)
    if not path.is_file():
        return None
    try:
        meta, body = hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    _, sections = split_sections(body)
    summary = sections.get("Summary", "")
    return {
        "date": day, "summary": summary.replace(TEMPLATE_MARK, "").strip(),
        "templated": TEMPLATE_MARK in summary, "notes": sections.get("My notes", "").strip(),
        "facts": sections.get("Facts", "").strip(), "updated": meta.get("updated"), "path": path,
    }


def end_day(day: datetime.date, summary_text: str | None = None,
            summary_file: str | None = None) -> tuple[Path, dict]:
    """Write days/<date>.md (rules in the module docstring). Returns (path, bundle)."""
    prose = None
    if summary_file:
        try:
            prose = Path(summary_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as e:
            raise HqError(f"can't read summary file {summary_file}: {e}")
        if not prose:
            raise HqError(f"summary file {summary_file} is empty")
    b = bundle(day)
    path = day_path(day.isoformat())
    extra: dict[str, str] = {}
    notes = ""
    summary = None
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise HqError(f"can't read {path}: {e}")
        _, body = hq_core.frontmatter_parse(text)
        _, sections = split_sections(body)
        notes = sections.pop("My notes", "").strip()
        old = sections.pop("Summary", "")
        sections.pop("Facts", None)
        extra = sections
        if old.strip() and TEMPLATE_MARK not in old:
            summary = old.strip()
    if prose is not None:
        summary = prose
    if summary is None:
        summary = template_summary(b)
    if summary_text and summary_text.strip():
        line = "- " + re.sub(r"\s+", " ", summary_text).strip()
        if line not in notes.splitlines():
            notes = (notes + "\n" + line).strip()
    meta = {"kind": "day", "date": day.isoformat(),
            "updated": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    parts = [f"# {day.isoformat()}", "", "## Summary", "", summary, "", "## My notes", ""]
    if notes:
        parts += [notes, ""]
    parts += ["## Facts", "", facts_markdown(b), ""]
    for heading, content in extra.items():
        parts += [f"## {heading}", "", content, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    hq_core.atomic_write_text(path, hq_core.frontmatter_dump(meta, "\n".join(parts)))
    hq_core.log_action("day-end", date=day.isoformat())
    return path, b


# ---- timeline ----------------------------------------------------------------

def week_range(day: datetime.date) -> tuple[datetime.date, datetime.date]:
    start = day - datetime.timedelta(days=day.weekday())
    return start, start + datetime.timedelta(days=6)


def month_range(day: datetime.date) -> tuple[datetime.date, datetime.date]:
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def timeline(start: datetime.date, end: datetime.date, with_git: bool = True) -> dict:
    """Per-day counts and saved summaries, plus finished/started work grouped
    by area -> goal/project, for start..end inclusive."""
    ctx = _Context()
    days = {}
    d = start
    while d <= end:
        days[d.isoformat()] = {"date": d.isoformat(), "finished": 0, "started": 0, "notes": 0,
                               "actions": 0, "commits": 0, "summary": None}
        d += datetime.timedelta(days=1)
    groups: dict[tuple[str, str], dict] = {}
    for when, e in _lines_between(start, end):
        a = e.get("action")
        if a == "day-end":
            continue
        row = days[when.date().isoformat()]
        row["actions"] += 1
        area, group, title, ref = ctx.place(e)
        if a == "archive" and e.get("outcome") != "dropped":
            row["finished"] += 1
        elif a == "start":
            row["started"] += 1
        elif a == "note":
            row["notes"] += 1
        if group is None:
            continue
        g = groups.setdefault((area or "work", group), {"area": area or "work", "group": group,
                                                        "finished": [], "started": [], "actions": 0})
        g["actions"] += 1
        if a == "archive" and e.get("outcome") != "dropped" and title not in g["finished"]:
            g["finished"].append(title)
        elif a == "start" and title not in g["started"]:
            g["started"].append(title)
    if with_git:
        for c in commits(start, end):
            if c["date"] in days:
                days[c["date"]]["commits"] += 1
    for key, row in days.items():
        saved = read_day(key)
        if saved and saved["summary"]:
            row["summary"] = saved["summary"]
    total = {k: sum(r[k] for r in days.values()) for k in ("finished", "started", "notes", "commits")}
    return {"start": start.isoformat(), "end": end.isoformat(), "total": total,
            "days": list(days.values()),
            "groups": sorted(groups.values(), key=lambda g: (g["area"], -g["actions"], g["group"]))}


def first_line(summary: str | None) -> str:
    for line in (summary or "").splitlines():
        line = line.strip().lstrip("-* ").strip()
        if line:
            return re.sub(r"\*\*(.+?)\*\*", r"\1", line)
    return ""


# ---- activity feed and lanes (the Timeline page) ------------------------------

MAX_RANGE_DAYS = 400


def check_range(start: datetime.date, end: datetime.date) -> None:
    if start > end:
        raise HqError("the end date must be on or after the start date")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise HqError(f"choose a range of {MAX_RANGE_DAYS} days or less")


def activity(start: datetime.date, end: datetime.date) -> list[dict]:
    """Every logged action from start to end inclusive, newest first, labelled
    with its item, area and goal/project so the browser can group and filter."""
    check_range(start, end)
    ctx = _Context()
    out = []
    for when, e in _lines_between(start, end):
        a = e.get("action")
        if a == "day-end":
            continue
        row = {"at": when.strftime("%Y-%m-%dT%H:%M"), "date": when.date().isoformat(),
               "time": when.strftime("%H:%M"), "action": a, "text": _describe(e), "by": e.get("by"),
               "project": None, "slug": None, "goal": None, "area": None}
        if a == "read":
            item = ctx.reading.get(e.get("slug"))
            row.update(kind="reading", group="Reading", title=item["title"] if item else e.get("slug"),
                       area=item["area"] if item else None, url=item["url"] if item else None)
        elif a in ("dump", "triage"):
            row.update(kind="inbox", group="Inbox", title=e.get("text") or e.get("target") or e.get("slug"))
        elif a == "event":
            row.update(kind="event", group="Calendar", title=e.get("title") or e.get("id"))
        else:
            area, group, title, ref = ctx.place(e)
            if group is None:
                row.update(kind="other", group="Other", title=a)
            elif ref and ref.startswith("goal/"):
                row.update(kind="goal", group=group, title=title if title != "(the goal itself)" else group[6:],
                           goal=ref[5:], area=area)
            else:
                row.update(kind="entry", group=group, title=title, area=area,
                           project=e.get("project"), slug=e.get("slug"))
        out.append(row)
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def lanes(start: datetime.date, end: datetime.date) -> list[dict]:
    """One lane per project and per goal: from its first entry (or creation)
    to its target, or else its last activity, with the days it saw activity
    inside start..end."""
    check_range(start, end)
    records = hq_ops.entry_records()
    goals = hq_registry.list_goals()
    try:
        registry = hq_registry.load_projects()
    except HqError:
        registry = {}
    by_ref = {(r["project"], r["slug"]): r for r in records}
    last: dict[str, str] = {}
    days: dict[str, set] = {}
    for e in hq_core.read_log():
        when = _local(e.get("ts", ""))
        if not when:
            continue
        d = when.date().isoformat()
        keys = []
        if e.get("project"):
            keys.append("p:" + e["project"])
        goal = e.get("goal") or (e.get("slug") if e.get("action") == "goal" else None)
        if goal:
            keys.append("g:" + goal)
        rec = by_ref.get((e.get("project"), e.get("slug")))
        if rec and rec["goal"]:
            keys.append("g:" + rec["goal"])
        for k in keys:
            last[k] = max(last.get(k, d), d)
            if start.isoformat() <= d <= end.isoformat():
                days.setdefault(k, set()).add(d)
    out = []
    for project in sorted({r["project"] for r in records}):
        mine = [r for r in records if r["project"] == project]
        created = min((str(r["created"]) for r in mine if r["created"]), default=None)
        k = "p:" + project
        first = created or last.get(k)
        if not first:
            continue
        out.append({"kind": "project", "id": project, "title": project,
                    "area": hq_registry.project_area(project, registry),
                    "start": first[:10], "end": max(last.get(k, first[:10]), first[:10]), "target": None,
                    "open": sum(r["status"] != "archive" for r in mine),
                    "closed": all(r["status"] == "archive" for r in mine),
                    "days": sorted(days.get(k, ()))})
    for g in goals:
        k = "g:" + g["slug"]
        first = str(g["created"] or last.get(k) or "")[:10]
        if not first:
            continue
        end_day = g["target"] or last.get(k, first)
        out.append({"kind": "goal", "id": g["slug"], "title": g["title"], "area": g["area"],
                    "start": first, "end": max(end_day, first), "target": g["target"],
                    "open": None, "closed": g["status"] != "active", "days": sorted(days.get(k, ()))})
    out.sort(key=lambda l: (l["closed"], l["kind"] != "goal", -len(l["days"]), l["title"]))
    return out
