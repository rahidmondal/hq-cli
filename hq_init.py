"""`hq init`: first-time setup. Creates the data folder and checks the three
things that silently go wrong: HQ_ROOT, PATH, and the Claude Code skill."""
import os
import shutil
import sys
from pathlib import Path

from hq_core import HqError

HERE = Path(__file__).resolve().parent
SKILL_TEMPLATE = HERE / "hq-skill-template.md"
SKILL_TARGET = Path.home() / ".claude" / "skills" / "hq" / "SKILL.md"
WINDOWS = sys.platform == "win32"


def _persist_root_cmd(root: Path) -> str:
    if WINDOWS:
        return f'setx HQ_ROOT "{root}"'
    return f"echo 'export HQ_ROOT=\"{root}\"' >> ~/.bashrc"


def _persist_path_cmd() -> str:
    if WINDOWS:
        return (
            '[Environment]::SetEnvironmentVariable("Path", '
            f'[Environment]::GetEnvironmentVariable("Path","User") + ";{HERE}", "User")'
        )
    return f"echo 'export PATH=\"{HERE}:$PATH\"' >> ~/.bashrc"


def init(root_arg: str | None, install_skill: bool) -> list[str]:
    """Create the data folder and return a report: '[ok] ...' / '[todo] ...' lines."""
    env_root = os.environ.get("HQ_ROOT")
    if root_arg:
        root = Path(root_arg).expanduser().resolve()
    elif env_root:
        root = Path(env_root).expanduser().resolve()
    else:
        raise HqError(
            "no data folder chosen. Pick where your archive should live, e.g.\n"
            "  hq init --root ~/hq-data"
        )

    for sub in ("projects", "learnings", "skills"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    report = [f"[ok] data folder ready: {root}"]

    if env_root and Path(env_root).expanduser().resolve() == root:
        report.append("[ok] HQ_ROOT points at it")
    else:
        report.append(
            "[todo] HQ_ROOT is not set to this folder, so hq would fall back to ~/.hq. "
            f"Persist it, then open a new terminal:\n       {_persist_root_cmd(root)}"
        )

    if shutil.which("hq"):
        report.append("[ok] `hq` is on PATH")
    else:
        report.append(
            f"[todo] `hq` is not on PATH. Add {HERE} to PATH, then open a new terminal:\n"
            f"       {_persist_path_cmd()}"
        )

    if SKILL_TARGET.is_file():
        report.append(f"[ok] Claude Code skill installed: {SKILL_TARGET}")
    elif install_skill:
        SKILL_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SKILL_TEMPLATE, SKILL_TARGET)
        report.append(f"[ok] installed Claude Code skill: {SKILL_TARGET}")
    else:
        report.append("[todo] optional: run `hq init --install-skill` to teach Claude Code the hq commands")

    return report
