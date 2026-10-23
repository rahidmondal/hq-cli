"""Terminal tables for advanced-mode views (today, free, read list, inbox,
week): one table, optional section divider rows, columns truncated to the
terminal width, color only on a TTY with NO_COLOR unset."""
import os
import shutil
import sys

_RESET = "\033[0m"
_STYLES = {"P1": "\033[31m", "P2": "\033[33m", "dim": "\033[2m", "bold": "\033[1m"}
_vt_ready = None


def _enable_vt() -> bool:
    """Windows 10+ consoles need VT processing switched on for ANSI codes."""
    global _vt_ready
    if _vt_ready is None:
        _vt_ready = True
        if sys.platform == "win32":
            try:
                import ctypes

                kernel = ctypes.windll.kernel32
                handle = kernel.GetStdHandle(-11)
                mode = ctypes.c_uint32()
                if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                    _vt_ready = False
                elif not kernel.SetConsoleMode(handle, mode.value | 0x0004):
                    _vt_ready = False
            except (AttributeError, OSError):
                _vt_ready = False
    return _vt_ready


def color_on(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or not hasattr(stream, "isatty"):
        return False
    try:
        if not stream.isatty():
            return False
    except ValueError:
        return False
    return _enable_vt()


def _encodable(text: str, stream=None) -> bool:
    enc = getattr(stream or sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(enc)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def width() -> int:
    return max(40, shutil.get_terminal_size((100, 24)).columns)


def _cut(text: str, n: int, ell: str) -> str:
    if len(text) <= n:
        return text
    return text[: max(0, n - len(ell))] + ell if n > len(ell) else text[:n]


def table(header: tuple, rows: list, flex: int | None = None, total: int | None = None,
          color: bool | None = None, styles: dict | None = None) -> str:
    """rows: tuples of cells, or a str for a section divider row.
    flex: index (or indexes) of the columns that shrink to fit the width,
    widest first (default: the last column).
    styles: {column index: fn(cell) -> style name or None}."""
    color = color_on() if color is None else color
    total = total or width()
    line = "─" if _encodable("─…") else "-"
    ell = "…" if line == "─" else "..."
    cells = [r for r in rows if not isinstance(r, str)]
    n = len(header)
    widths = [max(len(str(r[i])) for r in [header] + cells) for i in range(n)]
    flex = (n - 1,) if flex is None else (flex,) if isinstance(flex, int) else tuple(flex)
    over = sum(widths) + 2 * (n - 1) - total
    while over > 0:  # take a column at a time from the widest shrinkable one
        i = max(flex, key=lambda c: widths[c])
        if widths[i] <= 12:
            break
        widths[i] -= 1
        over -= 1

    def paint(text: str, style: str | None) -> str:
        return f"{_STYLES[style]}{text}{_RESET}" if color and style else text

    def fmt(row, head=False) -> str:
        out = []
        for i in range(n):
            text = _cut(str(row[i]), widths[i], ell)
            pad = text.ljust(widths[i]) if i < n - 1 else text
            style = "bold" if head else ((styles or {}).get(i, lambda _c: None)(row[i]))
            out.append(paint(pad, style))
        return "  ".join(out).rstrip()

    full = min(total, sum(widths) + 2 * (n - 1))
    out = [fmt(header, head=True)]
    for r in rows:
        if isinstance(r, str):
            label = f"{line}{line} {r} "
            out.append(paint(label + line * max(0, full - len(label)), "dim"))
        else:
            out.append(fmt(r))
    return "\n".join(out)


def priority_style(cell) -> str | None:
    return cell if cell in ("P1", "P2") else None
