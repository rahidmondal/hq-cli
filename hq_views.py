"""Advanced-mode daily-loop commands: today, free, read, dump, inbox, triage,
day, week, month, cal, artifact. All advanced-only; every read command takes --json."""
import datetime
import json
import sys

import hq_core
import hq_fields
import hq_term
from hq_core import HqError

AREA_SHORT = {"work": "work", "personal": "pers", None: "·"}
SECTION_LABELS = {"calendar": "calendar", "due": "overdue / due today", "planned": "planned for today",
                  "goals": "goal deadlines this week", "top": "top priority", "blocked": "blocked",
                  "reading": "reading"}


def _need(what: str) -> None:
    import hq

    hq.require_advanced(what)


def _jsonable(item: dict, **extra) -> str:
    out = {k: (str(v) if k == "path" else v) for k, v in item.items()}
    return json.dumps({**out, **extra}, default=str)


def _area_opt(value):
    return hq_fields.parse_area(value) if value else None


def _est(m) -> str:
    return hq_fields.format_est(m) if m else ""


def _ref(item: dict) -> str:
    t = item.get("type")
    if t == "event":
        return item["id"]
    if t in ("reading", "inbox"):
        return item["slug"]
    return item["slug"]


def _title(item: dict) -> str:
    if item.get("blocked"):
        return f"{item['title']}  [blocked: {item['blocked']}]"
    return item["title"]


# ---- today / free --------------------------------------------------------------

def today_sections(area: str | None = None, day: datetime.date | None = None) -> list[dict]:
    import hq_items
    import hq_ops
    import hq_registry
    import hq_today

    day = day or datetime.date.today()
    return hq_today.build(hq_ops.entry_records(), hq_registry.list_goals(), day, area=area,
                          events=hq_items.occurrences(day, day),
                          reading=hq_items.list_reading(status="unread"))


def cmd_today(args):
    _need("today")
    area = _area_opt(args.area)
    day = datetime.date.today()
    sections = today_sections(area, day)
    if args.json:
        for s in sections:
            for item in s["items"]:
                print(_jsonable(item, section=s["key"]))
        return
    entries = [i for s in sections if s["key"] not in ("calendar", "reading") for i in s["items"]]
    blocked = sum(1 for i in entries if i.get("blocked"))
    by_area = {}
    for i in entries:
        if not i.get("blocked"):
            by_area[i["area"]] = by_area.get(i["area"], 0) + 1
    bits = [f"{a} {n}" for a, n in sorted(by_area.items())] + ([f"{blocked} blocked"] if blocked else [])
    head = f"TODAY  {day.strftime('%a')} {day.isoformat()}"
    summary = " · ".join(bits)
    if not hq_term._encodable("·"):
        summary = summary.replace("·", "|")
    if not sections:
        print(head + ("  " + summary if summary else ""))
        print("nothing due, planned or in progress. `hq list` shows everything.")
        return
    rows = []
    for s in sections:
        rows.append(SECTION_LABELS[s["key"]])
        for i in s["items"]:
            prio = "" if i.get("type") == "event" else i["priority"]
            rows.append((prio, AREA_SHORT.get(i.get("area"), i.get("area") or "·"),
                         _ref(i), _title(i), i.get("when", ""), _est(i.get("est"))))
    body = hq_term.table(("P", "AREA", "REF", "TITLE", "WHEN", "EST"), rows, flex=3,
                         styles={0: hq_term.priority_style})
    span = max(len(head) + len(summary) + 2, max(len(l) for l in body.splitlines()[:1]))
    print(head + summary.rjust(span - len(head)) if summary else head)
    print(body)


def cmd_free(args):
    _need("free")
    import hq_items
    import hq_ops
    import hq_today

    area = _area_opt(args.area)
    if args.time:
        minutes, why = hq_fields.parse_est(args.time), ""
    else:
        today = datetime.date.today()
        gap = hq_today.minutes_until_next(hq_items.occurrences(today, today))
        if gap:
            minutes, why = gap, " (until your next event)"
        else:
            minutes, why = hq_today.DEFAULT_FREE_MINUTES, ""
    picks = hq_today.free(hq_ops.entry_records(), minutes, area=area,
                          reading=hq_items.list_reading(status="unread"))
    if args.json:
        for p in picks:
            print(_jsonable(p, type=p.get("type", "entry"), minutes=minutes))
        return
    if not picks:
        print(f"nothing with an estimate fits in {hq_fields.format_est(minutes)}{why}. "
              "Add estimates with `hq set <ref> est 20m`.")
        return
    print(f"FREE  {hq_fields.format_est(minutes)}{why}")
    print(hq_term.table(
        ("P", "AREA", "TYPE", "REF", "TITLE", "EST"),
        [(p["priority"], AREA_SHORT.get(p.get("area"), "·"), p.get("type") or p.get("kind") or "entry",
          p["slug"], p["title"], _est(p["est"])) for p in picks],
        flex=4, styles={0: hq_term.priority_style}))


# ---- reading -------------------------------------------------------------------

def cmd_read(args):
    _need("read")
    import hq_items

    words = args.words
    head = words[0]
    if head == "list":
        status = None if args.all else (args.status or "unread")
        items = hq_items.list_reading(status=status, area=_area_opt(args.area))
        if args.json:
            for i in items:
                print(_jsonable(i))
            return
        if not items:
            print("(reading list is empty)" if status in (None, "unread") else f"(no {status} links)")
            return
        print(hq_term.table(
            ("P", "STATUS", "EST", "AREA", "REF", "TITLE"),
            [(i["priority"], i["status"], _est(i["est"]), AREA_SHORT.get(i["area"], "·"),
              i["slug"], i["title"]) for i in items],
            flex=5, styles={0: hq_term.priority_style}))
        return
    if head in ("done", "drop"):
        if len(words) != 2:
            raise HqError(f"usage: hq read {head} <ref>")
        print(hq_items.finish_reading(words[1], dropped=head == "drop" or args.dropped))
        return
    if head == "set":
        if len(words) != 4:
            raise HqError("usage: hq read set <ref> <priority|est|area> <value>")
        print(hq_items.set_reading(words[1], words[2], words[3]))
        return
    if len(words) != 1:
        raise HqError("usage: hq read <url> | hq read list | hq read done <ref> | hq read drop <ref>")
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    path, warning = hq_items.add_reading(head, priority=args.priority, note=args.note,
                                         mins=args.mins, area=args.area, title=args.title,
                                         offline=args.offline, tags=tags)
    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    print(path)


# ---- inbox ---------------------------------------------------------------------

def cmd_dump(args):
    _need("dump")
    import hq_items

    print(hq_items.dump(" ".join(args.text), area=args.area))


def cmd_inbox(args):
    _need("inbox")
    import hq_items

    items = hq_items.list_inbox(area=_area_opt(args.area))
    if args.json:
        for i in items:
            print(_jsonable(i))
        return
    if not items:
        print("(inbox is empty)")
        return
    print(hq_term.table(("ADDED", "AREA", "REF", "TEXT"),
                        [(i["added"], AREA_SHORT.get(i["area"], "·"), i["slug"], i["title"])
                         for i in items], flex=3))


TRIAGE_TO = (*hq_core.KINDS, "goal", "reading", "drop")


def cmd_triage(args):
    _need("triage")
    import hq
    import hq_items

    item = hq_items.take_inbox(args.ref)
    text = item["title"]
    to = args.to
    if to == "drop":
        hq_items.remove_inbox(item["path"], "drop")
        print(f"dropped {item['slug']}")
        return
    if to == "reading":
        url, rest = hq_items.split_link(text)
        if not url:
            raise HqError(f"'{item['slug']}' has no http(s) link to save")
        path, warning = hq_items.add_reading(url, priority=args.priority, note=rest or None,
                                             mins=args.est, area=args.area or item["area"])
        if warning:
            print(f"warning: {warning}", file=sys.stderr)
    elif to == "goal":
        import hq_registry

        path = hq_registry.create_goal(text, area=args.area or item["area"] or "work",
                                       target=args.target, priority=args.priority)
    else:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        raw = {"priority": args.priority, "goal": args.goal, "due": args.due,
               "do-on": args.do_on, "est": args.est,
               "area": args.area or (item["area"] if to not in ("learning", "skill") else None)}
        path = hq.save_entry(to, text, project=args.project, tags=tags, raw_fields=raw)
    try:
        target = path.relative_to(hq_core.HQ_ROOT).as_posix()
    except ValueError:
        target = str(path)
    hq_items.remove_inbox(item["path"], to, target)
    print(path)


# ---- days and timeline ----------------------------------------------------------

def cmd_day(args):
    _need("day")
    import hq_day

    words = list(args.words)
    if words and words[0] == "end":
        if len(words) > 2:
            raise HqError("usage: hq day end [DATE] [--summary-file F | --summary TEXT]")
        day = hq_day.parse_day(words[1] if len(words) > 1 else None)
        path, _ = hq_day.end_day(day, summary_text=args.summary, summary_file=args.summary_file)
        print(path)
        return
    if args.summary or args.summary_file:
        raise HqError("--summary/--summary-file go with `hq day end`")
    if len(words) > 1:
        raise HqError("usage: hq day [DATE] | hq day end [DATE]")
    day = hq_day.parse_day(words[0] if words else None)
    b = hq_day.bundle(day, with_git=not args.no_git)
    saved = hq_day.read_day(day.isoformat())
    if args.json:
        print(json.dumps({**b, "saved": {k: v for k, v in saved.items() if k != "path"}
                          if saved else None}, default=str))
        return
    counts = [f"{k} {len(b[k])}" for k in ("finished", "started", "dropped", "blocked") if b[k]]
    if b["commits"]:
        counts.append(f"{len(b['commits'])} commits")
    print(f"DAY  {day.strftime('%a')} {day.isoformat()}" + ("  " + ", ".join(counts) if counts else ""))
    if saved and saved["summary"]:
        print()
        print(saved["summary"])
    print()
    print(hq_day.facts_markdown(b))


def _timeline(args, which: str):
    _need(which)
    import hq_day

    day = hq_day.parse_day(args.date)
    start, end = (hq_day.week_range if which == "week" else hq_day.month_range)(day)
    t = hq_day.timeline(start, end, with_git=not args.no_git)
    if args.json:
        print(json.dumps(t, default=str))
        return
    tot = t["total"]
    print(f"{which.upper()}  {t['start']} to {t['end']}  "
          f"finished {tot['finished']}, started {tot['started']}, notes {tot['notes']}, "
          f"commits {tot['commits']}")
    rows = [(datetime.date.fromisoformat(d["date"]).strftime("%a %d"), str(d["finished"] or ""),
             str(d["started"] or ""), str(d["notes"] or ""), str(d["commits"] or ""),
             hq_day.first_line(d["summary"]))
            for d in t["days"]
            if which == "week" or d["actions"] or d["commits"] or d["summary"]]
    if rows:
        print(hq_term.table(("DAY", "DONE", "STARTED", "NOTES", "COMMITS", "SUMMARY"), rows, flex=5))
    if t["groups"]:
        print()
        grows, area = [], None
        for g in t["groups"]:
            if g["area"] != area:
                area = g["area"]
                grows.append(area)
            grows.append((g["group"], str(len(g["finished"]) or ""), str(len(g["started"]) or ""),
                          "; ".join(g["finished"])))
        print(hq_term.table(("GOAL / PROJECT", "DONE", "STARTED", "FINISHED"), grows, flex=3))


def cmd_week(args):
    _timeline(args, "week")


def cmd_month(args):
    _timeline(args, "month")


# ---- calendar --------------------------------------------------------------------

def cmd_cal(args):
    _need("cal")
    import hq_items

    if args.cal_cmd == "add":
        print(hq_items.add_event(args.title, args.start, args.end, repeat=args.repeat,
                                 area=args.area, notes=args.notes, until=args.until))
    elif args.cal_cmd == "set":
        print(hq_items.edit_event(args.ref, title=args.title, start=args.start, end=args.end,
                                  repeat=args.repeat, until=args.until, area=args.area,
                                  notes=args.notes))
    elif args.cal_cmd == "list":
        start = datetime.date.fromisoformat(hq_fields.parse_date(args.date)) if args.date \
            else datetime.date.today()
        end = start + datetime.timedelta(days=max(1, args.days) - 1)
        items = hq_items.occurrences(start, end, area=_area_opt(args.area))
        if args.json:
            for o in items:
                print(_jsonable(o))
            return
        if not items:
            print("(no events)")
            return
        print(hq_term.table(
            ("DATE", "TIME", "AREA", "REF", "TITLE", "REPEAT"),
            [(o["date"], f"{o['time']}–{o['end_time']}" if o["time"] else "all day",
              AREA_SHORT.get(o["area"], "·"), o["id"], o["title"],
              (o["repeat"] or "") + (f" until {o['until']}" if o.get("until") else ""))
             for o in items], flex=4))
    elif args.cal_cmd == "rm":
        e = hq_items.remove_event(args.ref)
        print(f"removed {e['id']} ({e['title']})")
    else:
        path, n = hq_items.export_ics()
        print(f"{path}  ({n} event{'s' if n != 1 else ''})")


# ---- artifacts ---------------------------------------------------------------------

def cmd_artifact(args):
    _need("artifact")
    import hq_artifacts

    if args.art_cmd == "add":
        print(hq_artifacts.add(args.ref, args.file, about=args.about, why=args.why,
                               project=args.project))
    else:
        items = hq_artifacts.list_for(args.ref, project=args.project)
        if args.json:
            for a in items:
                print(json.dumps(a))
            return
        if not items:
            print("(no artifacts)")
            return
        print(hq_term.table(("FILE", "ADDED", "ABOUT", "WHY"),
                            [(a["file"], a.get("added") or "", a.get("about") or "-",
                              a.get("why") or "-") for a in items], flex=2))


# ---- parser -------------------------------------------------------------------------

WRITE_COMMANDS = ("read", "dump", "triage", "day", "cal", "artifact")


def register(sub) -> None:
    p = sub.add_parser("today", help="what needs you today (advanced mode)")
    p.add_argument("--area")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_today)

    p = sub.add_parser("free", help="suggest tasks and reading that fit in the time (advanced mode)")
    p.add_argument("time", nargs="?", help="e.g. 30m, 1h (default: until your next event, else 30m)")
    p.add_argument("--area")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_free)

    p = sub.add_parser("read", help="reading list: hq read <url> | list | done <ref> | drop <ref> (advanced mode)")
    p.add_argument("words", nargs="+", metavar="url|list|done|drop|set")
    p.add_argument("--priority")
    p.add_argument("--note")
    p.add_argument("--mins", help="reading time, overrides the fetched estimate")
    p.add_argument("--area")
    p.add_argument("--title", help="skip fetching and use this title")
    p.add_argument("--tags", default="")
    p.add_argument("--offline", action="store_true", help="don't fetch the page")
    p.add_argument("--status", choices=("unread", "read", "dropped"))
    p.add_argument("--all", action="store_true")
    p.add_argument("--dropped", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("dump", help="capture a thought to the inbox (advanced mode)")
    p.add_argument("text", nargs="+")
    p.add_argument("--area")
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("inbox", help="list the inbox (advanced mode)")
    p.add_argument("--area")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inbox)

    p = sub.add_parser("triage", help="turn an inbox item into a task, goal or link (advanced mode)")
    p.add_argument("ref")
    p.add_argument("to", choices=TRIAGE_TO)
    p.add_argument("--project")
    p.add_argument("--goal")
    p.add_argument("--priority")
    p.add_argument("--due")
    p.add_argument("--do-on", dest="do_on")
    p.add_argument("--est")
    p.add_argument("--area")
    p.add_argument("--target")
    p.add_argument("--tags", default="")
    p.set_defaults(func=cmd_triage)

    p = sub.add_parser("day", help="what happened on a day; `hq day end` saves it (advanced mode)")
    p.add_argument("words", nargs="*", metavar="end|DATE")
    p.add_argument("--summary", help="a line for 'My notes' (day end)")
    p.add_argument("--summary-file", dest="summary_file", help="prose for 'Summary' (day end)")
    p.add_argument("--no-git", dest="no_git", action="store_true", help="skip reading git commits")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_day)

    for name, fn in (("week", cmd_week), ("month", cmd_month)):
        p = sub.add_parser(name, help=f"timeline for the {name} containing DATE (advanced mode)")
        p.add_argument("date", nargs="?")
        p.add_argument("--no-git", dest="no_git", action="store_true")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=fn)

    p = sub.add_parser("cal", help="calendar events (advanced mode)")
    csub = p.add_subparsers(dest="cal_cmd", required=True)
    c = csub.add_parser("add", help="add an event")
    c.add_argument("title")
    c.add_argument("start", help="YYYY-MM-DD HH:MM, today 10:00, +1d 9:30, HH:MM, or a date for all day")
    c.add_argument("end", nargs="?", help="HH:MM, a duration (30m, 1h) or a full time; default 30m")
    c.add_argument("--repeat", choices=("daily", "weekdays", "weekly"))
    c.add_argument("--until", help="last day of a repeating event")
    c.add_argument("--area")
    c.add_argument("--notes")
    c = csub.add_parser("set", help="change an event (none clears repeat, until, area, notes)")
    c.add_argument("ref")
    c.add_argument("--title")
    c.add_argument("--start", help="new start; the length is kept unless --end is given")
    c.add_argument("--end")
    c.add_argument("--repeat", choices=("daily", "weekdays", "weekly", "none"))
    c.add_argument("--until")
    c.add_argument("--area")
    c.add_argument("--notes")
    c = csub.add_parser("list", help="list events")
    c.add_argument("date", nargs="?")
    c.add_argument("--days", type=int, default=7)
    c.add_argument("--area")
    c.add_argument("--json", action="store_true")
    c = csub.add_parser("rm", help="remove an event")
    c.add_argument("ref")
    csub.add_parser("export", help="write calendar.ics for calendar apps")
    p.set_defaults(func=cmd_cal)

    p = sub.add_parser("artifact", help="register files next to an entry or goal (advanced mode)")
    asub = p.add_subparsers(dest="art_cmd", required=True)
    a = asub.add_parser("add", help="register a file with what it is and why it exists")
    a.add_argument("ref")
    a.add_argument("file")
    a.add_argument("--about", required=True)
    a.add_argument("--why", required=True)
    a.add_argument("--project")
    a = asub.add_parser("list", help="list an entry's artifacts")
    a.add_argument("ref")
    a.add_argument("--project")
    a.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_artifact)
