import json
import unittest

import hq_core
import hq_registry
from helpers import TempRoot, run_cli, set_mode

import hq_check


def write(rel, text):
    p = hq_core.HQ_ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def entry(status="planning", extra=""):
    return f"---\nkind: task\nstatus: {status}\ncreated: 2026-01-01\ntags: []\n{extra}---\n\n# T\n"


E_PATH = "projects/p/planning/t/README.md"


class CheckTests(TempRoot):
    def setUp(self):
        super().setUp()
        set_mode("advanced")

    def probs(self):
        return hq_check.run_checks()

    def only(self, problem, path=E_PATH):
        self.assertEqual(self.probs(), [{"path": path, "problem": problem}])

    def test_clean_store_ok(self):
        write(E_PATH, entry(extra="priority: P2\ndue: 2026-05-01\nest: 1h\narea: work\n"))
        code, out, _ = run_cli(["check"])
        self.assertEqual((code, out), (0, "ok\n"))

    def test_check_gated_in_classic(self):
        set_mode("classic")
        code, out, err = run_cli(["check"])
        self.assertEqual(code, 1)
        self.assertIn("'check' needs advanced mode", err)

    def test_status_mismatch(self):
        write(E_PATH, entry("active"))
        self.only("status 'active' does not match folder 'planning'")

    def test_missing_frontmatter(self):
        write(E_PATH, "# T\n")
        self.only("missing frontmatter")

    def test_bad_priority(self):
        write(E_PATH, entry(extra="priority: P9\n"))
        self.only("bad priority 'P9'")

    def test_bad_dates(self):
        write(E_PATH, entry(extra="due: nope\ndo-on: 2026-13-01\n"))
        self.assertEqual({p["problem"] for p in self.probs()},
                         {"bad date in due 'nope'", "bad date in do-on '2026-13-01'"})

    def test_bad_est(self):
        write(E_PATH, entry(extra="est: abc\n"))
        self.only("bad est 'abc'")

    def test_bad_area(self):
        write(E_PATH, entry(extra="area: moon\n"))
        self.only("bad area 'moon'")

    def test_unknown_goal(self):
        write(E_PATH, entry(extra="goal: ghost\n"))
        self.only("unknown goal 'ghost'")

    def test_known_goal_ok(self):
        hq_registry.create_goal("Real")
        write(E_PATH, entry(extra="goal: real\n"))
        self.assertEqual(self.probs(), [])

    def test_goal_status_and_fields(self):
        write("goals/g/README.md",
              "---\nkind: goal\nstatus: paused\npriority: 7\ntarget: x\narea: moon\n---\n\n# G\n")
        self.assertEqual({p["problem"] for p in self.probs()}, {
            "goal status 'paused' is not one of active, done, dropped",
            "bad priority '7'", "bad date in target 'x'", "bad area 'moon'"})
        self.assertTrue(all(p["path"] == "goals/g/README.md" for p in self.probs()))

    def test_sync_conflict(self):
        write("projects/p/planning/t/README.sync-conflict-20260101-abc.md", "x")
        write(".hq/Foo (Conflicted Copy).txt", "x")
        write(".git/x.sync-conflict-1", "x")
        self.assertEqual(self.probs(), [
            {"path": ".hq/Foo (Conflicted Copy).txt", "problem": "sync conflict copy"},
            {"path": "projects/p/planning/t/README.sync-conflict-20260101-abc.md",
             "problem": "sync conflict copy"}])

    def test_projects_json_invalid(self):
        write(".hq/projects.json", "{nope")
        self.only("projects.json is not valid JSON", ".hq/projects.json")

    def test_robust_to_weird_values(self):
        write(E_PATH, entry(extra="priority: [a]\nest: ²\ndue: [x]\narea: [y]\ngoal: [z]\n"))
        probs = {p["problem"] for p in self.probs()}
        self.assertIn("bad priority '['a']'", probs)
        self.assertIn("bad est '²'", probs)

    def test_read_only_no_log(self):
        write(E_PATH, entry("active", "priority: P9\n"))
        log = hq_core.HQ_ROOT / ".log.jsonl"
        log.write_text("", encoding="utf-8")
        run_cli(["check"])
        self.assertEqual(log.read_text(encoding="utf-8"), "")

    def test_cli_output_and_json(self):
        write(E_PATH, entry(extra="priority: P9\n"))
        code, out, _ = run_cli(["check"])
        self.assertEqual((code, out), (1, f"{E_PATH}: bad priority 'P9'\n"))
        code, out, _ = run_cli(["check", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual([json.loads(l) for l in out.splitlines()],
                         [{"path": E_PATH, "problem": "bad priority 'P9'"}])


if __name__ == "__main__":
    unittest.main()
