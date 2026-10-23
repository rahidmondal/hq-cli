"""`hq init`: first-time setup. Creates the data folder and checks the three
things that silently go wrong: HQ_ROOT, PATH, and the Claude Code skill."""
import os
import shutil
import sys
from pathlib import Path

import hq_core
from hq_core import HqError

HERE = Path(__file__).resolve().parent
SKILL_TEMPLATE = HERE / "hq-skill-template.md"
SKILL_ADVANCED = HERE / "hq-skill-advanced.md"
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


def _root_mode(root: Path) -> str:
    orig = hq_core.HQ_ROOT
    hq_core.HQ_ROOT = root
    try:
        return hq_core.mode()
    finally:
        hq_core.HQ_ROOT = orig


def _skill_report(root: Path, install_skill: bool) -> str:
    """Classic: v1 behavior. Advanced: install the advanced skill, or flag an
    installed copy that isn't it (e.g. the classic one) so it can be updated."""
    advanced = _root_mode(root) == "advanced"
    template = SKILL_ADVANCED if advanced else SKILL_TEMPLATE
    if SKILL_TARGET.is_file():
        if not advanced or SKILL_TARGET.read_bytes() == template.read_bytes():
            return f"[ok] Claude Code skill installed: {SKILL_TARGET}"
        if install_skill:
            shutil.copyfile(template, SKILL_TARGET)
            return f"[ok] updated Claude Code skill for advanced mode: {SKILL_TARGET}"
        return ("[todo] the installed Claude Code skill isn't the advanced-mode one; "
                "run `hq init --install-skill` to update it")
    if install_skill:
        SKILL_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, SKILL_TARGET)
        return f"[ok] installed Claude Code skill: {SKILL_TARGET}"
    return "[todo] optional: run `hq init --install-skill` to teach Claude Code the hq commands"


def init(root_arg: str | None, install_skill: bool, mode: str | None = None,
         autostart: bool | None = None) -> list[str]:
    """Create the data folder and return a report: '[ok] ...' / '[todo] ...' lines."""
    if mode is not None and mode not in hq_core.MODES:
        raise HqError(f"invalid mode {mode!r}; choose from {', '.join(hq_core.MODES)}")
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

    skill_at = len(report)

    if mode is not None:
        # config lives under the root being initialised, which may differ from hq_core.HQ_ROOT
        orig = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = root
        try:
            cfg = hq_core.load_config()
            if not cfg:
                cfg["autostart"] = False
            cfg["mode"] = mode
            hq_core.save_config(cfg)
        finally:
            hq_core.HQ_ROOT = orig
        report.append(f"[ok] mode: {mode}")
    else:
        orig = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = root
        try:
            if hq_core.config_path().is_file():
                report.append(f"[ok] mode: {hq_core.mode()}")
        finally:
            hq_core.HQ_ROOT = orig

    report.insert(skill_at, _skill_report(root, install_skill))

    if autostart is not None:
        if _root_mode(root) != "advanced":
            raise HqError("--autostart needs advanced mode (hq init --mode advanced)")
        import hq_autostart

        orig = hq_core.HQ_ROOT
        hq_core.HQ_ROOT = root
        try:
            cfg = hq_core.load_config()
            cfg["autostart"] = autostart
            hq_core.save_config(cfg)
        finally:
            hq_core.HQ_ROOT = orig
        if autostart:
            report.append(f"[ok] hq serve starts at login: {hq_autostart.enable(root)}")
        else:
            gone = hq_autostart.disable()
            report.append(f"[ok] removed the login item: {gone}" if gone
                          else "[ok] no login item to remove")

    return report
