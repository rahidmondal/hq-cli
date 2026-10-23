"""The advanced-mode browser server: JSON API, write safety, and classic untouched."""
import http.client
import json
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer

import hq_core
import hq_serve
import hq_web
from helpers import TempRoot, run_cli, set_mode


class ServerCase(TempRoot):
    def setUp(self):
        super().setUp()
        set_mode("advanced")
        run_cli(["save", "task", "Write docs", "--project", "p", "--priority", "P1", "--due", "today",
                 "--est", "30m"])
        run_cli(["goal", "new", "Ship it", "--target", "+3d"])
        handler = hq_web.make_handler()
        self.token = handler.token
        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                          partial(handler, directory=str(hq_core.HQ_ROOT)))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.update({"Content-Type": "application/json", "X-HQ-Token": self.token})
        hdrs.update(headers or {})
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        return res.status, raw

    def get_json(self, path):
        status, raw = self.request("GET", path)
        return status, json.loads(raw)

    def post(self, body, headers=None):
        status, raw = self.request("POST", "/api/cmd", body, headers)
        return status, json.loads(raw)

    def log(self):
        return [json.loads(l) for l in
                (hq_core.HQ_ROOT / ".log.jsonl").read_text(encoding="utf-8").splitlines()]


class ReadTests(ServerCase):
    def test_app_page_embeds_token(self):
        status, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.token, raw.decode())
        self.assertIn(f"v{hq_core.VERSION}", raw.decode())
        self.assertNotIn("__VERSION__", raw.decode())
        for path in ("/_app/app.js", "/_app/app.css", "/board", "/goals", "/classic"):
            self.assertEqual(self.request("GET", path)[0], 200, path)

    def test_state(self):
        status, data = self.get_json("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual([s["key"] for s in data["sections"]], ["due"])
        item = data["sections"][0]["items"][0]
        self.assertEqual((item["slug"], item["when"], item["est_label"]), ("write-docs", "due today", "30m"))
        self.assertNotIn("path", item)
        self.assertEqual(data["goals"][0]["slug"], "ship-it")
        self.assertEqual(data["projects"], [{"name": "p", "area": "work"}])

    def test_free_and_entry(self):
        _, data = self.get_json("/api/free?minutes=45")
        self.assertEqual([r["slug"] for r in data["items"]], ["write-docs"])
        _, data = self.get_json("/api/free?minutes=10")
        self.assertEqual(data["items"], [])
        _, e = self.get_json("/api/entry?project=p&slug=write-docs")
        self.assertEqual(e["record"]["title"], "Write docs")
        self.assertEqual(e["log"][0]["action"], "save")
        _, g = self.get_json("/api/entry?goal=ship-it")
        self.assertEqual(g["record"]["slug"], "ship-it")
        status, err = self.get_json("/api/entry?project=p&slug=nope")
        self.assertEqual(status, 400)
        self.assertIn("nothing matches", err["error"])

    def test_bad_host_refused(self):
        status, _ = self.request("GET", "/api/state", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403)


class WriteTests(ServerCase):
    def test_set_runs_cli_and_logs_web(self):
        status, out = self.post({"action": "set", "project": "p", "slug": "write-docs",
                                 "field": "priority", "value": "P2"})
        self.assertEqual((status, out["ok"]), (200, True))
        last = self.log()[-1]
        self.assertEqual((last["action"], last["to"], last["by"]), ("set", "P2", "web"))

    def test_full_flow(self):
        ok = lambda body: self.assertTrue(self.post(body)[1]["ok"], body)
        ref = {"project": "p", "slug": "write-docs"}
        ok({"action": "start", **ref})
        ok({"action": "block", "reason": "waiting\non review", **ref})
        self.assertEqual(self.log()[-1]["reason"], "waiting on review")  # newlines flattened
        ok({"action": "unblock", **ref})
        ok({"action": "note", "text": "-starts with a dash", **ref})
        self.assertEqual(self.log()[-1]["text"], "-starts with a dash")
        ok({"action": "unstart", **ref})
        ok({"action": "set", "field": "goal", "value": "ship-it", **ref})
        ok({"action": "set", "field": "due", "value": "", **ref})  # empty clears
        ok({"action": "archive", "dropped": True, **ref})
        meta = hq_core.frontmatter_parse(
            (hq_core.task_path("p", "archive", "write-docs") / "README.md").read_text(encoding="utf-8"))[0]
        self.assertEqual((meta["outcome"], meta["goal"]), ("dropped", "ship-it"))
        self.assertNotIn("due", meta)
        ok({"action": "save", "project": "home", "title": "Buy milk", "priority": "P2", "area": "personal",
            "do_on": "today", "est": "15m"})
        self.assertTrue(hq_core.task_path("home", "planning", "buy-milk").is_dir())
        ok({"action": "goal_new", "title": "Learn Thai", "area": "personal", "target": "+30d"})
        ok({"action": "set", "goal": "learn-thai", "field": "priority", "value": "P1"})
        ok({"action": "goal_done", "goal": "learn-thai", "dropped": True})
        ok({"action": "project_area", "project": "home", "area": "personal"})
        self.assertTrue(all(l.get("by") == "web" for l in self.log()[2:]))

    def test_cli_errors_come_back_clean(self):
        status, out = self.post({"action": "set", "project": "p", "slug": "write-docs",
                                 "field": "priority", "value": "P9"})
        self.assertEqual(status, 400)
        self.assertEqual(out["error"], "bad priority 'P9' (use P1-P4)")
        status, out = self.post({"action": "rm -rf"})
        self.assertEqual(status, 400)
        status, out = self.post({"action": "set", "project": "p", "slug": ["x"], "field": "priority", "value": "1"})
        self.assertEqual(status, 400)

    def test_token_origin_and_body_checks(self):
        body = {"action": "start", "project": "p", "slug": "write-docs"}
        self.assertEqual(self.post(body, {"X-HQ-Token": "wrong"})[0], 403)
        self.assertEqual(self.post(body, {"Origin": "https://evil.example"})[0], 403)
        status, _ = self.request("POST", "/api/cmd", body, {"Host": "evil.example:80"})
        self.assertEqual(status, 403)
        status, _ = self.request("POST", "/api/cmd", body, {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(self.post(body, {"Origin": f"http://localhost:{self.port}"})[0], 200)
        self.assertEqual(sum(l["action"] == "start" for l in self.log()), 1)


class DailyLoopWebTests(ServerCase):
    def ok(self, body):
        status, out = self.post(body)
        self.assertEqual((status, out.get("ok")), (200, True), out)
        return out

    def test_new_pages_are_served(self):
        for page in ("/reading", "/inbox", "/calendar"):
            status, raw = self.request("GET", page)
            self.assertEqual(status, 200)
            self.assertIn(b"hq-token", raw)

    def test_inbox_reading_and_triage(self):
        self.ok({"action": "dump", "text": "-odd idea with https://e.com/x", "area": "work"})
        self.ok({"action": "dump", "text": "Plan the offsite"})
        _, state = self.get_json("/api/state")
        self.assertEqual(len(state["inbox"]), 2)
        self.ok({"action": "triage", "ref": "odd-idea", "to": "reading", "est": "5m"})
        self.ok({"action": "triage", "ref": "offsite", "to": "task", "project": "p", "do_on": "today",
                 "est": "20m", "priority": "P2"})
        _, state = self.get_json("/api/state")
        self.assertEqual(state["inbox"], [])
        self.assertEqual([i["url"] for i in state["reading"]], ["https://e.com/x"])
        task = next(r for r in state["entries"] if r["slug"] == "plan-the-offsite")
        self.assertEqual((task["priority"], task["do_on"], task["est"]), ("P2", state["today"], 20))
        self.ok({"action": "read_set", "ref": "e-com-x", "field": "priority", "value": "P1"})
        _, free = self.get_json("/api/free?minutes=10")
        self.assertEqual([(i["type"], i["priority"]) for i in free["items"]], [("reading", "P1")])
        self.ok({"action": "read_done", "ref": "e-com-x"})
        self.assertTrue(all(e.get("by") == "web" for e in self.log()[2:]))  # after setUp

    def test_read_add_needs_a_web_link(self):
        status, out = self.post({"action": "read_add", "url": "list"})
        self.assertEqual(status, 400)
        self.assertIn("http", out["error"])
        self.ok({"action": "read_add", "url": "https://e.com/-dash", "title": "-Dash", "mins": "4"})

    def test_calendar_and_day(self):
        self.ok({"action": "cal_add", "title": "-Standup", "start": "today 10:00", "end": "15m",
                 "repeat": "weekdays"})
        _, state = self.get_json("/api/state")
        self.assertEqual([e["title"] for e in state["events"]], ["-Standup"])
        month = state["today"][:7]
        _, cal = self.get_json(f"/api/calendar?month={month}")
        self.assertEqual(cal["month"], month)
        self.assertTrue(any(e["date"] == state["today"] for e in cal["events"]))
        self.ok({"action": "day_end", "summary": "-a quiet day"})
        _, cal = self.get_json(f"/api/calendar?month={month}")
        self.assertIn(state["today"], cal["days"])
        _, day = self.get_json("/api/day?date=today")
        self.assertEqual(day["saved"]["notes"], "- -a quiet day")
        self.assertIn("-Standup", day["facts_md"])
        event_id = cal["events"][0]["id"]
        self.ok({"action": "cal_rm", "ref": event_id})
        _, state = self.get_json("/api/state")
        self.assertEqual(state["events"], [])
        status, out = self.get_json("/api/calendar?month=nope")
        self.assertEqual(status, 400)


class CalendarViewTests(ServerCase):
    def test_week_view_and_timeline(self):
        self.post({"action": "start", "project": "p", "slug": "write-docs"})
        _, cal = self.get_json("/api/calendar?week=2026-10-23")
        self.assertEqual((cal["start"], cal["end"]), ("2026-10-19", "2026-10-25"))
        self.assertEqual(len(cal["timeline"]["days"]), 7)
        _, cal = self.get_json("/api/calendar?week=today")
        self.assertEqual(cal["timeline"]["total"]["started"], 1)
        self.assertTrue(any(g["started"] == ["Write docs"] for g in cal["timeline"]["groups"]))
        _, cal = self.get_json("/api/calendar?month=2026-02")
        self.assertEqual((cal["timeline"]["start"], cal["timeline"]["end"]), ("2026-02-01", "2026-02-28"))

    def test_theme_switch_is_in_the_page(self):
        _, raw = self.request("GET", "/")
        self.assertIn(b'data-act="theme"', raw)
        self.assertIn(b"<title>HQ</title>", raw)


class VersionTests(TempRoot):
    def test_cli_version_flag(self):
        code, out, err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), f"hq {hq_core.VERSION}")


class ClassicServeTests(TempRoot):
    def test_classic_mode_never_loads_the_app(self):
        handler_used = []
        orig = hq_serve.ThreadingHTTPServer

        class Probe:
            def __init__(self, addr, handler):
                handler_used.append(handler.func)
                raise KeyboardInterrupt

        hq_serve.ThreadingHTTPServer = Probe
        try:
            with self.assertRaises(KeyboardInterrupt):
                hq_serve.serve(0, open_browser=False)
            set_mode("advanced")
            with self.assertRaises(KeyboardInterrupt):
                hq_serve.serve(0, open_browser=False)
        finally:
            hq_serve.ThreadingHTTPServer = orig
        self.assertIs(handler_used[0], hq_serve.Handler)
        self.assertTrue(issubclass(handler_used[1], hq_web.Handler))


if __name__ == "__main__":
    unittest.main()
