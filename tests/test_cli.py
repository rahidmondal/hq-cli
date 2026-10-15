import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hq
import hq_core


class TestCliSave(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = hq.main(argv)
        return code, buf.getvalue()

    def test_save_creates_file_and_prints_path(self):
        code, out = self._run(["save", "task", "CLI Task", "--project", "demo"])
        self.assertEqual(code, 0)
        expected = hq_core.HQ_ROOT / "projects" / "demo" / "planning" / "cli-task" / "README.md"
        self.assertTrue(expected.is_file())
        self.assertIn(str(expected), out)

    def test_save_bad_kind_errors_with_nonzero_exit(self):
        code, out = self._run(["save", "nonsense", "Title", "--project", "demo"])
        self.assertNotEqual(code, 0)

    def test_save_learning_with_project_errors_with_nonzero_exit(self):
        code, out = self._run(["save", "learning", "A Lesson", "--project", "demo"])
        self.assertEqual(code, 1)


class TestCliStart(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = hq.main(argv)
        return code, buf.getvalue()

    def test_start_promotes_task(self):
        self._run(["save", "task", "Start Me", "--project", "demo"])
        code, out = self._run(["start", "start-me"])
        self.assertEqual(code, 0)
        self.assertTrue(hq_core.task_path("demo", "active", "start-me").is_dir())


class TestCliArchive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = hq.main(argv)
        return code, buf.getvalue()

    def test_archive_moves_task(self):
        self._run(["save", "task", "Archive Via CLI", "--project", "demo"])
        code, out = self._run(["archive", "archive-via-cli"])
        self.assertEqual(code, 0)
        self.assertTrue(hq_core.task_path("demo", "archive", "archive-via-cli").is_dir())


class TestCliList(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = hq.main(argv)
        return code, buf.getvalue()

    def test_list_prints_saved_task(self):
        self._run(["save", "task", "Listed Via CLI", "--project", "demo"])
        code, out = self._run(["list"])
        self.assertEqual(code, 0)
        self.assertIn("demo", out)
        self.assertIn("listed-via-cli", out)

    def test_list_empty_prints_placeholder(self):
        code, out = self._run(["list"])
        self.assertEqual(code, 0)
        self.assertIn("no entries", out)

    def test_list_json_outputs_one_json_object_per_line(self):
        self._run(["save", "task", "Json Listed", "--project", "demo"])
        code, out = self._run(["list", "--json"])
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["project"], "demo")
        self.assertEqual(entry["slug"], "json-listed")
        self.assertIsInstance(entry["path"], str)


class TestCliFind(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = hq.main(argv)
        return code, buf.getvalue()

    def test_find_prints_matching_slug(self):
        self._run(["save", "task", "Findable Perf Task", "--project", "demo"])
        code, out = self._run(["find", "perf"])
        self.assertEqual(code, 0)
        self.assertIn("findable-perf-task", out)

    def test_find_no_match_prints_nothing_useful(self):
        code, out = self._run(["find", "zzz-nothing"])
        self.assertEqual(code, 0)
        self.assertIn("no matches", out)

    def test_find_json_outputs_one_json_object_per_line(self):
        self._run(["save", "task", "Json Findable", "--project", "demo"])
        code, out = self._run(["find", "findable", "--json"])
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["slug"], "json-findable")
        self.assertIsInstance(entry["path"], str)


class TestCliLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = Path(self._tmp.name)

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        self._tmp.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = hq.main(argv)
        return code, buf.getvalue()

    def test_log_prints_save_action(self):
        self._run(["save", "task", "Logged CLI Task", "--project", "demo"])
        code, out = self._run(["log"])
        self.assertEqual(code, 0)
        self.assertIn('"action": "save"', out)
        self.assertIn('"slug": "logged-cli-task"', out)

    def test_log_filters_by_project(self):
        self._run(["save", "task", "A", "--project", "proj-a"])
        self._run(["save", "task", "B", "--project", "proj-b"])
        code, out = self._run(["log", "--project", "proj-a"])
        self.assertIn('"project": "proj-a"', out)
        self.assertNotIn('"project": "proj-b"', out)

    def test_log_filters_by_since(self):
        log_path = hq_core.HQ_ROOT / ".log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-01-01T00:00:00+00:00", "action": "save", "slug": "old"}) + "\n")
            f.write(json.dumps({"ts": "2026-06-01T00:00:00+00:00", "action": "save", "slug": "new"}) + "\n")
        code, out = self._run(["log", "--since", "2026-03-01"])
        self.assertEqual(code, 0)
        self.assertIn('"slug": "new"', out)
        self.assertNotIn('"slug": "old"', out)


if __name__ == "__main__":
    unittest.main()
