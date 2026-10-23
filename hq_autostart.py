"""Optional login item for `hq serve` (off by default): `hq init --autostart`
adds it and `--no-autostart` removes it. Windows: a .cmd in the Startup
folder. macOS: a LaunchAgent plist. Linux: an XDG autostart .desktop file.
Each starts `hq serve --no-open` with this HQ_ROOT, then opens the Today page."""
import os
import plistlib
import shlex
import sys
from pathlib import Path

HQ_PY = Path(__file__).resolve().with_name("hq.py")
PORT = 8787
LABEL = "com.hq.serve"


def target() -> Path:
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "hq-serve.cmd"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "autostart" / "hq-serve.desktop"


def _python() -> str:
    exe = Path(sys.executable)
    if sys.platform == "win32":
        quiet = exe.with_name("pythonw.exe")  # no console window at login
        if quiet.is_file():
            return str(quiet)
    return str(exe)


def _shell_line(root: Path) -> str:
    url = f"http://127.0.0.1:{PORT}/"
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    return (f"HQ_ROOT={shlex.quote(str(root))} {shlex.quote(_python())} {shlex.quote(str(HQ_PY))} "
            f"serve --no-open --port {PORT} & sleep 2; {opener} {url}; wait")


def content(root: Path) -> bytes:
    if sys.platform == "win32":
        url = f"http://127.0.0.1:{PORT}/"
        lines = ["@echo off", f'set "HQ_ROOT={root}"',
                 f'start "" "{_python()}" "{HQ_PY}" serve --no-open --port {PORT}',
                 "timeout /t 2 /nobreak >nul", f'start "" "{url}"', ""]
        return "\r\n".join(lines).encode("utf-8")
    if sys.platform == "darwin":
        return plistlib.dumps({"Label": LABEL, "RunAtLoad": True,
                               "ProgramArguments": ["/bin/sh", "-c", _shell_line(root)]})
    line = _shell_line(root).replace("\\", "\\\\").replace('"', '\\"')
    return ("[Desktop Entry]\nType=Application\nName=hq\nComment=Start hq serve at login\n"
            f'Exec=/bin/sh -c "{line}"\nX-GNOME-Autostart-enabled=true\n').encode("utf-8")


def enable(root: Path) -> Path:
    path = target()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content(root))
    return path


def disable() -> Path | None:
    path = target()
    if path.is_file():
        path.unlink()
        return path
    return None
