---
name: hq
description: Save, list, find, and manage project tasks, bugs, presentations, and learnings in the hq archive. Use when the user says "/hq", asks to save a task/plan/idea, wants to find past notes, or asks what's active/planned.
---

# hq

`hq` is a CLI (not this skill) that manages a plain-Markdown task/learning
archive at `$HQ_ROOT`, organized by project with a planning → active →
archive lifecycle. This skill just tells you the commands — all validation
and enforcement lives in the CLI itself.

## Commands

- `hq save <kind> "<title>" [--project X] [--tags a,b]` — capture a new
  idea/task. `kind` is one of `task`, `bug`, `presentation`, `learning`,
  `skill`. Defaults to `planning` status. Project auto-detects from the
  current repo unless `--project` is given. `kind=learning`/`kind=skill`
  ignore project entirely.
- `hq start <slug>` — promote a planning task to active.
- `hq archive <slug>` — archive a planning or active task (done or
  abandoned).
- `hq list [--project X] [--status planning|active|archive] [--json]` — see
  what exists.
- `hq find <query> [--json]` — search titles/tags/body across everything,
  including learnings and skills.
- `hq log [--project X] [--since DATE]` — see the action history.
- `hq serve [--port N] [--no-open]` — start a local browser view of the
  archive for the human (blocks until stopped; do not run it unless asked).
- `hq init [--root PATH]` — first-time setup/check; if `hq` warns that
  `HQ_ROOT` is not set, stop and tell the user rather than writing anyway.

`kind=skill` creates `$HQ_ROOT/skills/<slug>/SKILL.md` (Claude-Code-shaped:
`name`/`description` frontmatter, no hq-specific fields — clean enough to
copy or symlink straight into `~/.claude/skills/<slug>/` to install it) plus
a `README.md` alongside it for hq's own notes about the skill.

Run `hq --help` or any subcommand with `--help` for exact flags if unsure.
