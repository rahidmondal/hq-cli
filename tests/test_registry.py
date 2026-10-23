import json
import unittest

import hq_core
import hq_registry
from hq_core import HqError
from helpers import TempRoot, run_cli, set_mode


class RegistryTests(TempRoot):
    def test_create_goal_writes_readme(self):
        p = hq_registry.create_goal("Ship the billing page", area="work", target="2026-10-31", priority="P2")
        self.assertEqual(p, hq_core.HQ_ROOT / "goals" / "ship-the-billing-page" / "README.md")
        meta, body = hq_core.frontmatter_parse(p.read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "goal")
        self.assertEqual(meta["status"], "active")
        self.assertEqual(meta["target"], "2026-10-31")
        self.assertEqual(list(meta)[:5], ["kind", "area", "status", "priority", "target"])
        self.assertTrue(body.lstrip().startswith("# Ship the billing page"))

    def test_create_goal_duplicate_errors(self):
        hq_registry.create_goal("Dup")
        with self.assertRaises(HqError):
            hq_registry.create_goal("Dup")

    def test_create_goal_empty_slug_errors(self):
        with self.assertRaises(HqError):
            hq_registry.create_goal("!!!")

    def test_list_goals_filters_and_defaults(self):
        hq_registry.create_goal("A goal", area="personal", priority="P1")
        hq_registry.create_goal("B goal")
        (hq_core.HQ_ROOT / "goals" / "empty-dir").mkdir()
        self.assertEqual(len(hq_registry.list_goals()), 2)
        personal = hq_registry.list_goals(area="personal")
        self.assertEqual([g["slug"] for g in personal], ["a-goal"])
        b = hq_registry.get_goal("b-goal")
        self.assertEqual(b["priority"], "P3")
        self.assertEqual(b["area"], "work")
        self.assertEqual(hq_registry.goal_areas(), {"a-goal": "personal", "b-goal": "work"})
        self.assertIsNone(hq_registry.get_goal("nope"))

    def test_list_goals_tolerates_bad_data(self):
        d = hq_core.HQ_ROOT / "goals" / "bad"
        d.mkdir(parents=True)
        (d / "README.md").write_text("---\nkind: goal\narea: moon\npriority: zz\nstatus: weird\n---\n\n# Bad\n", encoding="utf-8")
        g = hq_registry.get_goal("bad")
        self.assertEqual((g["area"], g["priority"], g["status"]), ("work", "P3", "active"))

    def test_finish_goal_dropped(self):
        hq_registry.create_goal("Gone")
        p = hq_registry.finish_goal("gone", dropped=True)
        meta, _ = hq_core.frontmatter_parse(p.read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "dropped")
        last = hq_core.read_log()[-1]
        self.assertEqual((last["action"], last["op"], last["slug"]), ("goal", "dropped", "gone"))
        with self.assertRaises(HqError):
            hq_registry.finish_goal("missing")

    def test_record_repo_dedupes(self):
        from pathlib import Path
        hq_registry.record_repo("demo", Path("/x/y"))
        hq_registry.record_repo("demo", Path("/x/y"))
        data = json.loads(hq_registry.projects_path().read_text(encoding="utf-8"))
        self.assertEqual(len(data["demo"]["repos"]), 1)

    def test_load_projects_invalid(self):
        hq_registry.projects_path().parent.mkdir(parents=True, exist_ok=True)
        hq_registry.projects_path().write_text("{nope", encoding="utf-8")
        with self.assertRaises(HqError):
            hq_registry.load_projects()

    def test_project_area_defaults(self):
        self.assertEqual(hq_registry.project_area("x"), "work")
        self.assertEqual(hq_registry.project_area("personal"), "personal")
        hq_registry.set_project_area("x", "personal")
        self.assertEqual(hq_registry.project_area("x"), "personal")


class RegistryCliTests(TempRoot):
    def test_goal_new_and_list_json(self):
        set_mode("advanced")
        code, out, err = run_cli(["goal", "new", "G", "--area", "personal", "--target", "+7d"])
        self.assertEqual(code, 0, err)
        code, out, err = run_cli(["goal", "list", "--json"])
        lines = out.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["area"], "personal")
        code, out, _ = run_cli(["goal", "list"])
        self.assertEqual(out.splitlines()[0].split()[:6], ["P", "AREA", "STATUS", "TARGET", "SLUG", "TITLE"])

    def test_goal_list_empty_and_done(self):
        set_mode("advanced")
        self.assertEqual(run_cli(["goal", "list"])[1].strip(), "(no goals)")
        run_cli(["goal", "new", "G"])
        self.assertEqual(run_cli(["goal", "done", "g"])[0], 0)
        self.assertEqual(hq_registry.get_goal("g")["status"], "done")
        self.assertEqual(run_cli(["goal", "list", "--status", "active"])[1].strip(), "(no goals)")

    def test_classic_gated(self):
        code, out, err = run_cli(["goal", "list"])
        self.assertEqual(code, 1)
        self.assertIn("needs advanced mode", err)
        self.assertEqual(run_cli(["project", "set", "demo", "area", "personal"])[0], 1)

    def test_project_set(self):
        set_mode("advanced")
        self.assertEqual(run_cli(["project", "set", "demo", "area", "personal"])[0], 0)
        self.assertEqual(hq_registry.project_area("demo"), "personal")
        self.assertEqual(run_cli(["project", "set", "demo", "area", "home"])[0], 1)


if __name__ == "__main__":
    unittest.main()
