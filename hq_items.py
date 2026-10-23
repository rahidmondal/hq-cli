"""Standalone items outside projects (advanced mode): the reading list
(reading/<slug>.md), the inbox (inbox/<date>-<slug>.md) and calendar events
(calendar/<date>-<id>.md). One flat Markdown file each, so classic mode shows
them as plain browsable folders.

Items may carry an `area`; an item without one shows under every area filter."""
import datetime
import re
import secrets
import urllib.parse
from pathlib import Path

import hq_core
import hq_fields
from hq_core import HqError

DIRS = {"reading": "reading", "inbox": "inbox", "event": "calendar"}
READING_STATUSES = ("unread", "read", "dropped")
REPEATS = ("daily", "weekdays", "weekly")
SLUG_MAX = 60
INBOX_STALE_DAYS = 14


def _dir(kind: str) -> Path:
    return hq_core.HQ_ROOT / DIRS[kind]


def _files(kind: str) -> list[Path]:
    d = _dir(kind)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.md") if p.is_file() and not p.name.startswith("."))


def _read(path: Path) -> tuple[dict, str]:
    try:
        return hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}, ""


def _short_slug(text: str) -> str:
    slug = hq_core.slugify(text)[:SLUG_MAX].strip("-")
    return slug


def _free_path(d: Path, stem: str) -> Path:
    path, n = d / f"{stem}.md", 2
    while path.exists():
        path, n = d / f"{stem}-{n}.md", n + 1
    return path


def _area(meta: dict) -> str | None:
    try:
        return hq_fields.parse_area(meta["area"]) if meta.get("area") else None
    except HqError:
        return None


def _write(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hq_core.atomic_write_text(path, hq_core.frontmatter_dump(meta, body))


def in_area(item: dict, area: str | None) -> bool:
    return not area or item.get("area") in (None, area)


def resolve(kind: str, ref: str) -> Path:
    """A file of this kind by exact stem/id, else by unique substring of its
    stem or title slug."""
    text = ref.strip()
    if text.startswith(f"{kind}/"):
        text = text[len(kind) + 1:]
    needle = text.lower()
    files = _files(kind)
    exact = [p for p in files if p.stem == text or _read(p)[0].get("id") == text]
    if len(exact) == 1:
        return exact[0]
    want = hq_core.slugify(needle)

    def title_slug(p: Path) -> str:
        meta, body = _read(p)
        return hq_core.slugify(str(meta.get("title") or hq_core.extract_title(body)))

    matches = exact or [p for p in files if needle and (
        needle in p.stem.lower() or (want and want in title_slug(p)))]
    noun = "event" if kind == "event" else f"{kind} item"
    if not matches:
        raise HqError(f"no {noun} matches '{ref}'")
    if len(matches) > 1:
        raise HqError(f"ambiguous {noun} '{ref}': {', '.join(p.stem for p in matches)}")
    return matches[0]


# ---- reading list -----------------------------------------------------------

def reading_view(path: Path) -> dict:
    meta, body = _read(path)
    status = meta.get("status") if meta.get("status") in READING_STATUSES else "unread"
    try:
        priority = hq_fields.parse_priority(meta.get("priority"))
    except HqError:
        priority = hq_fields.DEFAULT_PRIORITY
    try:
        est = hq_fields.parse_est(meta["est"]) if meta.get("est") else None
    except HqError:
        est = None
    note = "\n".join(l for l in body.splitlines() if not l.startswith("# ")).strip()
    tags = meta.get("tags", [])
    return {
        "type": "reading", "slug": path.stem,
        "title": hq_core.extract_title(body) or meta.get("url") or path.stem,
        "url": meta.get("url") or "", "status": status, "priority": priority, "est": est,
        "added": str(meta.get("added") or ""), "read_on": meta.get("read-on") or None,
        "area": _area(meta), "tags": tags if isinstance(tags, list) else [], "note": note,
        "path": path,
    }


def list_reading(status: str | None = None, area: str | None = None) -> list[dict]:
    items = [reading_view(p) for p in _files("reading")]
    items = [i for i in items if (not status or i["status"] == status) and in_area(i, area)]
    items.sort(key=lambda i: (i["status"] != "unread", i["priority"], i["added"], i["slug"]))
    return items


def _check_url(url: str) -> str:
    url = url.strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HqError(f"not a web link: {url!r} (use http:// or https://)")
    return url


def fetch_enabled() -> bool:
    return hq_core.load_config().get("fetch", True) is not False


def add_reading(url: str, priority: str | None = None, note: str | None = None,
                mins: str | None = None, area: str | None = None, title: str | None = None,
                offline: bool = False, tags: list[str] | None = None) -> tuple[Path, str | None]:
    """Save a link. Returns (path, warning). Fetching the page is best-effort:
    on failure the link is saved anyway with no estimate."""
    url = _check_url(url)
    prio = hq_fields.parse_priority(priority) if priority else hq_fields.DEFAULT_PRIORITY
    est = hq_fields.parse_est(mins) if mins else None
    area = hq_fields.parse_area(area) if area else None
    for item in list_reading():
        if item["url"] == url:
            raise HqError(f"already on the reading list: {item['slug']}")
    warning = None
    if not title and not offline and fetch_enabled():
        import hq_fetch

        try:
            page = hq_fetch.fetch(url)
            title = page["title"] or None
            if est is None:
                est = page["minutes"]
        except Exception as e:  # network, TLS, HTTP or decode errors: save anyway
            warning = f"couldn't fetch the page ({e}); saved without a title or estimate"
    if not title:
        parts = urllib.parse.urlsplit(url)
        title = (parts.netloc + parts.path).rstrip("/")
    slug = _short_slug(title) or _short_slug(url) or "link"
    path = _free_path(_dir("reading"), slug)
    meta = {"kind": "reading", "url": url, "status": "unread", "priority": prio}
    if est:
        meta["est"] = hq_fields.format_est(est)
    if area:
        meta["area"] = area
    meta["added"] = datetime.date.today().isoformat()
    meta["tags"] = tags or []
    body = f"# {_one_line(title)}\n\n" + (f"{note.strip()}\n" if note and note.strip() else "")
    _write(path, meta, body)
    hq_core.log_action("read", op="add", slug=path.stem, url=url)
    return path, warning


def finish_reading(ref: str, dropped: bool = False) -> Path:
    path = resolve("reading", ref)
    meta, body = _read(path)
    status = "dropped" if dropped else "read"
    if meta.get("status") == status:
        raise HqError(f"'{path.stem}' is already {status}")
    meta["status"] = status
    meta["read-on"] = datetime.date.today().isoformat()
    _write(path, meta, body)
    hq_core.log_action("read", op=status, slug=path.stem)
    return path


def set_reading(ref: str, field: str, value: str) -> Path:
    path = resolve("reading", ref)
    if field not in ("priority", "est", "area"):
        raise HqError(f"can't set '{field}' on a reading item (allowed: priority, est, area)")
    meta, body = _read(path)
    clear = value.strip().lower() == "none"
    new = None if clear else hq_fields.normalize(field, value)
    if meta.get(field) == new or (clear and field not in meta):
        return path
    old = meta.pop(field, None)
    if new is not None:
        meta[field] = new
    _write(path, meta, body)
    hq_core.log_action("set", reading=path.stem, field=field, **{"from": old, "to": new})
    return path


# ---- inbox -------------------------------------------------------------------

def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def inbox_view(path: Path) -> dict:
    meta, body = _read(path)
    lines = [l for l in body.splitlines() if not l.startswith("# ")]
    return {
        "type": "inbox", "slug": path.stem,
        "title": hq_core.extract_title(body) or path.stem,
        "added": str(meta.get("added") or path.stem[:10]),
        "area": _area(meta), "note": "\n".join(lines).strip(), "path": path,
    }


def list_inbox(area: str | None = None) -> list[dict]:
    return [i for i in (inbox_view(p) for p in _files("inbox")) if in_area(i, area)]


def dump(text: str, area: str | None = None) -> Path:
    text = _one_line(text or "")
    if not text:
        raise HqError("nothing to capture")
    area = hq_fields.parse_area(area) if area else None
    today = datetime.date.today().isoformat()
    slug = _short_slug(" ".join(text.split()[:8])) or "note"
    path = _free_path(_dir("inbox"), f"{today}-{slug}")
    meta = {"kind": "inbox", "added": today}
    if area:
        meta["area"] = area
    _write(path, meta, f"# {text}\n")
    hq_core.log_action("dump", slug=path.stem, text=text)
    return path


_URL_RE = re.compile(r"https?://\S+")


def take_inbox(ref: str) -> dict:
    """The inbox item for a ref (triage reads it, then removes it)."""
    return inbox_view(resolve("inbox", ref))


def remove_inbox(path: Path, to: str, target: str | None = None) -> None:
    slug = path.stem
    path.unlink()
    hq_core.log_action("triage", slug=slug, to=to, target=target)


def split_link(text: str) -> tuple[str | None, str]:
    """(first http(s) URL in text, the rest of the text)."""
    m = _URL_RE.search(text)
    if not m:
        return None, text
    rest = _one_line(text[: m.start()] + " " + text[m.end():])
    return m.group(0).rstrip(".,);]"), rest


def stale_inbox(today: datetime.date | None = None) -> list[dict]:
    today = today or datetime.date.today()
    out = []
    for item in list_inbox():
        try:
            age = (today - datetime.date.fromisoformat(item["added"])).days
        except ValueError:
            continue
        if age > INBOX_STALE_DAYS:
            out.append({**item, "age": age})
    return out


# ---- calendar events ---------------------------------------------------------

_TIME_RE = re.compile(r"\A([01]?[0-9]|2[0-3]):([0-5][0-9])\Z")
_DUR_RE = re.compile(r"\A\+?(?:([0-9]+)h)?(?:([0-9]+)m)?\Z")


def _now_local() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_time(t: str) -> str | None:
    m = _TIME_RE.match(t.strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def parse_when(text: str, base: datetime.date | None = None) -> tuple[str, str | None]:
    """'2026-10-23T10:00', '2026-10-23 10:00', 'tomorrow 10:00', '+1d 9:30',
    '10:00' (on base, default today) or a bare date (all day) ->
    (YYYY-MM-DD, HH:MM or None)."""
    t = text.strip().replace("T", " ", 1) if re.match(r"\A\d{4}-\d{2}-\d{2}T", text.strip()) else text.strip()
    parts = t.split()
    if len(parts) == 1 and _parse_time(parts[0]):
        return (base or datetime.date.today()).isoformat(), _parse_time(parts[0])
    if len(parts) == 1:
        return hq_fields.parse_date(parts[0]), None
    if len(parts) == 2 and _parse_time(parts[1]):
        return hq_fields.parse_date(parts[0]), _parse_time(parts[1])
    raise HqError(f"bad time {text!r} (use YYYY-MM-DD HH:MM, today 10:00, +1d 9:30 or HH:MM)")


def _add_minutes(day: str, hhmm: str, minutes: int) -> tuple[str, str]:
    dt = datetime.datetime.fromisoformat(f"{day}T{hhmm}") + datetime.timedelta(minutes=minutes)
    return dt.date().isoformat(), dt.strftime("%H:%M")


def parse_span(start: str, end: str | None) -> tuple[str, str]:
    """(start, end) as stored: 'YYYY-MM-DDTHH:MM' or, all day, 'YYYY-MM-DD'.
    end may be a time on the start day, a duration ('30m', '+1h') or a full time."""
    sday, stime = parse_when(start)
    if end is None or not end.strip():
        if stime is None:
            return sday, sday
        eday, etime = _add_minutes(sday, stime, 30)
        return f"{sday}T{stime}", f"{eday}T{etime}"
    e = end.strip()
    dur = _DUR_RE.match(e.lower())
    if stime and dur and (dur.group(1) or dur.group(2)) and not _parse_time(e):
        minutes = int(dur.group(1) or 0) * 60 + int(dur.group(2) or 0)
        eday, etime = _add_minutes(sday, stime, minutes)
    else:
        eday, etime = parse_when(e, base=datetime.date.fromisoformat(sday))
    if (stime is None) != (etime is None):
        raise HqError("start and end must both have a time, or both be dates (all day)")
    s = f"{sday}T{stime}" if stime else sday
    en = f"{eday}T{etime}" if etime else eday
    if en < s:
        raise HqError(f"end {en} is before start {s}")
    return s, en


def event_view(path: Path) -> dict | None:
    meta, body = _read(path)
    start, end = str(meta.get("start") or ""), str(meta.get("end") or "")
    try:
        sday = datetime.date.fromisoformat(start[:10])
        eday = datetime.date.fromisoformat(end[:10]) if end else sday
    except ValueError:
        return None
    repeat = meta.get("repeat") if meta.get("repeat") in REPEATS else None
    title = str(meta.get("title") or hq_core.extract_title(body) or path.stem)
    return {
        "type": "event", "slug": path.stem, "id": str(meta.get("id") or path.stem),
        "title": title, "start": start, "end": end or start,
        "all_day": len(start) == 10, "span_days": (eday - sday).days,
        "repeat": repeat, "source": meta.get("source") or "hq", "area": _area(meta),
        "notes": body.strip(), "path": path,
    }


def list_events(area: str | None = None) -> list[dict]:
    out = [e for e in (event_view(p) for p in _files("event")) if e and in_area(e, area)]
    out.sort(key=lambda e: (e["start"], e["title"]))
    return out


def _repeats_on(e: dict, day: datetime.date) -> bool:
    first = datetime.date.fromisoformat(e["start"][:10])
    if day < first:
        return False
    if day == first:
        return True
    if e["repeat"] == "daily":
        return True
    if e["repeat"] == "weekdays":
        return day.weekday() < 5
    if e["repeat"] == "weekly":
        return (day - first).days % 7 == 0
    return False


def occurrences(start: datetime.date, end: datetime.date, area: str | None = None) -> list[dict]:
    """Every event occurrence from start to end inclusive, by date then time.
    Each is the event plus {date, time, end_time} (times None when all day)."""
    out = []
    events = list_events(area)
    day = start
    while day <= end:
        for e in events:
            first = datetime.date.fromisoformat(e["start"][:10])
            if e["repeat"]:
                hit = _repeats_on(e, day)
            else:
                hit = first <= day <= first + datetime.timedelta(days=e["span_days"])
            if hit:
                out.append({**e, "date": day.isoformat(),
                            "time": None if e["all_day"] else e["start"][11:16],
                            "end_time": None if e["all_day"] else e["end"][11:16]})
        day += datetime.timedelta(days=1)
    out.sort(key=lambda o: (o["date"], o["time"] or "", o["title"]))
    return out


def add_event(title: str, start: str, end: str | None = None, repeat: str | None = None,
              area: str | None = None, notes: str | None = None, source: str = "hq") -> Path:
    title = _one_line(title or "")
    if not title:
        raise HqError("event title is empty")
    if repeat and repeat not in REPEATS:
        raise HqError(f"bad repeat {repeat!r} (use {', '.join(REPEATS)})")
    area = hq_fields.parse_area(area) if area else None
    s, e = parse_span(start, end)
    eid = secrets.token_hex(4)
    path = _free_path(_dir("event"), f"{s[:10]}-{eid}")
    meta = {"kind": "event", "id": eid, "title": title, "start": s, "end": e,
            "repeat": repeat or "", "source": source}
    if area:
        meta["area"] = area
    meta["updated"] = _now_local()
    _write(path, meta, f"{notes.strip()}\n" if notes and notes.strip() else "")
    hq_core.log_action("event", op="add", id=eid, title=title, start=s)
    return path


def remove_event(ref: str) -> dict:
    path = resolve("event", ref)
    e = event_view(path) or {"id": path.stem, "title": path.stem}
    path.unlink()
    hq_core.log_action("event", op="rm", id=e["id"], title=e["title"])
    return e


def _ics_text(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return [out[0]] + [" " + p for p in out[1:]]


def _ics_dt(value: str, prop: str, end: bool = False) -> str:
    if len(value) == 10:
        d = datetime.date.fromisoformat(value)
        if end:
            d += datetime.timedelta(days=1)  # DTEND of an all-day event is exclusive
        return f"{prop};VALUE=DATE:{d.strftime('%Y%m%d')}"
    return f"{prop}:{value.replace('-', '').replace(':', '')}00"


_RRULE = {"daily": "FREQ=DAILY", "weekly": "FREQ=WEEKLY",
          "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"}


def export_ics() -> tuple[Path, int]:
    """Write HQ_ROOT/calendar.ics (floating local times). Returns (path, count)."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//hq//calendar//EN", "CALSCALE:GREGORIAN"]
    events = list_events()
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@hq", f"DTSTAMP:{stamp}",
                  _ics_dt(e["start"], "DTSTART"), _ics_dt(e["end"], "DTEND", end=True),
                  f"SUMMARY:{_ics_text(e['title'])}"]
        if e["repeat"]:
            lines.append(f"RRULE:{_RRULE[e['repeat']]}")
        if e["notes"]:
            lines.append(f"DESCRIPTION:{_ics_text(e['notes'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded = [part for line in lines for part in _fold(line)]
    path = hq_core.HQ_ROOT / "calendar.ics"
    path.write_bytes(("\r\n".join(folded) + "\r\n").encode("utf-8"))
    return path, len(events)
