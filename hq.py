import argparse
import json
import os
import sys
from pathlib import Path

import hq_core
import hq_fields
from hq_core import HqError


class ModeError(HqError):
    def __init__(self, what):
        super().__init__(f"'{what}' needs advanced mode")
        self.what = what


def require_advanced(what: str) -> None:
    if hq_core.mode() != "advanced":
        raise ModeError(what)


SAVE_FIELD_FLAGS = (("priority", "priority"), ("goal", "goal"), ("due", "due"),
                    ("do-on", "do_on"), ("est", "est"), ("area", "area"))


def _render_table(header, rows):
    rows = [header] + rows
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(row[i].ljust(widths[i]) for i in range(len(header)))
        for row in rows
    )


def cmd_save(args):
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    fields = {}
    for flag, attr in SAVE_FIELD_FLAGS:
        value = getattr(args, attr)
        if value is not None:
            require_advanced(f"--{flag}")
            fields[flag] = hq_fields.normalize(flag, value)
    advanced = hq_core.mode() == "advanced"
    if fields:
        if args.kind in ("learning", "skill"):
            raise HqError(f"kind={args.kind!r} does not take {', '.join('--' + f for f in fields)}")
        if "goal" in fields:
            import hq_registry

            if hq_registry.get_goal(fields["goal"]) is None:
                raise HqError(f"unknown goal '{fields['goal']}'")
    cwd = Path.cwd()
    path = hq_core.save(args.kind, args.title, project_override=args.project,
                        tags=tags, cwd=cwd, fields=fields or None)
    if advanced and args.project is None and args.kind not in ("learning", "skill"):
        repo = hq_core.detect_repo_root(cwd)
        if repo is not None:
            import hq_registry

            hq_registry.record_repo(path.parent.parent.parent.name, repo)
    print(path)


def cmd_start(args):
    slug = args.slug
    if hq_core.mode() == "advanced":
        import hq_ops

        r = hq_ops.resolve_ref(slug, project=args.project, goals=False, statuses=("planning",))
        slug, project = r.slug, r.project
    else:
        project = args.project
    print(hq_core.start(slug, project_override=project))


def cmd_archive(args):
    slug, project, outcome = args.slug, args.project, None
    if hq_core.mode() == "advanced":
        import hq_ops

        r = hq_ops.resolve_ref(slug, project=args.project, goals=False,
                               statuses=("planning", "active"))
        slug, project = r.slug, r.project
        outcome = "dropped" if args.dropped else "done"
    elif args.dropped:
        require_advanced("--dropped")
    print(hq_core.archive(slug, project_override=project, outcome=outcome))


def format_table(entries):
    if not entries:
        return "(no entries)"
    return _render_table(
        ("PROJECT", "STATUS", "KIND", "SLUG", "TITLE"),
        [(e["project"] or "-", e["status"] or "-", e["kind"], e["slug"], e["title"])
         for e in entries],
    )


def format_advanced_table(records):
    if not records:
        return "(no entries)"
    return _render_table(
        ("PROJECT", "STATUS", "KIND", "P", "AREA", "DUE", "SLUG", "TITLE"),
        [(r["project"] or "-", "blocked" if r["blocked"] else (r["status"] or "-"),
          r["kind"] or "-", r["priority"], r["area"], r["due"] or "-", r["slug"], r["title"])
         for r in records],
    )


def cmd_list(args):
    if hq_core.mode() == "advanced":
        import hq_ops

        records = hq_ops.filter_records(
            hq_ops.entry_records(project=args.project, status=args.status),
            area=args.area, goal=args.goal, priority=args.priority,
            due_before=args.due_before)
        if args.json:
            for r in records:
                print(json.dumps({**r, "path": str(r["path"])}))
            return
        print(format_advanced_table(records))
        return
    for flag, attr in (("area", "area"), ("goal", "goal"), ("priority", "priority"),
                       ("due-before", "due_before")):
        if getattr(args, attr) is not None:
            require_advanced(f"--{flag}")
    entries = hq_core.list_entries(project=args.project, status=args.status)
    if args.json:
        for e in entries:
            print(json.dumps({**e, "path": str(e["path"])}))
        return
    print(format_table(entries))


def cmd_find(args):
    results = hq_core.search_entries(args.query)
    if args.json:
        for r in results:
            print(json.dumps({**r, "path": str(r["path"])}))
        return
    if not results:
        print("no matches")
        return
    for r in results:
        project = r["project"] or "-"
        status = r["status"] or "-"
        print(f"{project}/{status}/{r['slug']}  ({r['title']})  {r['path']}")


def cmd_log(args):
    entries = hq_core.read_log(project=args.project, since=args.since)
    for entry in entries:
        print(json.dumps(entry))


def cmd_init(args):
    import hq_init

    print("\n".join(hq_init.init(args.root, args.install_skill, mode=args.mode)))


def cmd_serve(args):
    import hq_serve

    if not hq_core.HQ_ROOT.is_dir():
        raise HqError(f"{hq_core.HQ_ROOT} does not exist. Run `hq init` first.")
    hq_serve.serve(args.port, open_browser=not args.no_open)


def cmd_show(args):
    require_advanced("show")


def format_goal_table(goals):
    if not goals:
        return "(no goals)"
    header = ("P", "AREA", "STATUS", "TARGET", "SLUG", "TITLE")
    rows = [header] + [
        (g["priority"], g["area"], g["status"], g["target"] or "-", g["slug"], g["title"])
        for g in goals
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(row[i].ljust(widths[i]) for i in range(len(header)))
        for row in rows
    )


def cmd_goal(args):
    require_advanced("goal")
    import hq_registry

    if args.goal_cmd == "new":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        print(hq_registry.create_goal(args.title, area=args.area, target=args.target,
                                      priority=args.priority, tags=tags))
    elif args.goal_cmd == "list":
        goals = hq_registry.list_goals(status=args.status, area=args.area)
        if args.json:
            for g in goals:
                print(json.dumps({**g, "path": str(g["path"])}))
            return
        print(format_goal_table(goals))
    else:
        import hq_ops

        r = hq_ops.resolve_ref(args.ref, statuses=())
        print(hq_registry.finish_goal(r.slug, dropped=args.dropped))


def cmd_project(args):
    require_advanced("project")
    import hq_registry

    if args.field != "area":
        raise HqError(f"cannot set {args.field!r} on a project (only: area)")
    hq_registry.set_project_area(args.project, args.value)
    print(f"{args.project}: area = {hq_fields.parse_area(args.value)}")


def build_parser():
    parser = argparse.ArgumentParser(prog="hq")
    parser.add_argument("--by", choices=hq_core.ACTORS, help="who is acting (advanced mode; default $HQ_ACTOR or user)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="first-time setup: create the data folder and check PATH/HQ_ROOT")
    p_init.add_argument("--root", help="where the archive lives (defaults to $HQ_ROOT)")
    p_init.add_argument("--install-skill", action="store_true", help="copy the Claude Code skill to ~/.claude/skills/hq")
    p_init.add_argument("--mode", choices=hq_core.MODES, help="switch between classic and advanced mode")
    p_init.set_defaults(func=cmd_init)

    p_save = sub.add_parser("save", help="save a new task/bug/presentation/learning")
    p_save.add_argument("kind", choices=hq_core.KINDS)
    p_save.add_argument("title")
    p_save.add_argument("--project")
    p_save.add_argument("--tags", default="")
    p_save.add_argument("--priority")
    p_save.add_argument("--goal")
    p_save.add_argument("--due")
    p_save.add_argument("--do-on", dest="do_on")
    p_save.add_argument("--est")
    p_save.add_argument("--area")
    p_save.set_defaults(func=cmd_save)

    p_start = sub.add_parser("start", help="promote a planning task to active")
    p_start.add_argument("slug")
    p_start.add_argument("--project")
    p_start.set_defaults(func=cmd_start)

    p_archive = sub.add_parser("archive", help="archive a planning or active task")
    p_archive.add_argument("slug")
    p_archive.add_argument("--project")
    p_archive.add_argument("--dropped", action="store_true")
    p_archive.set_defaults(func=cmd_archive)

    p_list = sub.add_parser("list", help="list tasks")
    p_list.add_argument("--project")
    p_list.add_argument("--status", choices=hq_core.STATUSES)
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--area")
    p_list.add_argument("--goal")
    p_list.add_argument("--priority")
    p_list.add_argument("--due-before", dest="due_before")
    p_list.set_defaults(func=cmd_list)

    p_find = sub.add_parser("find", help="search tasks and learnings")
    p_find.add_argument("query")
    p_find.add_argument("--json", action="store_true")
    p_find.set_defaults(func=cmd_find)

    p_serve = sub.add_parser("serve", help="browse the archive in a browser")
    p_serve.add_argument("--port", type=int, default=8787)
    p_serve.add_argument("--no-open", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_log = sub.add_parser("log", help="show the action log")
    p_log.add_argument("--project")
    p_log.add_argument("--since", help="ISO date/time lower bound, e.g. 2026-08-01")
    p_log.set_defaults(func=cmd_log)

    p_show = sub.add_parser("show", help="show one entry (advanced mode)")
    p_show.add_argument("slug")
    p_show.set_defaults(func=cmd_show)

    p_goal = sub.add_parser("goal", help="manage goals (advanced mode)")
    gsub = p_goal.add_subparsers(dest="goal_cmd", required=True)
    g_new = gsub.add_parser("new", help="create a goal")
    g_new.add_argument("title")
    g_new.add_argument("--area", default="work")
    g_new.add_argument("--target")
    g_new.add_argument("--priority")
    g_new.add_argument("--tags", default="")
    g_list = gsub.add_parser("list", help="list goals")
    g_list.add_argument("--status", choices=("active", "done", "dropped"))
    g_list.add_argument("--area")
    g_list.add_argument("--json", action="store_true")
    g_done = gsub.add_parser("done", help="mark a goal done")
    g_done.add_argument("ref")
    g_done.add_argument("--dropped", action="store_true")
    p_goal.set_defaults(func=cmd_goal)

    p_project = sub.add_parser("project", help="project settings (advanced mode)")
    psub = p_project.add_subparsers(dest="project_cmd", required=True)
    p_set = psub.add_parser("set", help="set a project field")
    p_set.add_argument("project")
    p_set.add_argument("field")
    p_set.add_argument("value")
    p_project.set_defaults(func=cmd_project)

    return parser


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.command in ("save", "start", "archive", "goal", "project") and "HQ_ROOT" not in os.environ:
        print(f"warning: HQ_ROOT is not set, writing to {hq_core.HQ_ROOT}. Run `hq init`.", file=sys.stderr)
    try:
        if hq_core.mode() == "advanced":
            actor = args.by or os.environ.get("HQ_ACTOR") or "user"
            if actor not in hq_core.ACTORS:
                raise HqError(f"invalid HQ_ACTOR {actor!r}; choose from {', '.join(hq_core.ACTORS)}")
            hq_core.ACTOR = actor
        args.func(args)
    except ModeError as e:
        print(f"hq: '{e.what}' needs advanced mode — run: hq init --mode advanced", file=sys.stderr)
        return 1
    except HqError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
