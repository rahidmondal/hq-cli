import datetime
import unittest
from pathlib import Path

import hq_core
import hq_fields as f

TODAY = datetime.date(2026, 10, 22)


class TestFields(unittest.TestCase):
    def test_parse_priority_forms(self):
        self.assertEqual(f.parse_priority("p2"), "P2")
        self.assertEqual(f.parse_priority("2"), "P2")
        self.assertEqual(f.parse_priority("P1"), "P1")
        for bad in ("P5", "P0", "", "high"):
            with self.assertRaises(hq_core.HqError):
                f.parse_priority(bad)

    def test_parse_date_forms(self):
        p = lambda s: f.parse_date(s, today=TODAY)
        self.assertEqual(p("today"), "2026-10-22")
        self.assertEqual(p("tomorrow"), "2026-10-23")
        self.assertEqual(p("+3d"), "2026-10-25")
        self.assertEqual(p("+1w"), "2026-10-29")
        self.assertEqual(p("2026-11-01"), "2026-11-01")
        for bad in ("2026-13-01", "next friday", "2026-02-30", "2026-1-1", "+d", ""):
            with self.assertRaises(hq_core.HqError):
                p(bad)

    def test_parse_date_default_today(self):
        self.assertEqual(f.parse_date("today"), datetime.date.today().isoformat())

    def test_parse_est_forms(self):
        self.assertEqual(f.parse_est("20m"), 20)
        self.assertEqual(f.parse_est("1h"), 60)
        self.assertEqual(f.parse_est("1h30m"), 90)
        self.assertEqual(f.parse_est("90"), 90)
        for bad in ("0m", "abc", "", "0", "0h0m"):
            with self.assertRaises(hq_core.HqError):
                f.parse_est(bad)

    def test_format_est(self):
        self.assertEqual(f.format_est(20), "20m")
        self.assertEqual(f.format_est(60), "1h")
        self.assertEqual(f.format_est(90), "1h30m")

    def test_parse_area(self):
        self.assertEqual(f.parse_area("Work"), "work")
        with self.assertRaises(hq_core.HqError):
            f.parse_area("home")

    def test_normalize(self):
        self.assertEqual(f.normalize("priority", "1"), "P1")
        self.assertEqual(f.normalize("due", "+1d", today=TODAY), "2026-10-23")
        self.assertEqual(f.normalize("do-on", "today", today=TODAY), "2026-10-22")
        self.assertEqual(f.normalize("target", "2026-12-01"), "2026-12-01")
        self.assertEqual(f.normalize("est", "90"), "1h30m")
        self.assertEqual(f.normalize("goal", "My Goal!"), "my-goal")
        self.assertEqual(f.normalize("area", "personal"), "personal")
        with self.assertRaises(hq_core.HqError):
            f.normalize("bogus", "x")

    def _view(self, meta, **kw):
        args = dict(project="p", status="active", slug="s", title="T",
                    path=Path("x"), goal_areas={}, project_area="work")
        args.update(kw)
        return f.entry_view(meta, **args)

    def test_entry_view_defaults(self):
        v = self._view({"kind": "task", "created": "2026-08-01", "tags": []})
        self.assertEqual(v["priority"], "P3")
        self.assertEqual(v["area"], "work")
        for k in ("goal", "due", "do_on", "est", "blocked", "outcome"):
            self.assertIsNone(v[k], k)
        self.assertEqual(
            set(v),
            {"project", "status", "slug", "kind", "title", "created", "tags", "path",
             "priority", "area", "goal", "due", "do_on", "est", "blocked", "outcome"})
        self.assertEqual(v["tags"], [])
        self.assertEqual(v["title"], "T")

    def test_entry_view_area_precedence(self):
        v = self._view({"area": "personal", "goal": "g"}, goal_areas={"g": "work"})
        self.assertEqual(v["area"], "personal")
        v = self._view({"goal": "g"}, goal_areas={"g": "personal"})
        self.assertEqual(v["area"], "personal")
        v = self._view({"goal": "nope"}, goal_areas={"g": "personal"})
        self.assertEqual(v["area"], "work")
        v = self._view({"area": "bogus", "goal": "g"}, goal_areas={"g": "personal"})
        self.assertEqual(v["area"], "personal")

    def test_entry_view_bad_values_fall_back(self):
        v = self._view({"priority": "high", "due": "soon", "est": "lots", "do-on": "2026-02-30"})
        self.assertEqual(v["priority"], "P3")
        self.assertIsNone(v["due"])
        self.assertIsNone(v["est"])
        self.assertIsNone(v["do_on"])

    def test_entry_view_values(self):
        v = self._view({"est": "1h30m", "due": "2026-11-01", "do-on": "2026-10-30",
                        "priority": "p1", "blocked": "waiting", "outcome": "done", "goal": "g"})
        self.assertEqual(v["est"], 90)
        self.assertEqual(v["due"], "2026-11-01")
        self.assertEqual(v["do_on"], "2026-10-30")
        self.assertEqual(v["priority"], "P1")
        self.assertEqual(v["blocked"], "waiting")
        self.assertEqual(v["outcome"], "done")
        self.assertEqual(v["goal"], "g")
        self.assertIsNone(self._view({"blocked": ""})["blocked"])


if __name__ == "__main__":
    unittest.main()
