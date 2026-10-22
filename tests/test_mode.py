import json
import os
import unittest
from unittest import mock

from helpers import TempRoot, set_mode, run_cli
import hq_core
import hq_init


class TestMode(TempRoot):
    def _last_log(self):
        lines = (hq_core.HQ_ROOT / ".log.jsonl").read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1])

    def _write_config(self, text):
        hq_core.config_path().parent.mkdir(parents=True, exist_ok=True)
        hq_core.config_path().write_text(text, encoding="utf-8")

    def test_missing_config_is_classic(self):
        self.assertEqual(hq_core.mode(), "classic")

    def test_invalid_config_is_classic(self):
        self._write_config("{")
        self.assertEqual(hq_core.mode(), "classic")

    def test_init_mode_advanced_writes_config(self):
        report = hq_init.init(str(hq_core.HQ_ROOT), False, mode="advanced")
        self.assertEqual(hq_core.load_config(), {"mode": "advanced", "autostart": False})
        self.assertIn("[ok] mode: advanced", report)

    def test_init_mode_preserves_other_keys(self):
        self._write_config(json.dumps({"mode": "advanced", "fetch": False}))
        hq_init.init(str(hq_core.HQ_ROOT), False, mode="classic")
        self.assertEqual(hq_core.load_config(), {"mode": "classic", "fetch": False})

    def test_init_without_mode_has_no_mode_line_when_no_config(self):
        report = hq_init.init(str(hq_core.HQ_ROOT), False)
        self.assertFalse([l for l in report if l.startswith("[ok] mode")])

    def test_advanced_command_in_classic_errors(self):
        code, _, err = run_cli(["show", "x"])
        self.assertEqual(code, 1)
        self.assertEqual(err, "hq: 'show' needs advanced mode — run: hq init --mode advanced\n")

    def test_by_flag_tags_log_in_advanced(self):
        set_mode("advanced")
        run_cli(["--by", "agent", "save", "task", "T", "--project", "p"])
        self.assertEqual(self._last_log()["by"], "agent")

    def test_hq_actor_env_used_when_no_flag(self):
        set_mode("advanced")
        with mock.patch.dict(os.environ, {"HQ_ACTOR": "agent"}):
            run_cli(["save", "task", "T", "--project", "p"])
        self.assertEqual(self._last_log()["by"], "agent")
        env = {k: v for k, v in os.environ.items() if k != "HQ_ACTOR"}
        with mock.patch.dict(os.environ, env, clear=True):
            run_cli(["save", "task", "U", "--project", "p"])
        self.assertEqual(self._last_log()["by"], "user")

    def test_classic_log_has_no_by_key(self):
        run_cli(["--by", "agent", "save", "task", "T", "--project", "p"])
        self.assertNotIn("by", self._last_log())


if __name__ == "__main__":
    unittest.main()
