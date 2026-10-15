# hq-cli

This is the `hq` task/learning archive CLI. Its own design doc is managed by
the tool itself, not kept as a file in this repo — run `hq find hq-cli` to
find it. See `README.md` for setup and the data layout.

Commands: `hq init [--root PATH] [--install-skill]`,
`hq save <kind> "<title>" [--project X] [--tags a,b]`, `hq start <slug>`,
`hq archive <slug>`, `hq list [--project X] [--status S] [--json]`, `hq find <query> [--json]`,
`hq log [--project X] [--since DATE]`, `hq serve [--port N] [--no-open]`.
Kinds: `task, bug, presentation, learning, skill`.
Statuses: `planning, active, archive`.

Requires `HQ_ROOT` set to wherever your data directory lives, and this
directory on `PATH`. `hq init` checks both. Stdlib-only: do not add dependencies.
