import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hq_core
import hq_serve


class TestRenderIndex(unittest.TestCase):
    def test_links_entry_to_readme_or_index_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            orig, hq_core.HQ_ROOT = hq_core.HQ_ROOT, Path(tmp)
            try:
                for slug, extra in (("plain", None), ("rich", "index.html")):
                    d = hq_core.task_path("p", "active", slug)
                    d.mkdir(parents=True)
                    (d / "README.md").write_text("---\nkind: task\n---\n# T\n", encoding="utf-8")
                    if extra:
                        (d / extra).write_text("<p>x</p>", encoding="utf-8")
                page = hq_serve.render_index()
                self.assertIn('href="/projects/p/active/plain/README.md"', page)
                self.assertIn('href="/projects/p/active/rich/"', page)
            finally:
                hq_core.HQ_ROOT = orig

    def test_lists_artifacts_outside_readme_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            orig, hq_core.HQ_ROOT = hq_core.HQ_ROOT, Path(tmp)
            try:
                root = Path(tmp)
                (root / "learnings").mkdir()
                (root / "learnings" / "note.md").write_text("# n", encoding="utf-8")
                (root / "projects").mkdir()
                (root / "projects" / "loose.html").write_text("<p>x</p>", encoding="utf-8")
                (root / "projects" / "p" / "active" / "no-readme").mkdir(parents=True)
                page = hq_serve.render_index()
                self.assertIn('href="/learnings/note.md"', page)
                self.assertIn('href="/projects/loose.html"', page)
                self.assertIn('href="/projects/p/active/no-readme/"', page)
            finally:
                hq_core.HQ_ROOT = orig


if __name__ == "__main__":
    unittest.main()
