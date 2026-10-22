import argparse
import json
import os
import sys

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


def cmd_save(args):
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    path = hq_core.save(args.kind, args.title, project_override=args.project, tags=tags)
    print(path)


def cmd_start(args):
    path = hq_core.start(args.slug, project_override=args.project)
    print(path)


def cmd_archive(args):
    path = hq_core.archive(args.slug, project_override=args.project)
    print(path)


def format_table(entries):
    if not entries:
        return "(no entries)"
    header = ("PROJECT", "STATUS", "KIND", "SLUG", "TITLE")
    rows = [header] + [
        (e["project"] or "-", e["status"] or "-", e["kind"], e["slug"], e["title"])
        for e in entries
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(row[i].ljust(widths[i]) for i in range(len(header)))
        for row in rows
    )


def cmd_list(args):
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
        print(hq_registry.finish_goal(args.ref, dropped=args.dropped))


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
    p_save.set_defaults(func=cmd_save)

    p_start = sub.add_parser("start", help="promote a planning task to active")
    p_start.add_argument("slug")
    p_start.add_argument("--project")
    p_start.set_defaults(func=cmd_start)

    p_archive = sub.add_parser("archive", help="archive a planning or active task")
    p_archive.add_argument("slug")
    p_archive.add_argument("--project")
    p_archive.set_defaults(func=cmd_archive)

    p_list = sub.add_parser("list", help="list tasks")
    p_list.add_argument("--project")
    p_list.add_argument("--status", choices=hq_core.STATUSES)
    p_list.add_argument("--json", action="store_true")
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
