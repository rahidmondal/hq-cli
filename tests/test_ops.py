import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import hq
import hq_core
import hq_ops
import hq_registry
from hq_core import HqError
from helpers import TempRoot, run_cli, set_mode


def meta_of(path):
    return hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))[0]


class OpsTests(TempRoot):
    def setUp(self):
        super().setUp()
        set_mode("advanced")

    def save(self, title, project="p", *extra):
        code, out, err = run_cli(["save", "task", title, "--project", project, *extra])
        self.assertEqual(code, 0, err)

    def test_resolve_exact_beats_substring(self):
        self.save("api")
        self.save("api docs")
        self.assertEqual(hq_ops.resolve_ref("api").slug, "api")

    def test_resolve_substring_unique(self):
        self.save("api")
        self.save("api docs")
        self.assertEqual(hq_ops.resolve_ref("docs").slug, "api-docs")

    def test_resolve_ambiguous_lists_matches(self):
        self.save("x", "a")
        self.save("x", "b")
        with self.assertRaises(HqError) as cm:
            hq_ops.resolve_ref("x")
        self.assertIn("a/planning/x", str(cm.exception))
        self.assertIn("b/planning/x", str(cm.exception))
        self.assertEqual(hq_ops.resolve_ref("x", project="a").project, "a")

    def test_resolve_goal_prefix(self):
        hq_registry.create_goal("kb")
        self.save("kb")
        self.assertEqual(hq_ops.resolve_ref("goal/kb").kind, "goal")
        with self.assertRaises(HqError):
            hq_ops.resolve_ref("kb")

    def test_goal_done_rejects_traversal(self):
        (hq_core.HQ_ROOT / "foo").mkdir()
        (hq_core.HQ_ROOT / "foo" / "README.md").write_text("---\n---\n# x\n", encoding="utf-8")
        hq_registry.create_goal("g")
        code, _, err = run_cli(["goal", "done", "../foo"])
        self.assertEqual(code, 1)
        self.assertIn("nothing matches", err)
        self.assertEqual(run_cli(["goal", "done", "goal/g"])[0], 0)

    def test_save_with_fields(self):
        hq_registry.create_goal("g")
        code, out, err = run_cli(["save", "task", "T", "--project", "p", "--priority", "1",
                                  "--due", "tomorrow", "--est", "1h30m", "--goal", "g"])
        self.assertEqual(code, 0, err)
        meta = meta_of(hq_core.task_path("p", "planning", "t") / "README.md")
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self.assertEqual((meta["priority"], meta["due"], meta["est"], meta["goal"]),
                         ("P1", tomorrow, "1h30m", "g"))
        code, _, err = run_cli(["save", "task", "U", "--project", "p", "--goal", "zz"])
        self.assertEqual(code, 1)
        self.assertIn("unknown goal 'zz'", err)

    def test_save_field_flag_in_classic_errors(self):
        set_mode("classic")
        code, _, err = run_cli(["save", "task", "T", "--project", "p", "--priority", "P1"])
        self.assertEqual(code, 1)
        self.assertIn("hq: '--priority' needs advanced mode — run: hq init --mode advanced", err)

    def test_save_records_repo_when_detected(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            old = os.getcwd()
            os.chdir(d)
            try:
                repo = hq_core.detect_repo_root(os.getcwd())
                code, _, err = run_cli(["save", "task", "T"])
                self.assertEqual(code, 0, err)
                slug = hq_core.slugify(repo.name)
                self.assertEqual(hq_registry.load_projects()[slug]["repos"], [repo.as_posix()])
                os.remove(hq_registry.projects_path())
                self.assertEqual(run_cli(["save", "task", "T2", "--project", "q"])[0], 0)
                self.assertFalse(hq_registry.projects_path().exists())
            finally:
                os.chdir(old)

    def test_start_archive_accept_substring_in_advanced(self):
        self.save("cli task")
        code, out, err = run_cli(["start", "cli-ta"])
        self.assertEqual(code, 0, err)
        self.assertTrue(hq_core.task_path("p", "active", "cli-task").is_dir())
        set_mode("classic")
        self.save("other task")
        self.assertEqual(run_cli(["start", "other-ta"])[0], 1)

    def test_archive_dropped(self):
        self.save("x")
        self.save("y")
        self.assertEqual(run_cli(["archive", "x", "--dropped"])[0], 0)
        self.assertEqual(meta_of(hq_core.task_path("p", "archive", "x") / "README.md")["outcome"], "dropped")
        self.assertEqual(run_cli(["archive", "y"])[0], 0)
        self.assertEqual(meta_of(hq_core.task_path("p", "archive", "y") / "README.md")["outcome"], "done")
        set_mode("classic")
        self.save("z")
        self.assertEqual(run_cli(["archive", "z"])[0], 0)
        self.assertNotIn("outcome", meta_of(hq_core.task_path("p", "archive", "z") / "README.md"))
        self.assertEqual(run_cli(["archive", "--dropped", "z"])[0], 1)

    def test_list_advanced_columns_and_json(self):
        self.save("alpha")
        self.save("beta")
        p = hq_core.task_path("p", "planning", "beta") / "README.md"
        p.write_text(p.read_text(encoding="utf-8").replace("tags: []", "tags: []\nblocked: waiting"),
                     encoding="utf-8")
        code, out, _ = run_cli(["list"])
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), ["PROJECT", "STATUS", "KIND", "P", "AREA", "DUE", "SLUG", "TITLE"])
        col = lines[0].index("STATUS")
        self.assertEqual(lines[2][col:col + 7], "blocked")
        self.assertEqual(lines[1].split()[:6], ["p", "planning", "task", "P3", "work", "-"])
        self.assertEqual(lines[0].index("KIND"), lines[1].index("task"))
        code, out, _ = run_cli(["list", "--json"])
        rec = json.loads(out.splitlines()[0])
        for k in ("project", "slug", "status", "kind", "title", "created", "tags", "path",
                  "priority", "area", "goal", "due", "do_on", "est", "blocked", "outcome"):
            self.assertIn(k, rec)

    def test_list_filters(self):
        hq_registry.create_goal("g")
        self.save("a", "p", "--priority", "P1", "--due", "+2d", "--goal", "g")
        self.save("b", "p", "--area", "personal", "--due", "+30d")
        self.save("c")

        def slugs(*flags):
            code, out, err = run_cli(["list", "--json", *flags])
            self.assertEqual(code, 0, err)
            return sorted(json.loads(line)["slug"] for line in out.splitlines())

        self.assertEqual(slugs("--area", "personal"), ["b"])
        self.assertEqual(slugs("--goal", "g"), ["a"])
        self.assertEqual(slugs("--priority", "P1"), ["a"])
        self.assertEqual(slugs("--due-before", "+7d"), ["a"])

    def test_list_tolerates_v1_and_malformed_entries(self):
        root = hq_core.HQ_ROOT / "projects" / "p" / "planning"
        for name, text in (("v1", "---\nproject: p\nkind: task\nstatus: planning\n---\n\n# V1\n"),
                           ("bad", "---\nproject: p\nkind: task\npriority: high\n---\n\n# Bad\n"),
                           ("nofm", "# No frontmatter\n")):
            (root / name).mkdir(parents=True)
            (root / name / "README.md").write_text(text, encoding="utf-8")
        code, out, err = run_cli(["list"])
        self.assertEqual(code, 0, err)
        for name in ("v1", "bad", "nofm"):
            self.assertIn(name, out)
        self.assertIn("P3", out)

    def test_list_prints_non_ascii_title(self):
        title = "Café → 日本"
        self.save(title)
        code, out, _ = run_cli(["list"])
        self.assertIn(title, out)
        buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.object(sys, "stdout", buf):
            self.assertEqual(hq.main(["list"]), 0)


if __name__ == "__main__":
    unittest.main()
