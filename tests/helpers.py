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


class TempRoot(unittest.TestCase):
    """Swaps hq_core.HQ_ROOT to a temp dir and resets ACTOR for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = hq_core.HQ_ROOT
        self._orig_actor = hq_core.ACTOR
        hq_core.HQ_ROOT = Path(self._tmp.name)
        hq_core.ACTOR = None

    def tearDown(self):
        hq_core.HQ_ROOT = self._orig_root
        hq_core.ACTOR = self._orig_actor
        self._tmp.cleanup()


def set_mode(mode):
    cfg = hq_core.load_config()
    cfg["mode"] = mode
    hq_core.config_path().parent.mkdir(parents=True, exist_ok=True)
    hq_core.save_config(cfg)


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = hq.main(argv)
    return code, out.getvalue(), err.getvalue()
