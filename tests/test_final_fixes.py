"""Regression tests for the final whole-branch review fix wave."""
import json
import unittest

import hq_core
from helpers import TempRoot, run_cli, set_mode


def snapshot():
    root = hq_core.HQ_ROOT
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


class AdvancedBase(TempRoot):
    def setUp(self):
        super().setUp()
        set_mode("advanced")

    def ok(self, *argv):
        code, out, err = run_cli(list(argv))
        self.assertEqual(code, 0, err)
        return out


class ExactRefTests(AdvancedBase):
    """Item 1: an exact slug in an excluded status must not fall through to substring."""

    def test_archive_twice_does_not_archive_substring_match(self):
        self.ok("save", "task", "api", "--project", "p")
        self.ok("save", "task", "api v2", "--project", "p")
        self.ok("archive", "api")
        before = snapshot()
        code, out, err = run_cli(["archive", "api"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("'api' is archive, not planning/active", err)
        self.assertEqual(snapshot(), before)

    def test_start_active_exact_does_not_start_substring_match(self):
        self.ok("save", "task", "web", "--project", "p")
        self.ok("save", "task", "web next", "--project", "p")
        self.ok("start", "web")
        before = snapshot()
        code, out, err = run_cli(["start", "web"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("'web' is active, not planning", err)
        self.assertEqual(snapshot(), before)

    def test_substring_still_used_when_no_exact_anywhere(self):
        self.ok("save", "task", "web next", "--project", "p")
        self.ok("start", "web")
        self.assertTrue(hq_core.task_path("p", "active", "web-next").is_dir())


BAD_BYTES = b"---\nkind: task\nstatus: planning\ntags: []\n---\n\n# Caf\xe9\n"


class UnreadableReadmeTests(AdvancedBase):
    """Item 2: one non-UTF-8 README must not crash advanced reads; check reports it."""

    def setUp(self):
        super().setUp()
        self.ok("save", "task", "good", "--project", "p")
        self.bad = hq_core.task_path("p", "planning", "bad") / "README.md"
        self.bad.parent.mkdir(parents=True)
        self.bad.write_bytes(BAD_BYTES)

    def test_advanced_list_tolerates_unreadable(self):
        out = self.ok("list")
        self.assertIn("good", out)
        row = [l for l in out.splitlines() if " bad " in l + " "]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0].split()[-2:], ["bad", "bad"])
        recs = [json.loads(l) for l in self.ok("list", "--json").splitlines()]
        bad = next(r for r in recs if r["slug"] == "bad")
        self.assertEqual((bad["title"], bad["priority"], bad["area"]), ("bad", "P3", "work"))

    def test_advanced_show_and_set_tolerate_unreadable(self):
        self.assertIn("good", self.ok("show", "good"))
        self.ok("set", "good", "priority", "P1")
        code, _, err = run_cli(["show", "bad"])
        self.assertEqual(code, 1)
        self.assertIn("can't read", err)
        code, _, err = run_cli(["set", "bad", "priority", "P1"])
        self.assertEqual(code, 1)
        self.assertIn("can't read", err)
        self.assertEqual(self.bad.read_bytes(), BAD_BYTES)

    def test_unreadable_goal_is_tolerated(self):
        self.ok("goal", "new", "G")
        g = hq_core.HQ_ROOT / "goals" / "g" / "README.md"
        g.write_bytes(BAD_BYTES)
        self.ok("goal", "list")
        self.ok("list")
        self.ok("show", "good")
        code, _, err = run_cli(["goal", "done", "g"])
        self.assertEqual(code, 1)
        self.assertIn("can't read", err)

    def test_check_reports_unreadable_and_goal_missing_frontmatter(self):
        self.ok("goal", "new", "G")
        self.ok("goal", "new", "H")
        (hq_core.HQ_ROOT / "goals" / "g" / "README.md").write_bytes(BAD_BYTES)
        (hq_core.HQ_ROOT / "goals" / "h" / "README.md").write_text("# H\n", encoding="utf-8")
        code, out, _ = run_cli(["check"])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), [
            "goals/g/README.md: unreadable (not UTF-8)",
            "goals/h/README.md: missing frontmatter",
            "projects/p/planning/bad/README.md: unreadable (not UTF-8)",
        ])

    def test_classic_list_unchanged_crash(self):
        set_mode("classic")
        with self.assertRaises(UnicodeDecodeError):
            run_cli(["list"])


class UnicodeDigitTests(AdvancedBase):
    """Item 4: only ASCII digits are numbers in est/priority."""

    def test_stored_superscript_est_does_not_crash(self):
        self.ok("save", "task", "t", "--project", "p")
        f = hq_core.task_path("p", "planning", "t") / "README.md"
        f.write_text(f.read_text(encoding="utf-8").replace("tags: []", "tags: []\nest: ²"),
                     encoding="utf-8")
        recs = [json.loads(l) for l in self.ok("list", "--json").splitlines()]
        self.assertIsNone(recs[0]["est"])
        self.assertIsNone(json.loads(self.ok("show", "t", "--json"))["record"]["est"])
        self.ok("show", "t")

    def test_save_and_set_reject_unicode_digits(self):
        code, _, err = run_cli(["save", "task", "t", "--project", "p", "--est", "²"])
        self.assertEqual(code, 1)
        self.assertIn("bad estimate", err)
        self.ok("save", "task", "t", "--project", "p")
        for field, value, msg in (("est", "①", "bad estimate"),
                                  ("est", "²h", "bad estimate"),
                                  ("priority", "²", "bad priority")):
            code, _, err = run_cli(["set", "t", field, value])
            self.assertEqual(code, 1, (field, value))
            self.assertIn(msg, err)


class RecordRepoTests(AdvancedBase):
    """Item 5: a bad projects.json must not turn a completed save into a failure."""

    def setUp(self):
        super().setUp()
        p = hq_core.HQ_ROOT / ".hq" / "projects.json"
        p.write_text("{not json", encoding="utf-8")

    def test_save_warns_but_succeeds(self):
        from pathlib import Path
        from unittest import mock
        with mock.patch("hq_core.detect_repo_root", return_value=Path("/x/repo")), \
                mock.patch("hq_core.detect_project", return_value="repo"):
            code, out, err = run_cli(["save", "task", "T"])
        self.assertEqual(code, 0, err)
        readme = hq_core.task_path("repo", "planning", "t") / "README.md"
        self.assertEqual(out.strip(), str(readme))
        self.assertIn("warning: could not record repo:", err)
        self.assertTrue(readme.is_file())

    def test_list_and_show_ignore_bad_projects_file(self):
        self.ok("save", "task", "t", "--project", "personal")
        recs = [json.loads(l) for l in self.ok("list", "--json").splitlines()]
        self.assertEqual(recs[0]["area"], "personal")
        self.ok("list")
        self.ok("show", "t")
        code, out, _ = run_cli(["check"])
        self.assertIn("projects.json is not valid JSON", out)


class MinorFixTests(AdvancedBase):
    def setUp(self):
        super().setUp()
        self.ok("save", "task", "t", "--project", "p")

    def test_block_dash_is_quoted_and_round_trips(self):
        """Item 6."""
        self.ok("block", "t", "-")
        text = (hq_core.task_path("p", "planning", "t") / "README.md").read_text(encoding="utf-8")
        self.assertIn('blocked: "-"\n', text)
        self.assertEqual(hq_core.yaml_scalar("-"), '"-"')
        self.assertEqual(json.loads(self.ok("show", "t", "--json"))["record"]["blocked"], "-")

    def test_set_error_uses_correct_article(self):
        """Item 7."""
        code, _, err = run_cli(["set", "t", "title", "x"])
        self.assertEqual(code, 1)
        self.assertIn("can't set 'title' on an entry", err)
        self.ok("goal", "new", "G")
        code, _, err = run_cli(["set", "goal/g", "due", "today"])
        self.assertEqual(code, 1)
        self.assertIn("can't set 'due' on a goal", err)

    def test_goal_show_order_files_log_tasks(self):
        """Item 8."""
        self.ok("goal", "new", "G")
        self.ok("set", "t", "goal", "g")
        (hq_core.HQ_ROOT / "goals" / "g" / "notes.txt").write_text("x", encoding="utf-8")
        out = self.ok("show", "goal/g").splitlines()
        idx = [out.index(h) for h in ("files:", "log:", "tasks:")]
        self.assertEqual(idx, sorted(idx))

    def test_goal_show_log_only_matches_goal_lines(self):
        """Item 9."""
        self.ok("goal", "new", "kb")
        self.ok("save", "learning", "kb")
        self.ok("note", "goal/kb", "hello")
        log = json.loads(self.ok("show", "goal/kb", "--json"))["log"]
        self.assertEqual([e["action"] for e in log], ["goal", "note"])


if __name__ == "__main__":
    unittest.main()
