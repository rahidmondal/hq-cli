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


if __name__ == "__main__":
    unittest.main()
