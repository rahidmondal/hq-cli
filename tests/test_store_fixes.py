"""Fixes found by running advanced mode against a copy of the real store."""
import json
import os
import unittest

import hq_core
from helpers import TempRoot, run_cli, set_mode


class StoreFixTests(TempRoot):
    def ok(self, *argv):
        code, out, err = run_cli(list(argv))
        self.assertEqual(code, 0, err)
        return out

    def readme(self, status="planning", slug="t"):
        return hq_core.task_path("p", status, slug) / "README.md"

    def log(self):
        return [json.loads(l) for l in
                (hq_core.HQ_ROOT / ".log.jsonl").read_text(encoding="utf-8").splitlines()]

    def write_lf(self, slug="t"):
        """An entry written by an agent with LF endings, as most hand-made ones are."""
        path = self.readme(slug=slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"---\nproject: p\nkind: task\nstatus: planning\n"
                         b"created: 2026-10-01\ntags: []\n---\n\n# T\n\nbody line\n")
        return path


class LineEndingTests(StoreFixTests):
    def test_advanced_edits_keep_lf(self):
        set_mode("advanced")
        self.write_lf()
        self.ok("set", "t", "priority", "P1")
        self.ok("block", "t", "waiting")
        self.ok("unblock", "t")
        self.ok("start", "t")
        self.ok("unstart", "t")
        self.ok("archive", "t", "--dropped")
        data = self.readme("archive").read_bytes()
        self.assertNotIn(b"\r\n", data)
        self.assertIn(b"priority: P1\n", data)
        self.assertIn(b"body line\n", data)

    def test_advanced_edits_keep_crlf(self):
        set_mode("advanced")
        path = self.write_lf()
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.ok("set", "t", "est", "1h")
        data = path.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertIn(b"est: 1h\r\n", data)

    def test_goal_edits_keep_lf(self):
        set_mode("advanced")
        self.ok("goal", "new", "g")
        path = hq_core.HQ_ROOT / "goals" / "g" / "README.md"
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        self.ok("set", "goal/g", "priority", "P2")
        self.ok("goal", "done", "g")
        self.assertNotIn(b"\r\n", path.read_bytes())

    def test_classic_still_uses_v1_endings(self):
        # v1 rewrote moved READMEs with the platform default; classic must too.
        self.write_lf()
        self.ok("start", "t")
        data = self.readme("active").read_bytes()
        self.assertEqual(data.count(b"\r\n") > 0, os.linesep == "\r\n")


class GoalVsEntryRefTests(StoreFixTests):
    def setUp(self):
        super().setUp()
        set_mode("advanced")
        self.ok("goal", "new", "launch sprint")
        self.ok("save", "task", "launch sprint 3 weeks", "--project", "p")

    def test_bare_ref_matching_goal_and_entry_is_ambiguous(self):
        code, _, err = run_cli(["set", "launch-sprint", "priority", "P1"])
        self.assertEqual(code, 1)
        self.assertIn("goal/launch-sprint", err)
        self.assertIn("p/planning/launch-sprint-3-weeks", err)
        goal = hq_core.HQ_ROOT / "goals" / "launch-sprint" / "README.md"
        self.assertNotIn("priority: P1", goal.read_text(encoding="utf-8"))

    def test_goal_prefix_still_reaches_the_goal(self):
        self.ok("set", "goal/launch-sprint", "priority", "P1")
        goal = hq_core.HQ_ROOT / "goals" / "launch-sprint" / "README.md"
        self.assertIn("priority: P1", goal.read_text(encoding="utf-8"))

    def test_exact_goal_with_no_other_match_still_resolves(self):
        self.ok("goal", "new", "solo")
        self.ok("set", "solo", "priority", "P2")

    def test_exact_entry_still_beats_longer_entries(self):
        self.ok("save", "task", "api", "--project", "p")
        self.ok("save", "task", "api v2", "--project", "p")
        self.ok("set", "api", "priority", "P1")
        meta = hq_core.frontmatter_parse(
            self.readme(slug="api").read_text(encoding="utf-8"))[0]
        self.assertEqual(meta["priority"], "P1")


class NoOpSetTests(StoreFixTests):
    def setUp(self):
        super().setUp()
        set_mode("advanced")
        self.ok("save", "task", "t", "--project", "p", "--priority", "P1")

    def test_setting_same_value_writes_and_logs_nothing(self):
        before_log = len(self.log())
        before = self.readme().read_bytes()
        out = self.ok("set", "t", "priority", "1")
        self.assertIn(str(self.readme()), out)
        self.assertEqual(len(self.log()), before_log)
        self.assertEqual(self.readme().read_bytes(), before)

    def test_clearing_an_unset_field_logs_nothing(self):
        before_log = len(self.log())
        self.ok("set", "t", "due", "none")
        self.assertEqual(len(self.log()), before_log)

    def test_real_change_still_logs(self):
        self.ok("set", "t", "priority", "P2")
        self.assertEqual(self.log()[-1]["to"], "P2")


if __name__ == "__main__":
    unittest.main()
