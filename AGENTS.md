# hq-cli

This is the `hq` task/learning archive CLI. Its own design doc is managed by
the tool itself, not kept as a file in this repo — run `hq find hq-cli` to
find it. See `README.md` for setup and the data layout.

Commands: `hq init [--root PATH] [--install-skill]`,
`hq save <kind> "<title>" [--project X] [--tags a,b]`, `hq start <slug>`,
`hq archive <slug>`, `hq list [--project X] [--status S] [--json]`, `hq find <query> [--json]`,
`hq log [--project X] [--since DATE]`, `hq serve [--port N] [--no-open]`.
Advanced mode (`hq init --mode advanced`) adds `save --priority/--goal/--due/--do-on/--est/--area`,
`list --area/--goal/--priority/--due-before`, `archive --dropped`, `show`, `set`, `note`, `block`,
`unblock`, `unstart`, `goal new|list|done`, `project set <p> area <a>`, `check`, `today`, `free`,
`read`, `dump`, `inbox`, `triage`, `day [end]`, `week`, `month`, `cal add|list|set|rm|export`, `artifact add|list`,
`init --autostart`, and top-level
`--by user|agent|web` (or `HQ_ACTOR`). Daily-loop commands live in `hq_views.py` (items: `hq_items.py`, days: `hq_day.py`).
In advanced mode `hq serve` serves the v2 app (`hq_web.py`, `web/`, Today logic
in `hq_today.py`); browser writes run CLI commands in-process as `--by web`. Classic mode (the default, no `.hq/config.json`) must stay
byte-for-byte v1; `tests/test_classic_regression.py` guards that.
Kinds: `task, bug, presentation, learning, skill`.
Statuses: `planning, active, archive`.

Requires `HQ_ROOT` set to wherever your data directory lives, and this
directory on `PATH`. `hq init` checks both. Stdlib-only: do not add dependencies.
