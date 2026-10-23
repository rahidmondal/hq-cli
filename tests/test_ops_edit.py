import json
import unittest

import hq_core
import hq_registry
from helpers import TempRoot, run_cli, set_mode


def meta_of(path):
    return hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))[0]


class EditTests(TempRoot):
    def setUp(self):
        super().setUp()
        set_mode("advanced")
        self.ok("save", "task", "t", "--project", "p")

    def ok(self, *argv):
        code, out, err = run_cli(list(argv))
        self.assertEqual(code, 0, err)
        return out

    def readme(self, status="planning", slug="t"):
        return hq_core.task_path("p", status, slug) / "README.md"

    def log(self):
        return [json.loads(l) for l in
                (hq_core.HQ_ROOT / ".log.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_set_priority_and_clear(self):
        self.ok("set", "t", "priority", "1")
        self.assertEqual(meta_of(self.readme())["priority"], "P1")
        last = self.log()[-1]
        self.assertEqual({k: last[k] for k in ("action", "field", "from", "to", "by")},
                         {"action": "set", "field": "priority", "from": None, "to": "P1", "by": "user"})
        self.ok("set", "t", "priority", "none")
        self.assertNotIn("priority", meta_of(self.readme()))

    def test_set_rejects_unknown_field_and_bad_value(self):
        self.assertEqual(run_cli(["set", "t", "status", "done"])[0], 1)
        self.assertEqual(run_cli(["set", "t", "due", "someday"])[0], 1)
        self.assertEqual(run_cli(["set", "t", "goal", "nope"])[0], 1)

    def test_set_goal_target(self):
        hq_registry.create_goal("g")
        self.ok("set", "goal/g", "target", "2026-11-30")
        self.assertEqual(meta_of(hq_registry.goal_readme("g"))["target"], "2026-11-30")
        self.assertEqual(run_cli(["set", "goal/g", "due", "2026-11-30"])[0], 1)

    def test_set_preserves_key_order(self):
        self.ok("set", "t", "priority", "2")
        keys = list(meta_of(self.readme()))
        self.assertEqual(keys, ["project", "kind", "status", "created", "tags", "priority"])
        self.ok("set", "t", "priority", "1")
        self.assertEqual(list(meta_of(self.readme())), keys)

    def test_note_logged(self):
        self.ok("note", "t", "--", "--force was wrong")
        last = self.log()[-1]
        self.assertEqual((last["action"], last["text"], last["slug"]), ("note", "--force was wrong", "t"))
        self.assertEqual(run_cli(["note", "t", " "])[0], 1)

    def test_note_on_goal_uses_goal_key(self):
        hq_registry.create_goal("g")
        self.ok("note", "goal/g", "hi")
        last = self.log()[-1]
        self.assertEqual(last["goal"], "g")
        self.assertNotIn("project", last)

    def test_block_unblock_roundtrip(self):
        self.ok("block", "t", "waiting: on keys")
        self.assertIn('blocked: "waiting: on keys"\n', self.readme().read_text(encoding="utf-8"))
        self.assertIn("blocked", self.ok("list"))
        self.ok("unblock", "t")
        self.assertNotIn("blocked", meta_of(self.readme()))
        self.assertEqual(run_cli(["unblock", "t"])[0], 1)

    def test_block_multiline_reason_stays_valid(self):
        self.ok("block", "t", "a\nb")
        self.assertEqual(meta_of(self.readme())["blocked"], "a\nb")
        self.assertEqual(meta_of(self.readme())["status"], "planning")

    def test_block_archived_errors(self):
        self.ok("archive", "t")
        self.assertEqual(run_cli(["block", "t", "x"])[0], 1)

    def test_unstart_keeps_fields(self):
        self.ok("set", "t", "priority", "1")
        self.ok("start", "t")
        out = self.ok("unstart", "t", "--reason", "swap")
        self.assertFalse(self.readme("active").parent.exists())
        m = meta_of(self.readme())
        self.assertEqual((m["priority"], m["status"]), ("P1", "planning"))
        self.assertEqual(out.strip(), str(self.readme()))
        self.assertEqual(self.log()[-1]["reason"], "swap")

    def test_unstart_requires_active(self):
        code, _, err = run_cli(["unstart", "t"])
        self.assertEqual(code, 1)
        self.assertIn("'t' is not active", err)

    def test_show_entry_json(self):
        self.ok("set", "t", "priority", "1")
        self.ok("note", "t", "n1")
        folder = self.readme().parent
        (folder / "notes.md").write_text("x", encoding="utf-8")
        (folder / ".artifacts.json").write_text("{}", encoding="utf-8")
        d = json.loads(self.ok("show", "t", "--json"))
        self.assertEqual(d["record"]["priority"], "P1")
        self.assertIn("# t", d["body"])
        self.assertEqual(d["files"], ["notes.md"])
        self.assertEqual([e["action"] for e in d["log"]], ["save", "set", "note"])
        self.assertNotIn("tasks", d)

    def test_show_text(self):
        self.ok("note", "t", "n1")
        out = self.ok("show", "t")
        self.assertTrue(out.startswith("t\n"))
        self.assertIn("priority: P3", out)
        self.assertIn("log:", out)
        self.assertIn("note text=n1", out)

    def test_show_goal_lists_tasks(self):
        hq_registry.create_goal("g")
        self.ok("save", "task", "a", "--project", "p", "--goal", "g")
        self.ok("save", "task", "b", "--project", "p", "--goal", "g")
        self.ok("note", "goal/g", "hello")
        d = json.loads(self.ok("show", "goal/g", "--json"))
        self.assertEqual(len(d["tasks"]), 2)
        self.assertEqual(d["kind"], "goal")
        self.assertEqual([e["action"] for e in d["log"]], ["goal", "note"])
        self.assertIn("tasks:", self.ok("show", "goal/g"))

    def test_edit_commands_gated_in_classic(self):
        set_mode("classic")
        for argv in (["show", "t"], ["set", "t", "priority", "1"], ["note", "t", "x"],
                     ["block", "t", "x"], ["unblock", "t"], ["unstart", "t"]):
            code, _, err = run_cli(argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(err, f"hq: '{argv[0]}' needs advanced mode — run: hq init --mode advanced\n")


if __name__ == "__main__":
    unittest.main()
