"""Classic mode must stay v1 even on a store full of advanced-mode data."""
import json
import unittest

from helpers import TempRoot, set_mode, run_cli
import hq_core
import hq_serve

V1_KEYS = {"project", "slug", "status", "kind", "title", "created", "tags", "path"}


def build_mixed_store():
    """v1 entries, then advanced extras (goal, fields, hostile blocked, projects.json,
    reading/x.md), then back to classic."""
    for argv in (
        ["save", "task", "Alpha task", "--project", "demo", "--tags", "x,y"],
        ["save", "bug", "Beta bug", "--project", "demo"],
        ["save", "task", "Gamma task", "--project", "other"],
    ):
        assert run_cli(argv)[0] == 0
    set_mode("advanced")
    for argv in (
        ["goal", "new", "Ship it", "--area", "work"],
        ["set", "alpha", "priority", "P1"],
        ["set", "alpha", "goal", "ship-it"],
        ["set", "alpha", "due", "2030-01-01"],
        ["block", "alpha", "waiting: on keys"],
        ["project", "set", "demo", "area", "personal"],
    ):
        code, _, err = run_cli(argv)
        assert code == 0, (argv, err)
    (hq_core.HQ_ROOT / "reading").mkdir()
    (hq_core.HQ_ROOT / "reading" / "x.md").write_text("# x\n", encoding="utf-8")
    set_mode("classic")


GOLDEN_LIST = (
    "PROJECT  STATUS    KIND  SLUG        TITLE     \n"
    "demo     planning  task  alpha-task  Alpha task\n"
    "demo     planning  bug   beta-bug    Beta bug  \n"
    "other    planning  task  gamma-task  Gamma task"
)


def entry_file(project, status, slug):
    return hq_core.HQ_ROOT / "projects" / project / status / slug / "README.md"


class TestClassicRegression(TempRoot):
    def setUp(self):
        super().setUp()
        build_mixed_store()

    def _log(self):
        lines = (hq_core.HQ_ROOT / ".log.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines]

    def test_classic_list_matches_v1_golden(self):
        code, out, _ = run_cli(["list"])
        self.assertEqual(code, 0)
        self.assertEqual(out.rstrip("\n"), GOLDEN_LIST)

    def test_classic_list_json_has_only_v1_keys(self):
        code, out, _ = run_cli(["list", "--json"])
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertEqual(set(json.loads(line)), V1_KEYS)

    def test_classic_find_includes_advanced_text(self):
        code, out, _ = run_cli(["find", "on keys"])
        self.assertEqual(code, 0)
        self.assertIn("alpha-task", out)

    def test_classic_start_preserves_advanced_fields(self):
        f = entry_file("demo", "planning", "alpha-task")
        before = f.read_text(encoding="utf-8")
        wanted = [l for l in before.splitlines()
                  if l.startswith(("priority:", "goal:", "blocked:"))]
        self.assertEqual(len(wanted), 3)
        self.assertIn('blocked: "waiting: on keys"', wanted)
        code, _, err = run_cli(["start", "alpha-task", "--project", "demo"])
        self.assertEqual(code, 0, err)
        after = entry_file("demo", "active", "alpha-task").read_text(encoding="utf-8")
        for line in wanted:
            self.assertIn(line + "\n", after)

    def test_classic_archive_writes_no_outcome(self):
        code, _, err = run_cli(["archive", "beta-bug", "--project", "demo"])
        self.assertEqual(code, 0, err)
        text = entry_file("demo", "archive", "beta-bug").read_text(encoding="utf-8")
        self.assertNotIn("outcome", text)
        self.assertNotIn("outcome", self._log()[-1])

    def test_classic_log_lines_have_no_by(self):
        skip = len(self._log())  # fixture's advanced-mode lines legitimately carry "by"
        run_cli(["start", "alpha-task", "--project", "demo"])
        run_cli(["archive", "alpha-task", "--project", "demo"])
        run_cli(["save", "task", "Delta", "--project", "demo"])
        entries = self._log()[skip:]
        self.assertEqual(len(entries), 3)
        for e in entries:
            self.assertNotIn("by", e)
        code, out, _ = run_cli(["log"])
        self.assertEqual(code, 0)
        self.assertNotIn('"by"', ' '.join(out.splitlines()[skip:]))

    def test_switch_back_to_advanced_loses_nothing(self):
        run_cli(["start", "alpha-task", "--project", "demo"])
        run_cli(["archive", "gamma-task", "--project", "other"])
        set_mode("advanced")
        code, out, err = run_cli(["show", "alpha-task", "--json"])
        self.assertEqual(code, 0, err)
        shown = json.loads(out)
        flat = json.dumps(shown)
        for needle in ("P1", "ship-it", "waiting: on keys", "2030-01-01"):
            self.assertIn(needle, flat)
        code, out, err = run_cli(["show", "ship-it"])
        self.assertEqual(code, 0, err)
        self.assertIn("Ship it", out)
        code, out, _ = run_cli(["goal", "list", "--json"])
        self.assertIn("Ship it", out)

    def test_classic_serve_index_renders(self):
        page = hq_serve.render_index()
        self.assertIn("Other artifacts", page)
        self.assertIn("goals", page)
        self.assertIn("reading", page)


class TestClassicRawFrontmatter(TempRoot):
    """Classic reads/writes frontmatter exactly like v1: no YAML quoting or unquoting."""

    def test_classic_save_does_not_quote_tags(self):
        code, out, err = run_cli(["save", "task", "A", "--project", "demo",
                                  "--tags", "yes,#urgent,@me,on"])
        self.assertEqual(code, 0, err)
        text = entry_file("demo", "planning", "a").read_text(encoding="utf-8")
        self.assertIn("tags: [yes, #urgent, @me, on]\n", text)

    def _hand_written(self, extra):
        f = entry_file("demo", "planning", "h")
        f.parent.mkdir(parents=True)
        f.write_text("---\nproject: demo\nkind: task\nstatus: planning\n"
                     "created: 2026-01-01\n" + extra + "---\n\n# H\n", encoding="utf-8")
        return f

    def test_classic_start_keeps_hand_written_values_byte_identical(self):
        self._hand_written('tags: []\nnote: "quoted"\nother: key: val\n')
        code, _, err = run_cli(["start", "h", "--project", "demo"])
        self.assertEqual(code, 0, err)
        after = entry_file("demo", "active", "h").read_text(encoding="utf-8")
        self.assertEqual(after, "---\nproject: demo\nkind: task\nstatus: active\n"
                                "created: 2026-01-01\ntags: []\nnote: \"quoted\"\n"
                                "other: key: val\n---\n\n# H\n")

    def test_classic_list_json_keeps_quotes_in_list_items(self):
        self._hand_written('tags: ["q", plain]\n')
        code, out, _ = run_cli(["list", "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"tags": ["\\"q\\"", "plain"]', out)
        self.assertEqual(json.loads(out)["tags"], ['"q"', "plain"])


if __name__ == "__main__":
    unittest.main()
