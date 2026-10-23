import unittest
from datetime import date

import hq_today

TODAY = date(2026, 10, 23)


def rec(slug, **kw):
    base = {"project": "p", "status": "planning", "slug": slug, "kind": "task", "title": slug,
            "created": "2026-10-01", "tags": [], "priority": "P3", "area": "work", "goal": None,
            "due": None, "do_on": None, "est": None, "blocked": None, "outcome": None}
    base.update(kw)
    return base


def goal(slug, target, status="active"):
    return {"slug": slug, "title": slug, "area": "work", "status": status, "priority": "P2",
            "target": target, "created": "2026-10-01", "tags": []}


def keys(sections):
    return {s["key"]: [r["slug"] for r in s["items"]] for s in sections}


class BuildTests(unittest.TestCase):
    def test_sections_and_order(self):
        records = [
            rec("late", due="2026-10-20"),
            rec("due-today", due="2026-10-23", priority="P1"),
            rec("planned", do_on="2026-10-22"),
            rec("future", do_on="2026-10-30"),
            rec("in-goal", goal="sprint"),
            rec("far-goal", goal="later"),
            rec("hot", status="active", priority="P2"),
            rec("cold", status="active", priority="P3"),
            rec("stuck", blocked="waiting", due="2026-10-01"),
            rec("done", status="archive", due="2026-10-01"),
        ]
        goals = [goal("sprint", "2026-10-28"), goal("later", "2026-12-01")]
        got = keys(hq_today.build(records, goals, TODAY))
        self.assertEqual(list(got), ["due", "planned", "goals", "top", "blocked"])
        self.assertEqual(got["due"], ["due-today", "late"])  # priority first
        self.assertEqual(got["planned"], ["planned"])
        self.assertEqual(got["goals"], ["in-goal"])
        self.assertEqual(got["top"], ["hot"])
        self.assertEqual(got["blocked"], ["stuck"])

    def test_entry_appears_once_in_highest_section(self):
        records = [rec("both", due="2026-10-23", do_on="2026-10-23", status="active", priority="P1")]
        got = keys(hq_today.build(records, [], TODAY))
        self.assertEqual(got, {"due": ["both"]})

    def test_closed_goal_and_area_filter(self):
        records = [rec("a", goal="g"), rec("b", do_on="2026-10-23", area="personal")]
        self.assertEqual(keys(hq_today.build(records, [goal("g", "2026-10-24", status="done")], TODAY)),
                         {"planned": ["b"]})
        self.assertEqual(hq_today.build(records, [], TODAY, area="work"), [])

    def test_when_labels(self):
        records = [rec("late", due="2026-10-21"), rec("yday", due="2026-10-22"), rec("now", due="2026-10-23"),
                   rec("p", do_on="2026-10-20"), rec("g", goal="sprint")]
        items = {r["slug"]: r["when"] for s in hq_today.build(records, [goal("sprint", "2026-10-25")], TODAY)
                 for r in s["items"]}
        self.assertEqual(items, {"late": "due 2 days ago", "yday": "due yesterday", "now": "due today",
                                 "p": "planned 3 days ago", "g": "goal due in 2d"})


class FreeTests(unittest.TestCase):
    def test_fits_and_ranks(self):
        records = [
            rec("big", est=90),
            rec("p3", est=20),
            rec("p1", est=30, priority="P1"),
            rec("no-est"),
            rec("blocked", est=10, blocked="x"),
            rec("archived", est=10, status="archive"),
            rec("p3-due", est=25, due="2026-10-24"),
        ]
        self.assertEqual([r["slug"] for r in hq_today.free(records, 30)], ["p1", "p3-due", "p3"])

    def test_limit_and_area(self):
        records = [rec(f"t{i}", est=10) for i in range(8)] + [rec("home", est=10, area="personal")]
        self.assertEqual(len(hq_today.free(records, 30)), 5)
        self.assertEqual([r["slug"] for r in hq_today.free(records, 30, area="personal")], ["home"])


if __name__ == "__main__":
    unittest.main()
