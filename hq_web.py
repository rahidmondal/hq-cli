"""Advanced-mode `hq serve`: the v2 browser app (Today, Board, Goals, entry
panel) and its JSON API. Classic mode never loads this module.

Reads call hq_ops / hq_registry / hq_today directly. Every write runs the
matching CLI command in-process as `hq --by web ...`, so validation, output
and the log are exactly what the terminal would produce.

Safety: the server binds to 127.0.0.1. Every request must carry a Host of
127.0.0.1:<port> or localhost:<port> (blocks DNS rebinding). POSTs also need
the per-run token embedded in the page (X-HQ-Token), a JSON body, and a
same-origin Origin header when the browser sends one. The client only ever
sends refs (project + slug or goal slug), never file paths."""
import contextlib
import io
import json
import re
import secrets
import threading
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import hq_core
import hq_day
import hq_fields
import hq_items
import hq_ops
import hq_registry
import hq_serve
import hq_today
from hq_core import HqError

WEB_DIR = Path(__file__).with_name("web")
STATIC = {"app.css": "text/css", "app.js": "text/javascript"}
PAGES = ("/", "/today", "/board", "/goals", "/reading", "/inbox", "/calendar")
MAX_BODY = 64 * 1024
_WRITE_LOCK = threading.Lock()  # hq.main swaps sys.stdout; run one command at a time


# ---- reads -----------------------------------------------------------------

def _record(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k != "path"}
    out["tags"] = hq_serve._as_list(r.get("tags"))
    out["created"] = str(r.get("created") or "")
    out["est_label"] = hq_fields.format_est(r["est"]) if r.get("est") else None
    out["href"] = hq_serve._entry_href(r)
    return out


def _goal(g: dict, records: list[dict]) -> dict:
    mine = [r for r in records if r["goal"] == g["slug"]]
    out = {k: v for k, v in g.items() if k != "path"}
    out["created"] = str(g.get("created") or "")
    out["open"] = sum(r["status"] in hq_today.OPEN for r in mine)
    out["done"] = sum(r["status"] == "archive" and r["outcome"] != "dropped" for r in mine)
    out["dropped"] = sum(r["status"] == "archive" and r["outcome"] == "dropped" for r in mine)
    out["blocked"] = sum(r["status"] in hq_today.OPEN and bool(r["blocked"]) for r in mine)
    return out


def _item(i: dict) -> dict:
    """A reading/inbox item or event occurrence for the browser."""
    out = {k: v for k, v in i.items() if k != "path"}
    if i.get("est"):
        out["est_label"] = hq_fields.format_est(i["est"])
    return out


def state(today: date | None = None) -> dict:
    today = today or date.today()
    records = hq_ops.entry_records()
    goals = hq_registry.list_goals()
    sections = hq_today.build(records, goals, today)
    try:
        registry = hq_registry.load_projects()
    except HqError:
        registry = {}
    projects = sorted({r["project"] for r in records} | set(registry))
    saved = hq_day.read_day(today.isoformat())
    return {
        "today": today.isoformat(),
        "sections": [{**s, "items": [_record(r) for r in s["items"]]} for s in sections],
        "entries": [_record(r) for r in records],
        "goals": [_goal(g, records) for g in goals],
        "projects": [{"name": p, "area": hq_registry.project_area(p, registry)} for p in projects],
        "events": [_item({**o, "when": hq_today.event_when(o)}) for o in hq_items.occurrences(today, today)],
        "reading": [_item(i) for i in hq_items.list_reading()],
        "inbox": [_item(i) for i in hq_items.list_inbox()],
        "day_saved": bool(saved),
        "fields": {"priorities": list(hq_fields.PRIORITIES), "areas": list(hq_fields.AREAS),
                   "kinds": [k for k in hq_core.KINDS if k not in ("learning", "skill")],
                   "repeats": list(hq_items.REPEATS)},
    }


def free(minutes: int) -> list[dict]:
    picks = hq_today.free(hq_ops.entry_records(), minutes, limit=50,
                          reading=hq_items.list_reading(status="unread"))
    return [_item(p) if p.get("type") == "reading" else {**_record(p), "type": "entry"} for p in picks]


def calendar(month: str | None = None, week: str | None = None) -> dict:
    """A Monday-first grid: the weeks covering `month` (YYYY-MM), or the one
    week containing `week` (a date). Event occurrences and saved day summaries;
    due/do-on/targets come from state. Also the timeline for the period
    (the month itself, or the week)."""
    if week:
        anchor = hq_day.parse_day(week)
        start, end = hq_day.week_range(anchor)
        period = (start, end)
        label = start.isoformat()[:7]
    else:
        try:
            first = date.fromisoformat((month or date.today().isoformat()[:7]) + "-01")
        except ValueError:
            raise HqError(f"bad month {month!r} (use YYYY-MM)")
        _, last = hq_day.month_range(first)
        start = first - timedelta(days=first.weekday())
        end = last + timedelta(days=6 - last.weekday())
        period = (first, last)
        label = first.isoformat()[:7]
    days = {}
    d = start
    while d <= end:
        saved = hq_day.read_day(d.isoformat())
        if saved:
            days[d.isoformat()] = {"summary": hq_day.first_line(saved["summary"]),
                                   "templated": saved["templated"]}
        d += timedelta(days=1)
    return {"month": label, "start": start.isoformat(), "end": end.isoformat(),
            "events": [_item(o) for o in hq_items.occurrences(start, end)], "days": days,
            "timeline": hq_day.timeline(*period)}


def day(when: str | None) -> dict:
    d = hq_day.parse_day(when)
    b = hq_day.bundle(d)
    saved = hq_day.read_day(d.isoformat())
    return {"date": d.isoformat(), "facts_md": hq_day.facts_markdown(b),
            "counts": {k: len(b[k]) for k in ("finished", "started", "dropped", "blocked")}
            | {"commits": len(b["commits"]), "notes": b["notes"]},
            "events": b["events"],
            "saved": {k: v for k, v in saved.items() if k != "path"} if saved else None}


def entry(project: str | None, slug: str | None, goal: str | None) -> dict:
    if goal:
        data = hq_ops.show("goal/" + goal)
    elif project and slug:
        data = hq_ops.show(slug, project=project)
    else:
        raise HqError("need project and slug, or goal")
    record = data["record"]
    out = {**data, "record": _goal(record, hq_ops.entry_records()) if goal else _record(record)}
    out["log"] = [{**line, "local": _local(line.get("ts", ""))} for line in data["log"]]
    if goal:
        out["href"] = hq_serve._href(record["path"])
    return out


def _local(ts: str) -> str:
    import datetime

    try:
        return datetime.datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


# ---- writes ----------------------------------------------------------------

def _text(body: dict, key: str, required: bool = True) -> str | None:
    value = body.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise HqError(f"missing {key}")
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise HqError(f"{key} must be text")
    # One line only: header values and log lines can't hold newlines.
    return re.sub(r"\s+", " ", str(value)).strip()


def _target(body: dict) -> tuple[list[str], str]:
    """(--project args, ref) for an entry, or ([], goal/<slug>) for a goal."""
    goal = _text(body, "goal", required=False)
    if goal:
        return [], "goal/" + hq_core.slugify(goal)
    project = _text(body, "project")
    return [f"--project={project}"], _text(body, "slug")


def argv_for(body: dict) -> list[str]:
    """Map a JSON action to the hq command line it stands for. Positionals go
    after `--` so a value starting with '-' is never read as a flag."""
    action = body.get("action")
    if action == "set":
        proj, ref = _target(body)
        field = _text(body, "field")
        value = _text(body, "value", required=False) or "none"
        return ["set", *proj, "--", ref, field, value]
    if action in ("start", "unstart", "unblock"):
        proj, ref = _target(body)
        return [action, *proj, "--", ref]
    if action == "archive":
        proj, ref = _target(body)
        return ["archive", *proj, *(["--dropped"] if body.get("dropped") else []), "--", ref]
    if action == "block":
        proj, ref = _target(body)
        return ["block", *proj, "--", ref, _text(body, "reason")]
    if action == "note":
        proj, ref = _target(body)
        return ["note", *proj, "--", ref, _text(body, "text")]
    if action == "save":
        opts = [f"--project={_text(body, 'project')}"]
        for key, flag in (("priority", "--priority"), ("goal_ref", "--goal"), ("due", "--due"),
                          ("do_on", "--do-on"), ("est", "--est"), ("area", "--area")):
            value = _text(body, key, required=False)
            if value:
                opts.append(f"{flag}={value}")
        return ["save", *opts, "--", _text(body, "kind", required=False) or "task", _text(body, "title")]
    if action == "goal_new":
        opts = []
        for key in ("area", "target", "priority"):
            value = _text(body, key, required=False)
            if value:
                opts.append(f"--{key}={value}")
        return ["goal", "new", *opts, "--", _text(body, "title")]
    if action == "goal_done":
        dropped = ["--dropped"] if body.get("dropped") else []
        return ["goal", "done", *dropped, "--", "goal/" + hq_core.slugify(_text(body, "goal"))]
    if action == "project_area":
        return ["project", "set", "--", _text(body, "project"), "area", _text(body, "area")]
    if action == "read_add":
        url = _text(body, "url")
        if not url.lower().startswith(("http://", "https://")):
            raise HqError("a link must start with http:// or https://")
        return ["read", *_opts(body, ("priority", "note", "mins", "area", "title")), "--", url]
    if action in ("read_done", "read_drop"):
        return ["read", "done" if action == "read_done" else "drop", "--", _text(body, "ref")]
    if action == "read_set":
        value = _text(body, "value", required=False) or "none"
        return ["read", "set", "--", _text(body, "ref"), _text(body, "field"), value]
    if action == "dump":
        return ["dump", *_opts(body, ("area",)), "--", _text(body, "text")]
    if action == "triage":
        to = _text(body, "to")
        keys = ("project", "priority", "due", "do_on", "est", "area", "target", "goal_ref")
        return ["triage", *_opts(body, keys), "--", _text(body, "ref"), to]
    if action == "cal_add":
        opts = _opts(body, ("repeat", "until", "area", "notes"))
        end = _text(body, "end", required=False)
        return ["cal", "add", *opts, "--", _text(body, "title"), _text(body, "start"), *([end] if end else [])]
    if action == "cal_set":
        return ["cal", "set", *_opts(body, ("title", "start", "end", "repeat", "until", "area")),
                "--", _text(body, "ref")]
    if action == "cal_rm":
        return ["cal", "rm", "--", _text(body, "ref")]
    if action == "day_end":
        day = hq_fields.parse_date(_text(body, "date", required=False) or "today")
        return ["day", *_opts(body, ("summary",)), "--", "end", day]
    raise HqError(f"unknown action {action!r}")


_FLAGS = {"do_on": "--do-on", "goal_ref": "--goal"}


def _opts(body: dict, keys) -> list[str]:
    out = []
    for key in keys:
        value = _text(body, key, required=False)
        if value:
            out.append(f"{_FLAGS.get(key, '--' + key)}={value}")
    return out


def run(argv: list[str]) -> tuple[int, str, str]:
    import hq

    out, err = io.StringIO(), io.StringIO()
    with _WRITE_LOCK, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = hq.main(["--by", "web", *argv])
    return code, out.getvalue(), err.getvalue()


def _clean_error(err: str) -> str:
    lines = [l.removeprefix("error: ").removeprefix("hq: ") for l in err.strip().splitlines()]
    return " ".join(l for l in lines if not l.startswith("warning: HQ_ROOT")) or "command failed"


# ---- HTTP ------------------------------------------------------------------

def app_page(token: str) -> str:
    shell = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return shell.replace("__TOKEN__", token).replace("__VERSION__", hq_core.VERSION)


class Handler(hq_serve.Handler):
    token = ""  # set per server run by serve()

    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self._allowed_hosts()

    def _json(self, data, code: int = 200):
        payload = json.dumps(data, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self._host_ok():
            return self.send_error(403, "bad host")
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        if path in PAGES:
            return self._send(app_page(self.token))
        if path.startswith("/_app/") and path[len("/_app/"):] in STATIC:
            name = path[len("/_app/"):]
            return self._send((WEB_DIR / name).read_text(encoding="utf-8"), STATIC[name])
        if path == "/classic":
            return self._send(hq_serve.render_index())
        if path.startswith("/api/"):
            try:
                if path == "/api/state":
                    return self._json(state())
                if path == "/api/free":
                    minutes = hq_fields.parse_est(query.get("minutes", "30"))
                    return self._json({"minutes": minutes, "items": free(minutes)})
                if path == "/api/entry":
                    return self._json(entry(query.get("project"), query.get("slug"), query.get("goal")))
                if path == "/api/calendar":
                    return self._json(calendar(query.get("month"), query.get("week")))
                if path == "/api/day":
                    return self._json(day(query.get("date")))
            except HqError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            return self._json({"ok": False, "error": "not found"}, 404)
        super().do_GET()

    def do_POST(self):
        if not self._host_ok():
            return self.send_error(403, "bad host")
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc not in self._allowed_hosts():
            return self._json({"ok": False, "error": "cross-origin request refused"}, 403)
        if not secrets.compare_digest(self.headers.get("X-HQ-Token", ""), self.token):
            return self._json({"ok": False, "error": "bad or missing token; reload the page"}, 403)
        if self.path != "/api/cmd":
            return self._json({"ok": False, "error": "not found"}, 404)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"ok": False, "error": "JSON body required"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            return self._json({"ok": False, "error": "bad body size"}, 400)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
            argv = argv_for(body)
        except (ValueError, UnicodeDecodeError):
            return self._json({"ok": False, "error": "bad JSON"}, 400)
        except HqError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        code, out, err = run(argv)
        if code != 0:
            return self._json({"ok": False, "error": _clean_error(err)}, 400)
        return self._json({"ok": True, "out": out.strip()})


def make_handler():
    """A Handler subclass carrying a fresh random token for this server run."""
    return type("WebHandler", (Handler,), {"token": secrets.token_urlsafe(24)})
