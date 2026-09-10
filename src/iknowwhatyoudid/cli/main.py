"""Argument parsing, exit codes, and the stdout/stderr split."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..errors import EXIT_USAGE, IkwydError
from ..store.location import resolve_store_path
from ..sources.state import SqliteSourceStateStore
from . import commands, projects_commands, sources_commands


def _global_options(*, suppress: bool) -> argparse.ArgumentParser:
    """The options every command accepts, before or after the subcommand.

    The leaf copies must use ``SUPPRESS`` defaults. Without it argparse writes each
    subparser's own defaults over whatever the top-level parse produced, so
    ``ikwyd --store X store info`` would silently ignore ``--store`` and operate on the
    default store — writing to the user's real data directory when they asked for a
    different one.
    """
    common = argparse.ArgumentParser(
        add_help=False,
        argument_default=argparse.SUPPRESS if suppress else None,
    )
    common.add_argument("--store", help="use this store instead of the default")
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="emit the machine form",
    )
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="more diagnostics",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _global_options(suppress=True)
    parser = argparse.ArgumentParser(
        prog="ikwyd",
        description="A local tool to get information about how you spend your days.",
        parents=[_global_options(suppress=False)],
    )
    subparsers = parser.add_subparsers(dest="group", required=True)

    store = subparsers.add_parser("store", help="inspect and maintain the store")
    store_actions = store.add_subparsers(dest="action", required=True)
    store_actions.add_parser(
        "info", help="location, version, and what it holds", parents=[common]
    )
    store_actions.add_parser("check", help="full integrity check", parents=[common])
    migrate_parser = store_actions.add_parser(
        "migrate", help="apply pending migrations", parents=[common]
    )
    migrate_parser.add_argument("--dry-run", action="store_true")
    store_actions.add_parser(
        "protection", help="at-rest protection state", parents=[common]
    )

    records = subparsers.add_parser("records", help="read records back")
    record_actions = records.add_subparsers(dest="action", required=True)
    query = record_actions.add_parser(
        "query", help="records by time range and source", parents=[common]
    )
    query.add_argument("--from", dest="since", help="YYYY-MM-DD")
    query.add_argument("--to", dest="until", help="YYYY-MM-DD")
    query.add_argument("--source")
    query.add_argument("--include-withdrawn", action="store_true")

    derived = subparsers.add_parser("derived", help="derived attributions")
    derived_actions = derived.add_subparsers(dest="action", required=True)
    derived_actions.add_parser(
        "discard", help="discard the derived region", parents=[common]
    )

    sources = subparsers.add_parser("sources", help="configured sources")
    source_actions = sources.add_subparsers(dest="action", required=True)
    for verb, helptext in (
        ("list", "every configured source and its status"),
        ("validate", "check the configuration; contacts nothing"),
        ("destinations", "every destination the configuration could contact"),
    ):
        leaf = source_actions.add_parser(verb, help=helptext, parents=[common])
        leaf.add_argument("--config", help="use this configuration file")
    check = source_actions.add_parser(
        "check", help="check one source", parents=[common]
    )
    check.add_argument("name")
    check.add_argument("--config", help="use this configuration file")
    check.add_argument(
        "--live", action="store_true", help="contact the source to confirm it is reachable"
    )
    kinds = source_actions.add_parser(
        "kinds", help="available source kinds and their settings", parents=[common]
    )
    kinds.add_argument("name", nargs="?")
    kinds.add_argument("--config", help="use this configuration file")

    ingest = subparsers.add_parser("ingest", help="read from configured sources")
    ingest.add_argument("--config", help="use this configuration file")
    ingest.add_argument("--projects", help="use this project mapping file")
    ingest.add_argument("--source", help="only this source")
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument(
        "--sweep",
        action="store_true",
        help=(
            "read exhaustively over the window, so records the source no longer "
            "presents can be marked withdrawn. Without this a run is incremental and "
            "nothing is ever withdrawn."
        ),
    )
    for option in common._actions:  # attach the global options to `ingest` too
        if option.dest != "help":
            ingest._add_action(option)

    repos = subparsers.add_parser("repos", help="discovered git repositories")
    repo_actions = repos.add_subparsers(dest="action", required=True)
    for verb, helptext in (
        ("list", "every repository the configuration matches; reads no history"),
        ("check", "discovery diagnostics without ingesting"),
    ):
        leaf = repo_actions.add_parser(verb, help=helptext, parents=[common])
        leaf.add_argument("--config", help="use this configuration file")
        leaf.add_argument("--projects", help="use this project mapping file")

    projects = subparsers.add_parser("projects", help="projects and their mapping")
    project_actions = projects.add_subparsers(dest="action", required=True)
    for verb, helptext in (
        ("list", "every project and how much activity it holds"),
        ("validate", "check the project mapping"),
    ):
        leaf = project_actions.add_parser(verb, help=helptext, parents=[common])
        leaf.add_argument("--config", help="use this configuration file")
        leaf.add_argument("--projects", help="use this project mapping file")
    rederive = project_actions.add_parser(
        "rederive", help="re-apply the mapping to recorded activity", parents=[common]
    )
    rederive.add_argument("--config", help="use this configuration file")
    rederive.add_argument("--projects", help="use this project mapping file")
    rederive.add_argument("--dry-run", action="store_true")

    corrections = subparsers.add_parser("corrections", help="user corrections")
    correction_actions = corrections.add_subparsers(dest="action", required=True)
    export = correction_actions.add_parser(
        "export", help="write corrections as JSON Lines", parents=[common]
    )
    export.add_argument("--out", help="write to this file instead of stdout")
    import_parser = correction_actions.add_parser(
        "import", help="merge corrections in", parents=[common]
    )
    import_parser.add_argument("file")
    import_parser.add_argument("--dry-run", action="store_true")
    list_parser = correction_actions.add_parser(
        "list", help="list corrections", parents=[common]
    )
    list_parser.add_argument("--pending", action="store_true")

    return parser


def _dispatch_sources(args: argparse.Namespace) -> commands.Result:
    """The `sources` group and `ingest` read a configuration, not a store.

    `sources kinds` needs neither, so it never fails on a missing configuration file —
    asking what can be configured must work before anything is configured.
    """
    config = getattr(args, "config", None)
    if args.group == "sources" and args.action == "kinds":
        try:
            session: sources_commands.ConfigSession | None = (
                sources_commands.open_config(config)
            )
        except IkwydError:
            session = None
        return sources_commands.sources_kinds(session, name=args.name)

    session = sources_commands.open_config(config)
    store_session = commands.open_store(args.store, verbose=args.verbose)
    store = SqliteSourceStateStore(store_session.connection)

    match (args.group, getattr(args, "action", None)):
        case ("sources", "list"):
            return sources_commands.sources_list(session, store)
        case ("sources", "validate"):
            return sources_commands.sources_validate(session, store)
        case ("sources", "check"):
            return sources_commands.sources_check(
                session, name=args.name, live=args.live
            )
        case ("sources", "destinations"):
            return sources_commands.sources_destinations(session)
        case ("ingest", _):
            return sources_commands.ingest(
                session,
                store,
                connection=store_session.connection,
                projects=getattr(args, "projects", None),
                config=config,
                only=args.source,
                dry_run=args.dry_run,
                sweep=args.sweep,
            )
    raise IkwydError(f"unknown command: {args.group}")


def _dispatch_projects(args: argparse.Namespace) -> commands.Result:
    """`repos` and `projects` need both the store and the mapping."""
    session = commands.open_store(args.store, verbose=args.verbose)
    config = getattr(args, "config", None)
    projects = getattr(args, "projects", None)

    match (args.group, args.action):
        case ("repos", "list"):
            return projects_commands.repos_list(
                session.connection, config, projects, session.path
            )
        case ("repos", "check"):
            return projects_commands.repos_check(config, projects, session.path)
        case ("projects", "list"):
            return projects_commands.projects_list(session.connection, session.path)
        case ("projects", "validate"):
            return projects_commands.projects_validate(
                session.connection, config, projects, session.path
            )
        case ("projects", "rederive"):
            return projects_commands.projects_rederive(
                session.connection,
                config,
                projects,
                session.path,
                dry_run=args.dry_run,
            )
    raise IkwydError(f"unknown command: {args.group} {args.action}")


def _dispatch(args: argparse.Namespace) -> commands.Result:
    if args.group in {"sources", "ingest"}:
        return _dispatch_sources(args)
    if args.group in {"repos", "projects"}:
        return _dispatch_projects(args)

    session = commands.open_store(args.store, verbose=args.verbose)

    match (args.group, args.action):
        case ("store", "info"):
            return commands.store_info(session)
        case ("store", "check"):
            return commands.store_check(session)
        case ("store", "migrate"):
            return commands.store_migrate(session, dry_run=args.dry_run)
        case ("store", "protection"):
            return commands.store_protection(session)
        case ("records", "query"):
            return commands.records_query(
                session,
                since=args.since,
                until=args.until,
                source=args.source,
                include_withdrawn=args.include_withdrawn,
            )
        case ("derived", "discard"):
            return commands.derived_discard(session)
        case ("corrections", "export"):
            return commands.corrections_export(session, out=args.out)
        case ("corrections", "import"):
            return commands.corrections_import(
                session, path=args.file, dry_run=args.dry_run
            )
        case ("corrections", "list"):
            return commands.corrections_list(session, pending_only=args.pending)

    raise IkwydError(f"unknown command: {args.group} {args.action}")


def _use_utf8_output() -> None:
    """Keep non-ASCII output readable on a legacy console.

    A Windows console still defaults to a legacy code page, where a bullet in a summary
    line comes out as a replacement character. Ask for UTF-8 and fall back silently.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # pragma: no cover
                pass


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    action = getattr(args, "action", None)
    command = f"{args.group}.{action}" if action else args.group

    try:
        result = _dispatch(args)
    except IkwydError as error:
        store_path = resolve_store_path(args.store)
        failure = commands.fail(command, store_path, error)
        commands.emit(failure, as_json=args.json)
        return error.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return EXIT_USAGE

    return commands.emit(result, as_json=args.json)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
