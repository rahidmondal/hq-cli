"""Phase 2-3, 5: today/free CLI, reading list, inbox, days, timeline, calendar
events and artifacts (advanced mode)."""
import datetime
import json
import os
from pathlib import Path
from unittest import mock

from helpers import TempRoot, run_cli, set_mode

import hq_core
import hq_day
import hq_fetch
import hq_items
import hq_today

TODAY = datetime.date.today().isoformat()


class Adv(TempRoot):
    def setUp(self):
        super().setUp()
        set_mode("advanced")
        self._noenv = mock.patch.dict(os.environ, {"HQ_ROOT": str(hq_core.HQ_ROOT), "NO_COLOR": "1"})
        self._noenv.start()

    def tearDown(self):
        self._noenv.stop()
        super().tearDown()

    def ok(self, *argv):
        code, out, err = run_cli(list(argv))
        self.assertEqual(code, 0, f"{argv}: {err}")
        return out

    def fails(self, *argv):
        code, out, err = run_cli(list(argv))
        self.assertEqual(code, 1, f"{argv} should fail: {out}")
        return err

    def jsonl(self, *argv):
        return [json.loads(l) for l in self.ok(*argv, "--json").splitlines() if l.strip()]


class FetchParseTests(Adv):
    def test_title_words_and_minutes(self):
        html = ("<html><head><title> A  Post </title><style>x y z</style></head><body>"
                + "<p>" + "word " * 460 + "</p><script>var a = 1;</script></body></html>")
        page = hq_fetch.parse(html)
        self.assertEqual(page["title"], "A Post")
        self.assertEqual(page["words"], 460)
        self.assertEqual(page["minutes"], 2)

    def test_og_title_wins_and_empty_page(self):
        page = hq_fetch.parse('<meta property="og:title" content="OG"><title>T</title>')
        self.assertEqual(page["title"], "OG")
        self.assertIsNone(page["minutes"])


class ReadingTests(Adv):
    def test_add_offline_list_done(self):
        out = self.ok("read", "https://example.com/a/post", "--offline", "--priority", "p2", "--mins", "12")
        path = Path(out.strip())
        self.assertEqual(path.parent.name, "reading")
        meta, body = hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))
        self.assertEqual((meta["url"], meta["status"], meta["priority"], meta["est"]),
                         ("https://example.com/a/post", "unread", "P2", "12m"))
        self.assertIn("# example.com/a/post", body)
        items = self.jsonl("read", "list")
        self.assertEqual([i["slug"] for i in items], [path.stem])
        self.ok("read", "done", "post")
        self.assertEqual(self.jsonl("read", "list"), [])
        self.assertEqual(self.jsonl("read", "list", "--status", "read")[0]["read_on"], TODAY)
        self.assertIn("already read", self.fails("read", "done", "post"))

    def test_fetch_used_and_duplicate_refused(self):
        with mock.patch.object(hq_fetch, "fetch", return_value={"title": "Why SQLite", "words": 2300,
                                                                "minutes": 10}) as f:
            path = Path(self.ok("read", "https://e.com/sqlite").strip())
        f.assert_called_once()
        self.assertEqual(path.stem, "why-sqlite")
        self.assertIn("est: 10m", path.read_text(encoding="utf-8"))
        self.assertIn("already on the reading list", self.fails("read", "https://e.com/sqlite", "--offline"))

    def test_fetch_failure_saves_with_warning(self):
        with mock.patch.object(hq_fetch, "fetch", side_effect=OSError("down")):
            code, out, err = run_cli(["read", "https://e.com/x"])
        self.assertEqual(code, 0)
        self.assertIn("couldn't fetch", err)
        self.assertTrue(Path(out.strip()).is_file())

    def test_config_can_turn_fetch_off(self):
        cfg = hq_core.load_config()
        cfg["fetch"] = False
        hq_core.save_config(cfg)
        with mock.patch.object(hq_fetch, "fetch") as f:
            self.ok("read", "https://e.com/y")
        f.assert_not_called()

    def test_rejects_non_web_links(self):
        self.assertIn("not a web link", self.fails("read", "file:///etc/passwd", "--offline"))
        self.assertIn("not a web link", self.fails("read", "javascript:alert(1)", "--offline"))

    def test_set_and_area_filter(self):
        self.ok("read", "https://e.com/w", "--offline", "--area", "work")
        self.ok("read", "https://e.com/any", "--offline")
        self.ok("read", "set", "e-com-w", "priority", "1")
        self.assertEqual(self.jsonl("read", "list", "--area", "personal")[0]["slug"], "e-com-any")
        self.assertEqual({i["slug"]: i["priority"] for i in self.jsonl("read", "list", "--area", "work")},
                         {"e-com-w": "P1", "e-com-any": "P3"})


class InboxTests(Adv):
    def test_dump_list_triage_task(self):
        path = Path(self.ok("dump", "Write", "retro", "notes", "--area", "personal").strip())
        self.assertTrue(path.name.startswith(TODAY))
        self.assertEqual(self.jsonl("inbox")[0]["title"], "Write retro notes")
        out = self.ok("triage", "retro", "task", "--project", "life", "--est", "15m")
        self.assertFalse(path.exists())
        rec = self.jsonl("list")[0]
        self.assertEqual((rec["project"], rec["slug"], rec["est"], rec["area"]),
                         ("life", "write-retro-notes", 15, "personal"))
        self.assertIn("write-retro-notes", out)
        line = hq_core.read_log()[-1]
        self.assertEqual((line["action"], line["to"]), ("triage", "task"))

    def test_triage_reading_goal_drop(self):
        self.ok("dump", "read https://e.com/deep-dive later")
        self.ok("dump", "Ship v2")
        self.ok("dump", "junk")
        self.ok("triage", "read-https", "reading", "--est", "5m")
        item = hq_items.list_reading()[0]
        self.assertEqual((item["url"], item["note"]), ("https://e.com/deep-dive", "read later"))
        self.ok("triage", "ship", "goal", "--target", "+7d")
        self.assertEqual(self.jsonl("goal", "list")[0]["slug"], "ship-v2")
        self.ok("triage", "junk", "drop")
        self.assertEqual(self.jsonl("inbox"), [])

    def test_failed_triage_keeps_the_item(self):
        self.ok("dump", "no link here")
        self.assertIn("no http(s) link", self.fails("triage", "no-link", "reading"))
        self.assertIn("unknown goal", self.fails("triage", "no-link", "task", "--project", "p",
                                                  "--goal", "nope"))
        self.assertEqual(len(self.jsonl("inbox")), 1)

    def test_check_flags_stale_inbox(self):
        d = hq_core.HQ_ROOT / "inbox"
        d.mkdir()
        (d / "2020-01-01-old.md").write_text("---\nkind: inbox\nadded: 2020-01-01\n---\n\n# old\n",
                                             encoding="utf-8")
        code, out, _ = run_cli(["check"])
        self.assertEqual(code, 1)
        self.assertIn("days old (triage it)", out)


class EventTests(Adv):
    def test_parse_span_forms(self):
        d = TODAY
        self.assertEqual(hq_items.parse_span("2026-10-23T10:00", "10:15"),
                         ("2026-10-23T10:00", "2026-10-23T10:15"))
        self.assertEqual(hq_items.parse_span("2026-10-23 10:00", "1h30m"),
                         ("2026-10-23T10:00", "2026-10-23T11:30"))
        self.assertEqual(hq_items.parse_span("9:05", None), (f"{d}T09:05", f"{d}T09:35"))
        self.assertEqual(hq_items.parse_span("2026-10-23", None), ("2026-10-23", "2026-10-23"))
        self.assertEqual(hq_items.parse_span("2026-10-23", "2026-10-25"), ("2026-10-23", "2026-10-25"))
        for bad in (("2026-10-23 10:00", "09:00"), ("2026-10-23", "10:00"), ("25:00", None)):
            with self.assertRaises(hq_core.HqError):
                hq_items.parse_span(*bad)

    def test_repeats_and_occurrences(self):
        hq_items.add_event("Standup", "2026-10-23 10:00", "15m", repeat="weekdays")  # a Friday
        hq_items.add_event("Gym", "2026-10-24 07:00", "1h", repeat="weekly")
        hq_items.add_event("Trip", "2026-10-26", "2026-10-27")
        occ = hq_items.occurrences(datetime.date(2026, 10, 22), datetime.date(2026, 10, 31))
        got = [(o["date"], o["title"]) for o in occ]
        self.assertNotIn(("2026-10-22", "Standup"), got)
        self.assertIn(("2026-10-23", "Standup"), got)
        self.assertNotIn(("2026-10-24", "Standup"), got)
        self.assertIn(("2026-10-26", "Standup"), got)
        self.assertIn(("2026-10-31", "Gym"), got)
        self.assertEqual([d for d, t in got if t == "Trip"], ["2026-10-26", "2026-10-27"])

    def test_cli_add_list_rm_export(self):
        self.ok("cal", "add", "Design review, part 1; notes", "2026-10-23 14:00", "15:00",
                "--notes", "line one\nline two")
        self.ok("cal", "add", "Holiday", "2026-10-25")
        items = self.jsonl("cal", "list", "2026-10-23", "--days", "3")
        self.assertEqual([i["title"] for i in items], ["Design review, part 1; notes", "Holiday"])
        out = self.ok("cal", "export")
        self.assertIn("2 events", out)
        ics = (hq_core.HQ_ROOT / "calendar.ics").read_bytes().decode("utf-8")
        self.assertIn("SUMMARY:Design review\\, part 1\\; notes\r\n", ics)
        self.assertIn("DTSTART:20261023T140000\r\n", ics)
        self.assertIn("DTEND;VALUE=DATE:20261026\r\n", ics)
        self.assertIn("DESCRIPTION:line one\\nline two", ics)
        self.ok("cal", "rm", "holiday")
        self.assertEqual(len(self.jsonl("cal", "list", "2026-10-23", "--days", "3")), 1)

    def test_ics_folds_long_lines(self):
        hq_items.add_event("x" * 200, "2026-10-23")
        hq_items.export_ics()
        for line in (hq_core.HQ_ROOT / "calendar.ics").read_bytes().split(b"\r\n"):
            self.assertLessEqual(len(line), 75)


class TodayFreeTests(Adv):
    def test_today_includes_calendar_and_reading_and_json(self):
        self.ok("save", "task", "Ship it", "--project", "p", "--due", "today", "--priority", "P1")
        self.ok("save", "task", "Home thing", "--project", "home", "--area", "personal", "--do-on", "today")
        self.ok("cal", "add", "Standup", "23:58", "1m")
        self.ok("read", "https://e.com/a", "--offline", "--title", "A link")
        rows = self.jsonl("today")
        self.assertEqual([r["section"] for r in rows], ["calendar", "due", "planned", "reading"])
        work = self.jsonl("today", "--area", "work")
        self.assertEqual([r["slug"] for r in work if r["section"] != "calendar"], ["ship-it", "a-link"])
        text = self.ok("today")
        self.assertIn("overdue / due today", text)
        self.assertIn("Ship it", text)
        self.assertIn("23:58", text)

    def test_today_reading_capped_at_three(self):
        for i in range(5):
            self.ok("read", f"https://e.com/{i}", "--offline")
        self.assertEqual(sum(r["section"] == "reading" for r in self.jsonl("today")), 3)

    def test_free_mixes_entries_and_reading(self):
        self.ok("save", "task", "Small", "--project", "p", "--est", "20m", "--priority", "P2")
        self.ok("save", "task", "Big", "--project", "p", "--est", "2h")
        self.ok("save", "task", "No est", "--project", "p")
        self.ok("read", "https://e.com/r", "--offline", "--mins", "10", "--priority", "P1")
        picks = self.jsonl("free", "30m")
        self.assertEqual([(p["type"], p["slug"]) for p in picks],
                         [("reading", "e-com-r"), ("entry", "small")])
        self.assertTrue(all(p["minutes"] == 30 for p in picks))
        self.assertIn("nothing with an estimate fits", self.ok("free", "5m"))

    def test_free_without_time_uses_gap_to_next_event(self):
        now = datetime.datetime(2026, 10, 23, 9, 0)
        events = [{"date": "2026-10-23", "time": "09:45"}, {"date": "2026-10-23", "time": "08:00"},
                  {"date": "2026-10-23", "time": None}]
        self.assertEqual(hq_today.minutes_until_next(events, now), 45)
        self.assertIsNone(hq_today.minutes_until_next(events[1:], now))


class DayTests(Adv):
    def _activity(self):
        self.ok("goal", "new", "Launch", "--area", "work")
        self.ok("save", "task", "Alpha", "--project", "p", "--goal", "launch")
        self.ok("save", "task", "Beta", "--project", "home", "--area", "personal")
        self.ok("start", "alpha")
        self.ok("note", "alpha", "halfway")
        self.ok("archive", "beta")

    def test_bundle_groups_by_area_and_goal(self):
        self._activity()
        b = hq_day.bundle(datetime.date.today(), with_git=False)
        areas = {a["area"]: [g["group"] for g in a["groups"]] for a in b["areas"]}
        self.assertEqual(areas, {"personal": ["home"], "work": ["goal: Launch"]})
        self.assertEqual([i["title"] for i in b["finished"]], ["Beta"])
        self.assertEqual([i["title"] for i in b["started"]], ["Alpha"])
        self.assertEqual(b["notes"], 1)
        data = json.loads(self.ok("day", "--json", "--no-git"))
        self.assertEqual(data["date"], TODAY)
        self.assertIsNone(data["saved"])

    def test_day_end_rules(self):
        self._activity()
        path = Path(self.ok("day", "end", "--summary", "good day").strip())
        first = hq_day.read_day(TODAY)
        self.assertTrue(first["templated"])
        self.assertIn("Finished 1", first["summary"])
        self.assertEqual(first["notes"], "- good day")
        # rerun: same line not added twice; template refreshed with new facts
        self.ok("save", "task", "Gamma", "--project", "p")
        self.ok("day", "end", "--summary", "good day")
        again = hq_day.read_day(TODAY)
        self.assertEqual(again["notes"], "- good day")
        self.assertIn("Gamma", again["facts"])
        # agent prose replaces the template and survives a plain rerun
        prose = hq_core.HQ_ROOT / "prose.md"
        prose.write_text("Shipped Beta. Alpha is halfway.\n", encoding="utf-8")
        self.ok("day", "end", "--summary-file", str(prose))
        # the user edits My notes by hand and adds their own section
        text = path.read_text(encoding="utf-8").replace("- good day", "- good day\n- my own line")
        path.write_text(text + "\n## Mood\n\ncalm\n", encoding="utf-8")
        self.ok("day", "end", "--summary", "late add")
        final = hq_day.read_day(TODAY)
        self.assertEqual(final["summary"], "Shipped Beta. Alpha is halfway.")
        self.assertFalse(final["templated"])
        self.assertEqual(final["notes"], "- good day\n- my own line\n- late add")
        self.assertIn("## Mood\n\ncalm", path.read_text(encoding="utf-8"))
        self.assertEqual(path.read_text(encoding="utf-8").count("## Facts"), 1)

    def test_day_end_for_another_date_and_bad_file(self):
        self.ok("day", "end", "2026-01-02")
        self.assertIn("Nothing recorded", hq_day.read_day("2026-01-02")["summary"])
        self.assertIn("can't read summary file", self.fails("day", "end", "--summary-file", "nope.md"))
        self.assertIn("go with `hq day end`", self.fails("day", "--summary", "x"))

    def test_week_and_month(self):
        self._activity()
        self.ok("day", "end")
        week = json.loads(self.ok("week", "--json", "--no-git"))
        self.assertEqual(len(week["days"]), 7)
        self.assertEqual(week["total"]["finished"], 1)
        today_row = next(d for d in week["days"] if d["date"] == TODAY)
        self.assertTrue(today_row["summary"].startswith("Finished 1"))
        month = json.loads(self.ok("month", "2026-02-10", "--json", "--no-git"))
        self.assertEqual((month["start"], month["end"]), ("2026-02-01", "2026-02-28"))
        text = self.ok("week", "--no-git")
        self.assertIn("goal: Launch", text)
        self.assertIn("Beta", text)

    def test_commits_from_recorded_repos(self):
        import hq_registry

        hq_registry.record_repo("p", Path("/no/such/repo"))
        self.assertEqual(hq_day.commits(datetime.date.today(), datetime.date.today()), [])


class ArtifactTests(Adv):
    def test_add_copy_list_show_and_dangling(self):
        self.ok("save", "task", "Report", "--project", "p")
        src = hq_core.HQ_ROOT / "draft.html"
        src.write_text("<p>hi</p>", encoding="utf-8")
        dest = Path(self.ok("artifact", "add", "report", str(src), "--about", "explainer",
                            "--why", "for review").strip())
        self.assertEqual(dest.parent.name, "report")
        self.assertTrue(dest.is_file())
        (dest.parent / "notes.txt").write_text("x", encoding="utf-8")
        listed = self.jsonl("artifact", "list", "report")
        self.assertEqual([(a["file"], a["about"]) for a in listed],
                         [("draft.html", "explainer"), ("notes.txt", None)])
        shown = json.loads(self.ok("show", "report", "--json"))
        self.assertEqual(shown["artifacts"][0]["why"], "for review")
        self.assertIn("draft.html  explainer (why: for review)", self.ok("show", "report"))
        # registering by name, again, updates in place
        self.ok("artifact", "add", "report", "draft.html", "--about", "v2", "--why", "again")
        self.assertEqual(self.jsonl("artifact", "list", "report")[0]["about"], "v2")
        dest.unlink()
        code, out, _ = run_cli(["check"])
        self.assertEqual(code, 1)
        self.assertIn("artifact 'draft.html' is registered but missing", out)

    def test_refuses_readme_and_missing_files(self):
        self.ok("save", "task", "Report", "--project", "p")
        self.assertIn("no such file", self.fails("artifact", "add", "report", "nope.txt",
                                                 "--about", "a", "--why", "b"))
        self.assertIn("can't register", self.fails("artifact", "add", "report", "README.md",
                                                   "--about", "a", "--why", "b"))


class GatingTests(TempRoot):
    def test_classic_refuses_new_commands(self):
        for argv in (["today"], ["free"], ["read", "list"], ["dump", "x"], ["inbox"], ["day"],
                     ["week"], ["month"], ["cal", "list"], ["triage", "x", "drop"],
                     ["artifact", "list", "x"]):
            code, _, err = run_cli(argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("needs advanced mode", err)

    def test_bad_actor_does_not_block_reads(self):
        set_mode("advanced")
        with mock.patch.dict(os.environ, {"HQ_ACTOR": "robot", "HQ_ROOT": str(hq_core.HQ_ROOT)}):
            self.assertEqual(run_cli(["log"])[0], 0)
            self.assertEqual(run_cli(["today", "--json"])[0], 0)
            code, _, err = run_cli(["dump", "x"])
        self.assertEqual(code, 1)
        self.assertIn("invalid HQ_ACTOR", err)


class ClassicReadsNewData(Adv):
    def test_classic_list_find_log_serve_with_phase2_data(self):
        import hq_serve

        self.ok("save", "task", "Report", "--project", "p")
        self.ok("read", "https://e.com/a", "--offline", "--note", "why: it matters")
        self.ok("dump", "an idea")
        self.ok("cal", "add", "Standup", "2026-10-23 10:00", "15m", "--repeat", "daily")
        src = hq_core.HQ_ROOT / "a.txt"
        src.write_text("x", encoding="utf-8")
        self.ok("artifact", "add", "report", str(src), "--about", "a", "--why", "b")
        self.ok("day", "end")
        set_mode("classic")
        hq_core.ACTOR = None
        code, out, _ = run_cli(["list"])
        self.assertEqual(code, 0)
        self.assertIn("report", out)
        self.assertEqual(run_cli(["find", "idea"])[0], 0)
        self.assertEqual(run_cli(["log"])[0], 0)
        page = hq_serve.render_index()
        for folder in ("reading", "inbox", "calendar", "days"):
            self.assertIn(folder, page)
        self.assertNotIn(".artifacts.json", page)
