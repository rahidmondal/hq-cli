import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hq_core


class TestSlugify(unittest.TestCase):
    def test_lowercases_and_dashes(self):
        self.assertEqual(hq_core.slugify("UI/UX Improvement"), "ui-ux-improvement")

    def test_strips_leading_trailing_dashes(self):
        self.assertEqual(hq_core.slugify("  --Retriever Port!!--  "), "retriever-port")

    def test_collapses_repeated_separators(self):
        self.assertEqual(hq_core.slugify("a   b---c"), "a-b-c")


class TestFrontmatter(unittest.TestCase):
    def test_parse_basic(self):
        text = (
            "---\n"
            "project: retriever-port\n"
            "kind: task\n"
            "status: active\n"
            "created: 2026-08-07\n"
            "tags: [perf, indexing]\n"
            "---\n"
            "\n"
            "# Retriever Port\n"
            "\n"
            "Notes here.\n"
        )
        meta, body = hq_core.frontmatter_parse(text)
        self.assertEqual(meta["project"], "retriever-port")
        self.assertEqual(meta["kind"], "task")
        self.assertEqual(meta["tags"], ["perf", "indexing"])
        self.assertIn("# Retriever Port", body)

    def test_parse_no_frontmatter_returns_empty_meta(self):
        meta, body = hq_core.frontmatter_parse("# Just a heading\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "# Just a heading\n")

    def test_dump_then_parse_round_trips(self):
        meta = {"project": "demo", "kind": "task", "status": "planning",
                 "created": "2026-08-09", "tags": ["a", "b"]}
        text = hq_core.frontmatter_dump(meta, "# Demo\n\nbody text\n")
        parsed_meta, parsed_body = hq_core.frontmatter_parse(text)
        self.assertEqual(parsed_meta, meta)
        self.assertIn("body text", parsed_body)


class TestPathsAndLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_task_path_layout(self):
        p = hq_core.task_path("demo", "planning", "my-task")
        self.assertEqual(p, hq_core.HQ_ROOT / "projects" / "demo" / "planning" / "my-task")

    def test_learning_path_layout(self):
        p = hq_core.learning_path("my-lesson")
        self.assertEqual(p, hq_core.HQ_ROOT / "learnings" / "my-lesson.md")

    def test_skill_path_layout(self):
        p = hq_core.skill_path("my-skill")
        self.assertEqual(p, hq_core.HQ_ROOT / "skills" / "my-skill")

    def test_detect_project_uses_override(self):
        self.assertEqual(hq_core.detect_project(Path("."), "My Repo"), "my-repo")

    def test_detect_project_falls_back_to_cwd_name(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = Path(d) / "Some Repo"
            cwd.mkdir()
            self.assertEqual(hq_core.detect_project(cwd, None), "some-repo")

    def test_find_task_empty_when_no_projects_dir(self):
        self.assertEqual(hq_core.find_task("nope"), [])

    def test_find_task_finds_across_statuses(self):
        target = hq_core.task_path("demo", "active", "my-task")
        target.mkdir(parents=True)
        matches = hq_core.find_task("my-task")
        self.assertEqual(matches, [target])

    def test_extract_title_reads_first_heading(self):
        body = "\nsome text\n# The Title\nmore text\n"
        self.assertEqual(hq_core.extract_title(body), "The Title")

    def test_extract_title_empty_when_no_heading(self):
        self.assertEqual(hq_core.extract_title("no heading here\n"), "")

    def test_log_action_appends_jsonl(self):
        hq_core.log_action("save", project="demo", slug="my-task")
        entries = hq_core.read_log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "save")
        self.assertEqual(entries[0]["project"], "demo")
        self.assertIn("ts", entries[0])

    def test_read_log_filters_by_project(self):
        hq_core.log_action("save", project="a", slug="x")
        hq_core.log_action("save", project="b", slug="y")
        entries = hq_core.read_log(project="a")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["project"], "a")

    def test_read_log_skips_malformed_lines(self):
        hq_core.log_action("save", project="a", slug="x")
        log_path = hq_core.HQ_ROOT / ".log.jsonl"
        with log_path.open("a", encoding="utf-8") as f:
            f.write("not valid json\n")
        hq_core.log_action("save", project="a", slug="y")
        entries = hq_core.read_log(project="a")
        self.assertEqual(len(entries), 2)
        self.assertEqual([e["slug"] for e in entries], ["x", "y"])


class TestSave(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_save_task_creates_planning_readme(self):
        path = hq_core.save("task", "My New Task", project_override="demo")
        self.assertTrue(path.is_file())
        self.assertEqual(path, hq_core.HQ_ROOT / "projects" / "demo" / "planning" / "my-new-task" / "README.md")
        meta, body = hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["project"], "demo")
        self.assertEqual(meta["kind"], "task")
        self.assertEqual(meta["status"], "planning")
        self.assertIn("# My New Task", body)

    def test_save_learning_skips_project_and_lifecycle(self):
        path = hq_core.save("learning", "A Lesson Learned")
        self.assertEqual(path, hq_core.HQ_ROOT / "learnings" / "a-lesson-learned.md")
        meta, _ = hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "learning")
        self.assertNotIn("project", meta)

    def test_save_learning_rejects_project_override(self):
        with self.assertRaises(hq_core.HqError):
            hq_core.save("learning", "A Lesson Learned", project_override="demo")

    def test_save_skill_rejects_project_override(self):
        with self.assertRaises(hq_core.HqError):
            hq_core.save("skill", "My Great Skill", project_override="demo")

    def test_save_skill_creates_readme_and_skill_md(self):
        path = hq_core.save("skill", "My Great Skill")
        self.assertEqual(path, hq_core.HQ_ROOT / "skills" / "my-great-skill" / "README.md")
        self.assertTrue(path.is_file())
        skill_md = path.parent / "SKILL.md"
        self.assertTrue(skill_md.is_file())
        skill_meta, _ = hq_core.frontmatter_parse(skill_md.read_text(encoding="utf-8"))
        self.assertEqual(skill_meta["name"], "my-great-skill")
        self.assertEqual(skill_meta["description"], "My Great Skill")
        readme_meta, _ = hq_core.frontmatter_parse(path.read_text(encoding="utf-8"))
        self.assertEqual(readme_meta["kind"], "skill")
        self.assertNotIn("project", readme_meta)

    def test_save_skill_rejects_duplicate(self):
        hq_core.save("skill", "Dup Skill")
        with self.assertRaises(hq_core.HqError):
            hq_core.save("skill", "Dup Skill")

    def test_save_rejects_unknown_kind(self):
        with self.assertRaises(hq_core.HqError):
            hq_core.save("nonsense", "Title", project_override="demo")

    def test_save_rejects_duplicate_slug(self):
        hq_core.save("task", "Dup Task", project_override="demo")
        with self.assertRaises(hq_core.HqError):
            hq_core.save("task", "Dup Task", project_override="demo")

    def test_save_logs_action(self):
        hq_core.save("task", "Logged Task", project_override="demo")
        entries = hq_core.read_log(project="demo")
        self.assertEqual(entries[-1]["action"], "save")
        self.assertEqual(entries[-1]["slug"], "logged-task")


class TestStart(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_start_moves_planning_to_active(self):
        hq_core.save("task", "Move Me", project_override="demo")
        dest = hq_core.start("move-me")
        self.assertEqual(dest, hq_core.task_path("demo", "active", "move-me"))
        self.assertTrue(dest.is_dir())
        self.assertFalse(hq_core.task_path("demo", "planning", "move-me").exists())
        meta, _ = hq_core.frontmatter_parse((dest / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "active")

    def test_start_raises_when_slug_not_in_planning(self):
        with self.assertRaises(hq_core.HqError):
            hq_core.start("does-not-exist")

    def test_start_raises_on_ambiguous_slug_across_projects(self):
        hq_core.save("task", "Shared Slug", project_override="proj-a")
        hq_core.save("task", "Shared Slug", project_override="proj-b")
        with self.assertRaises(hq_core.HqError):
            hq_core.start("shared-slug")

    def test_start_disambiguated_by_project(self):
        hq_core.save("task", "Shared Slug", project_override="proj-a")
        hq_core.save("task", "Shared Slug", project_override="proj-b")
        dest = hq_core.start("shared-slug", project_override="proj-a")
        self.assertEqual(dest, hq_core.task_path("proj-a", "active", "shared-slug"))

    def test_start_logs_action(self):
        hq_core.save("task", "Log Start", project_override="demo")
        hq_core.start("log-start")
        entries = hq_core.read_log(project="demo")
        self.assertEqual(entries[-1]["action"], "start")
        self.assertEqual(entries[-1]["from_status"], "planning")
        self.assertEqual(entries[-1]["to_status"], "active")

    def test_start_rejects_invalid_slug(self):
        with self.assertRaises(hq_core.HqError):
            hq_core.start("../../escape")

    def test_start_raises_cleanly_when_readme_missing(self):
        planning_dir = hq_core.task_path("demo", "planning", "no-readme")
        planning_dir.mkdir(parents=True)
        with self.assertRaises(hq_core.HqError):
            hq_core.start("no-readme")
        self.assertTrue(planning_dir.is_dir())
        self.assertFalse(hq_core.task_path("demo", "active", "no-readme").exists())
        self.assertEqual(hq_core.read_log(), [])


class TestArchive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_archive_from_planning(self):
        hq_core.save("task", "Archive Me", project_override="demo")
        dest = hq_core.archive("archive-me")
        self.assertEqual(dest, hq_core.task_path("demo", "archive", "archive-me"))
        meta, _ = hq_core.frontmatter_parse((dest / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "archive")

    def test_archive_from_active(self):
        hq_core.save("task", "Finish Me", project_override="demo")
        hq_core.start("finish-me")
        dest = hq_core.archive("finish-me")
        self.assertEqual(dest, hq_core.task_path("demo", "archive", "finish-me"))

    def test_archive_raises_when_not_found(self):
        with self.assertRaises(hq_core.HqError):
            hq_core.archive("does-not-exist")

    def test_archive_logs_from_status(self):
        hq_core.save("task", "Log Archive", project_override="demo")
        hq_core.archive("log-archive")
        entries = hq_core.read_log(project="demo")
        self.assertEqual(entries[-1]["action"], "archive")
        self.assertEqual(entries[-1]["from_status"], "planning")
        self.assertEqual(entries[-1]["to_status"], "archive")

    def test_archive_rejects_invalid_slug(self):
        with self.assertRaises(hq_core.HqError):
            hq_core.archive("../../escape")

    def test_archive_raises_cleanly_when_readme_missing(self):
        planning_dir = hq_core.task_path("demo", "planning", "no-readme")
        planning_dir.mkdir(parents=True)
        with self.assertRaises(hq_core.HqError):
            hq_core.archive("no-readme")
        self.assertTrue(planning_dir.is_dir())
        self.assertFalse(hq_core.task_path("demo", "archive", "no-readme").exists())
        self.assertEqual(hq_core.read_log(), [])


class TestListEntries(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_list_entries_empty_when_no_projects(self):
        self.assertEqual(hq_core.list_entries(), [])

    def test_list_entries_returns_saved_task(self):
        hq_core.save("task", "Listed Task", project_override="demo", tags=["x"])
        entries = hq_core.list_entries()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["project"], "demo")
        self.assertEqual(e["slug"], "listed-task")
        self.assertEqual(e["status"], "planning")
        self.assertEqual(e["kind"], "task")
        self.assertEqual(e["title"], "Listed Task")
        self.assertEqual(e["tags"], ["x"])

    def test_list_entries_filters_by_project(self):
        hq_core.save("task", "A Task", project_override="proj-a")
        hq_core.save("task", "B Task", project_override="proj-b")
        entries = hq_core.list_entries(project="proj-a")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["project"], "proj-a")

    def test_list_entries_filters_by_status(self):
        hq_core.save("task", "Planned", project_override="demo")
        hq_core.save("task", "Started", project_override="demo")
        hq_core.start("started")
        entries = hq_core.list_entries(status="active")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["slug"], "started")


class TestSearchEntries(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def test_search_matches_title(self):
        hq_core.save("task", "Retriever Indexing Perf", project_override="demo")
        results = hq_core.search_entries("indexing")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["slug"], "retriever-indexing-perf")

    def test_search_matches_tags(self):
        hq_core.save("task", "Tagged Task", project_override="demo", tags=["bm25"])
        results = hq_core.search_entries("bm25")
        self.assertEqual(len(results), 1)

    def test_search_includes_learnings(self):
        hq_core.save("learning", "Qdrant Filter Gotcha")
        results = hq_core.search_entries("qdrant")
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["project"])
        self.assertEqual(results[0]["slug"], "qdrant-filter-gotcha")

    def test_search_includes_skills(self):
        hq_core.save("skill", "Retry With Backoff")
        results = hq_core.search_entries("backoff")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["slug"], "retry-with-backoff")
        self.assertEqual(results[0]["kind"], "skill")

    def test_search_no_match_returns_empty(self):
        hq_core.save("task", "Unrelated", project_override="demo")
        self.assertEqual(hq_core.search_entries("zzz-nothing-matches"), [])

    def test_search_is_case_insensitive(self):
        hq_core.save("task", "CaseTest", project_override="demo")
        self.assertEqual(len(hq_core.search_entries("casetest")), 1)

    def test_search_does_not_match_frontmatter_key_names(self):
        hq_core.save("task", "Unrelated Content", project_override="demo")
        self.assertEqual(hq_core.search_entries("project"), [])
        self.assertEqual(hq_core.search_entries("tags"), [])


if __name__ == "__main__":
    unittest.main()
