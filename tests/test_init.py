import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hq_init
from hq_core import HqError


class TestInit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        patches = [
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(hq_init, "SKILL_TARGET", self.tmp / "skills" / "hq" / "SKILL.md"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("HQ_ROOT", None)
        self.addCleanup(self._tmp.cleanup)

    def test_requires_a_root(self):
        with self.assertRaises(HqError):
            hq_init.init(None, install_skill=False)

    def test_creates_folders_and_flags_unset_env(self):
        root = self.tmp / "data"
        report = "\n".join(hq_init.init(str(root), install_skill=False))
        for sub in ("projects", "learnings", "skills"):
            self.assertTrue((root / sub).is_dir())
        self.assertIn("[todo] HQ_ROOT", report)

    def test_env_matching_root_is_ok_and_skill_installs(self):
        root = self.tmp / "data"
        os.environ["HQ_ROOT"] = str(root)
        report = "\n".join(hq_init.init(None, install_skill=True))
        self.assertIn("[ok] HQ_ROOT points at it", report)
        self.assertTrue(hq_init.SKILL_TARGET.is_file())

    def _advanced_root(self):
        root = self.tmp / "data"
        hq_init.init(str(root), install_skill=False, mode="advanced")
        return root

    def test_advanced_mode_installs_and_updates_the_advanced_skill(self):
        classic = self.tmp / "classic"
        hq_init.init(str(classic), install_skill=True)
        self.assertEqual(hq_init.SKILL_TARGET.read_bytes(), hq_init.SKILL_TEMPLATE.read_bytes())
        root = self._advanced_root()
        report = "\n".join(hq_init.init(str(root), install_skill=False))
        self.assertIn("isn't the advanced-mode one", report)
        report = "\n".join(hq_init.init(str(root), install_skill=True))
        self.assertIn("updated Claude Code skill for advanced mode", report)
        self.assertEqual(hq_init.SKILL_TARGET.read_bytes(), hq_init.SKILL_ADVANCED.read_bytes())
        self.assertIn("[ok] Claude Code skill installed", "\n".join(hq_init.init(str(root), False)))

    def test_autostart_on_and_off(self):
        import hq_autostart
        import hq_core

        root = self._advanced_root()
        item = self.tmp / "login" / "hq-serve.item"
        with mock.patch.object(hq_autostart, "target", return_value=item):
            report = "\n".join(hq_init.init(str(root), False, autostart=True))
            self.assertIn("starts at login", report)
            text = item.read_bytes().decode("utf-8")
            self.assertIn(str(root), text)
            self.assertIn("serve --no-open", text)
            orig = hq_core.HQ_ROOT
            hq_core.HQ_ROOT = root
            try:
                self.assertTrue(hq_core.load_config()["autostart"])
            finally:
                hq_core.HQ_ROOT = orig
            report = "\n".join(hq_init.init(str(root), False, autostart=False))
            self.assertIn("removed the login item", report)
            self.assertFalse(item.exists())

    def test_autostart_needs_advanced(self):
        with self.assertRaises(HqError):
            hq_init.init(str(self.tmp / "c"), False, autostart=True)


if __name__ == "__main__":
    unittest.main()
