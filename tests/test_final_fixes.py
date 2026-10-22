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


if __name__ == "__main__":
    unittest.main()
