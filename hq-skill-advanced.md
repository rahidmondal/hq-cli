---
name: hq
description: Run the user's day from hq, their local task, goal, reading and calendar system. Use when the user says "/hq", asks what's on today, wants to add or update a task, says they're blocked, has a few free minutes, saves a link, captures an idea, asks about goals, wants to wrap up the day, or asks what they did last week.
---

# hq (advanced mode)

`hq` is a CLI that keeps the user's tasks, goals, reading list, inbox,
calendar and daily summaries as plain Markdown files under `$HQ_ROOT`. This
skill tells you the commands; the CLI does all validation. It never calls an
AI and works without you: you make it faster and add context it can't reach.

## Rules

- **Always pass `--by agent`** right after `hq` (or set `HQ_ACTOR=agent`), so
  the log shows which changes were yours: `hq --by agent start <ref>`.
- Prefer `--json` for anything you read. Every read command has it.
- A `<ref>` is a slug or any unique part of one. If hq says the ref is
  ambiguous, use a longer one or `--project`; `goal/<slug>` picks a goal.
- Never invent an artifact's `--about` or `--why`. Ask the user.
- Don't run `hq serve` unless asked (it blocks). If hq warns that `HQ_ROOT`
  is not set, stop and tell the user rather than writing anyway.
- Keep answers short. Group by area (work, personal), then by goal or project.

## What the user says → what to run

| The user says | Run |
|---|---|
| "what's on today?" | `hq today --json` (add `--area work` or `--area personal`) |
| "add a task …" | `hq --by agent save task "<title>" [--project X] [--priority P1-P4] [--due D] [--do-on D] [--est 30m] [--goal G] [--area A]` |
| "I'm working on X" | `hq --by agent show <ref>`, then `hq --by agent start <ref>` |
| (after a meaningful step) | `hq --by agent note <ref> "<what happened>"` |
| "X is done" / "drop X" | `hq --by agent archive <ref>` / `hq --by agent archive <ref> --dropped` |
| "I'm blocked on X because …" | `hq --by agent block <ref> "<reason>"`; later `hq --by agent unblock <ref>` |
| "put X back" / "pause X" | `hq --by agent unstart <ref> --reason "<why>"` |
| "make X urgent", "due Friday" | `hq --by agent set <ref> priority P1`, `hq --by agent set <ref> due 2026-10-30` (`none` clears) |
| "I've got 20 minutes" | `hq free 20m --json` (no time = until the next event) |
| "save this link" | `hq --by agent read <url> [--note "why"] [--priority P2]` |
| "what should I read?" | `hq read list --json`; mark with `hq --by agent read done <ref>` or `read drop <ref>` |
| "note this idea" / "remind me …" | `hq --by agent dump "<text>"`; sort later with `hq --by agent triage <ref> task\|goal\|reading\|drop [--project X]` |
| "new goal …" | `hq --by agent goal new "<title>" --area work [--target D] [--priority P]`; `hq goal list --json`; `hq --by agent goal done <ref>` |
| "add a meeting …" | `hq --by agent cal add "<title>" "<YYYY-MM-DD HH:MM>" <end or 30m> [--repeat daily\|weekdays\|weekly]`; `hq cal list --json` |
| "save this file with the task" | `hq --by agent artifact add <ref> <file> --about "<what>" --why "<why>"` (ask for both) |
| "wrap up my day" | the day-end recipe below |
| "what did I do this week / last week?" | `hq week [DATE] --json`, `hq month [DATE] --json`, `hq day <DATE> --json` |
| "is everything ok?" | `hq check` |

Dates accept `YYYY-MM-DD`, `today`, `tomorrow`, `+3d`, `+2w`. Estimates
accept `20m`, `1h`, `1h30m`.

## Working on an entry

1. `hq --by agent show <ref> --json` before you start: read its fields,
   body, artifacts and recent log.
2. `hq --by agent start <ref>` when you begin.
3. `hq --by agent note <ref> "<one line>"` after each meaningful step
   (decision made, PR opened, test passing).
4. `hq --by agent archive <ref>` when it's done.

## Day end

1. `hq day --json` gives the facts: every log line today grouped by area →
   goal/project → entry, what was started, finished, dropped and blocked,
   links read, inbox captures, git commits in the user's repos, and events.
2. Add what only you can reach: the threads and sessions you worked in today.
3. Write a short summary (a few lines, grouped by area then project: what
   moved, what's blocked, what's next) to a temporary file.
4. `hq --by agent day end --summary-file <file>`. hq keeps the facts below
   your prose and never touches the user's own "My notes" section. If the
   user gives you a line of their own, add it with `--summary "<line>"`.
