"""`hq serve`: browse the archive in a browser. A status board of every entry,
rendered Markdown, and everything else (HTML explainers, images) served as-is
from HQ_ROOT. Read-only."""
import html
import json
import re
import urllib.parse
import webbrowser
from functools import partial
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import hq_core

MARKED_JS = Path(__file__).with_name("marked.min.js")  # vendored marked v15.0.12

CSS = """
:root{--bg:#f4f5f8;--card:#fff;--text:#1b1f27;--muted:#697386;--line:#e2e5ec;--accent:#5b5bd6;
--shadow:0 1px 2px #0000000f,0 6px 18px #0000000a;--task:#3b82f6;--bug:#ef4444;--presentation:#a855f7;
--learning:#10b981;--skill:#f59e0b;--other:#64748b;color-scheme:light dark}
@media(prefers-color-scheme:dark){:root{--bg:#0e1015;--card:#171a22;--text:#e7e9ef;--muted:#8d95a6;--line:#272c38;
--shadow:0 1px 2px #0007,0 6px 18px #0005}}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:inherit;text-decoration:none}
.wrap{max-width:1240px;margin:0 auto;padding:1.5rem 1.25rem 4rem}
header{display:flex;flex-wrap:wrap;gap:1rem 1.5rem;align-items:center;margin-bottom:1.75rem}
h1{margin:0;font-size:1.7rem;letter-spacing:-.03em}h1 b{color:var(--accent)}
.stats{display:flex;gap:.5rem;flex-wrap:wrap}
.stat{background:var(--card);border:1px solid var(--line);border-radius:99px;padding:.15rem .75rem;font-size:.8rem;color:var(--muted)}
.stat b{color:var(--text)}
.searchbox{margin-left:auto;display:flex;align-items:center;gap:.6rem;flex:1 1 360px;max-width:560px}
#q{flex:1;padding:.55rem .9rem;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--text);font:inherit;outline:none}
#q:focus{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 25%,transparent)}
#count{font-size:.8rem;color:var(--muted);min-width:4.5rem}
.project{margin-bottom:2.25rem}
.project>h2{font-size:1.1rem;margin:0 0 .8rem;display:flex;align-items:center;gap:.5rem}
.project>h2::before{content:"";width:.6rem;height:.6rem;border-radius:50%;background:var(--accent)}
.board{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;align-items:start}
@media(max-width:860px){.board{grid-template-columns:1fr}}
.col{background:color-mix(in srgb,var(--card) 45%,transparent);border:1px solid var(--line);border-radius:14px;padding:.8rem}
.col>h3,.col>summary{margin:0 0 .7rem;font-size:.72rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
display:flex;align-items:center;gap:.5rem;cursor:default;list-style:none}
.col>summary{cursor:pointer;margin:0}.col[open]>summary{margin-bottom:.7rem}.col>summary::-webkit-details-marker{display:none}
.col>summary::after{content:"+";margin-left:auto}.col[open]>summary::after{content:"\\2212"}
.dot{width:.55rem;height:.55rem;border-radius:50%}
.planning .dot{background:#f59e0b}.active .dot{background:#22c55e}.archive .dot{background:#94a3b8}
.n{background:var(--line);color:var(--text);border-radius:99px;padding:0 .5rem;font-size:.72rem}
.empty{color:var(--muted);font-size:.85rem;padding:.2rem .3rem}
.card{--kind:var(--other);display:block;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--kind);
border-radius:10px;padding:.6rem .75rem .65rem;margin-bottom:.6rem;box-shadow:var(--shadow);transition:transform .12s,border-color .12s}
.card:last-child{margin-bottom:0}.card:hover{transform:translateY(-2px);border-color:var(--kind)}
.k-task{--kind:var(--task)}.k-bug{--kind:var(--bug)}.k-presentation{--kind:var(--presentation)}
.k-learning{--kind:var(--learning)}.k-skill{--kind:var(--skill)}
.badge{font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--kind)}
.title{font-weight:600;line-height:1.3;margin:.1rem 0 .2rem;overflow-wrap:anywhere}
.meta{font-size:.74rem;color:var(--muted)}
.chip{display:inline-block;background:var(--bg);border:1px solid var(--line);border-radius:99px;padding:0 .5rem;font-size:.72rem;margin:.2rem .25rem 0 0}
.group{margin-bottom:1.25rem}.group>h3{font-size:.72rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:0 0 .55rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:.6rem}
.tile{display:flex;align-items:center;gap:.65rem;background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:.55rem .75rem;box-shadow:var(--shadow);transition:transform .12s,border-color .12s;min-width:0}
.tile:hover{transform:translateY(-2px);border-color:var(--accent)}
.tile span:last-child{overflow-wrap:anywhere;line-height:1.3;font-size:.9rem}.ico{font-size:1.25rem}
.crumb{font-size:.85rem;color:var(--muted);margin:0 auto 1rem;max-width:860px}.crumb a{color:var(--accent)}
.doc{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:1.5rem 2rem 2rem;max-width:860px;margin:0 auto}
.doc .chips{margin-bottom:.5rem}
.md{line-height:1.7}.md h1{font-size:1.9rem;letter-spacing:-.02em;margin:.3rem 0 1rem}.md h2{margin:2rem 0 .6rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}
.md a{color:var(--accent)}.md img{max-width:100%}
.md pre{overflow:auto;padding:.9rem 1rem;background:var(--bg);border:1px solid var(--line);border-radius:10px}
.md code{background:var(--bg);padding:.12em .35em;border-radius:5px;font-size:.88em}.md pre code{padding:0;background:none}
.md table{border-collapse:collapse;margin:1rem 0}.md th,.md td{border:1px solid var(--line);padding:.4rem .75rem;text-align:left}
.md th{background:var(--bg)}.md blockquote{margin:1rem 0;padding:.1rem 1rem;border-left:4px solid var(--accent);color:var(--muted)}
"""

PAGE = """<!doctype html><meta charset="utf-8"><title>__TITLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>__CSS__</style>
<div class="wrap">__BODY__</div>__SCRIPT__"""

FILTER_JS = """<script>
const q=document.getElementById("q"),items=[...document.querySelectorAll(".item")],count=document.getElementById("count");
q.oninput=()=>{const s=q.value.trim().toLowerCase();let n=0;
items.forEach(i=>{const m=!s||i.dataset.t.includes(s);i.hidden=!m;if(m)n++});
document.querySelectorAll("details.col").forEach(d=>{if(s&&d.querySelector(".item:not([hidden])"))d.open=true});
document.querySelectorAll(".project,.group").forEach(g=>g.hidden=!g.querySelector(".item:not([hidden])"));
count.textContent=s?n+(n==1?" match":" matches"):""};
addEventListener("keydown",e=>{if(e.key=="/"&&document.activeElement!=q){e.preventDefault();q.focus()}});
</script>"""


def render(title: str, body: str, script: str = "") -> str:
    return PAGE.replace("__TITLE__", html.escape(title)).replace("__CSS__", CSS).replace("__BODY__", body).replace("__SCRIPT__", script)


def _entry_href(e) -> str:
    folder = e["path"].parent
    rel = folder.relative_to(hq_core.HQ_ROOT).as_posix()
    name = "" if (folder / "index.html").is_file() else "README.md"
    return "/" + urllib.parse.quote(f"{rel}/{name}")


def _as_list(tags) -> list[str]:
    return [str(t) for t in tags] if isinstance(tags, list) else ([str(tags)] if tags else [])


def _chips(values) -> str:
    return "".join(f'<span class="chip">{html.escape(v)}</span>' for v in values)


def _card(e) -> str:
    tags = _as_list(e["tags"])
    kind = e["kind"] or "entry"
    text = " ".join([e["title"], e["slug"], kind, *tags]).lower()
    kind_class = re.sub(r"[^a-z0-9]+", "-", kind.lower())
    return (
        f'<a class="card item k-{kind_class}" data-t="{html.escape(text)}" href="{_entry_href(e)}">'
        f'<div class="badge">{html.escape(kind)}</div><div class="title">{html.escape(e["title"])}</div>'
        f'<div class="meta">{html.escape(str(e["created"]))}</div>{_chips(tags)}</a>'
    )


def _column(status: str, rows: list) -> str:
    head = f'<span class="dot"></span>{status}<span class="n">{len(rows)}</span>'
    cards = "".join(_card(e) for e in rows) or '<div class="empty">nothing here</div>'
    if status == "archive":  # collapsed: the archive is the biggest column and the least urgent
        return f'<details class="col archive"><summary>{head}</summary>{cards}</details>'
    return f'<div class="col {status}"><h3>{head}</h3>{cards}</div>'


def _icon(p: Path) -> str:
    if p.is_dir():
        return "\U0001F310" if (p / "index.html").is_file() else "\U0001F4C1"
    return {".md": "\U0001F4DD", ".html": "\U0001F4C4"}.get(p.suffix, "\U0001F4CE")


def render_index() -> str:
    entries = hq_core.list_entries()
    stats = "".join(
        f'<span class="stat"><b>{sum(e["status"] == s for e in entries)}</b> {s}</span>' for s in hq_core.STATUSES
    )
    parts = [
        '<header><h1><b>hq</b></h1>'
        f'<div class="stats">{stats}</div>'
        '<div class="searchbox"><input id="q" placeholder="Search entries and artifacts  ( / )" autofocus>'
        '<span id="count"></span></div></header>'
    ]
    for project in sorted({e["project"] for e in entries}):
        cols = "".join(
            _column(s, [e for e in entries if e["project"] == project and e["status"] == s])
            for s in hq_core.STATUSES
        )
        parts.append(f'<section class="project"><h2>{html.escape(project)}</h2><div class="board">{cols}</div></section>')
    groups = {name: paths for name, paths in _other_artifacts().items() if paths}
    if groups:
        parts.append('<section class="project"><h2>Other artifacts</h2>')
        for name, paths in groups.items():
            tiles = "".join(
                f'<a class="tile item" data-t="{html.escape((name + " " + p.name).lower())}" href="{_href(p)}">'
                f'<span class="ico">{_icon(p)}</span><span>{html.escape(p.name)}</span></a>'
                for p in paths
            )
            parts.append(f'<div class="group"><h3>{html.escape(name)}</h3><div class="tiles">{tiles}</div></div>')
        parts.append("</section>")
    return render("hq", "".join(parts), FILTER_JS)


def render_markdown(f: Path) -> str:
    meta, body = hq_core.frontmatter_parse(f.read_text(encoding="utf-8"))
    title = hq_core.extract_title(body) or f.stem
    rel = f.relative_to(hq_core.HQ_ROOT.resolve()).parent.as_posix().removeprefix(".")
    facts = [str(meta[k]) for k in ("kind", "status", "created") if meta.get(k)] + _as_list(meta.get("tags"))
    data = json.dumps(body).replace("</", "<\\/")
    page = (
        f'<div class="crumb"><a href="/">hq</a> / {html.escape(rel.replace("/", " / "))}</div>'
        f'<article class="doc"><div class="chips">{_chips(facts)}</div><div class="md" id="md"></div></article>'
    )
    script = f'<script src="/_marked.js"></script><script>document.getElementById("md").innerHTML=marked.parse({data});</script>'
    return render(title, page, script)


def _href(p: Path) -> str:
    rel = p.relative_to(hq_core.HQ_ROOT).as_posix()
    return "/" + urllib.parse.quote(rel) + ("/" if p.is_dir() else "")


def _visible(folder: Path):
    return sorted(p for p in folder.iterdir() if not p.name.startswith("."))


def _other_artifacts() -> dict[str, list[Path]]:
    """Everything the entry board doesn't cover: other top-level folders
    (learnings, presentations, ...), entry folders without a README, loose files."""
    root = hq_core.HQ_ROOT
    groups: dict[str, list[Path]] = {}
    for top in _visible(root):
        if top.name != "projects":
            if top.is_dir():
                groups[top.name + "/"] = _visible(top)
            else:
                groups.setdefault("(root)", []).append(top)
            continue
        for proj in _visible(top):
            statuses = [proj / s for s in hq_core.STATUSES if (proj / s).is_dir()] if proj.is_dir() else []
            if not statuses:  # a loose file, or a project folder without the status layout
                groups.setdefault("projects/", []).append(proj)
            for status_dir in statuses:
                missing = [d for d in _visible(status_dir) if not (d / "README.md").is_file()]
                if missing:
                    groups[f"{proj.name} / {status_dir.name} (no README)"] = missing
    return groups


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/":
            return self._send(render_index())
        if path == "/_marked.js":
            return self._send(MARKED_JS.read_text(encoding="utf-8"), "text/javascript")
        if path.endswith(".md"):
            f = (hq_core.HQ_ROOT / path.lstrip("/")).resolve()
            if f.is_relative_to(hq_core.HQ_ROOT.resolve()) and f.is_file():
                return self._send(render_markdown(f))
        super().do_GET()

    def _send(self, page: str, ctype: str = "text/html"):
        data = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def serve(port: int = 8787, open_browser: bool = True) -> None:
    handler = Handler
    if hq_core.mode() == "advanced":  # the v2 app; classic serves exactly the v1 board
        import hq_web

        handler = hq_web.make_handler()
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(handler, directory=str(hq_core.HQ_ROOT)))
    url = f"http://127.0.0.1:{port}/"
    print(f"serving {hq_core.HQ_ROOT} at {url} (ctrl-c to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
