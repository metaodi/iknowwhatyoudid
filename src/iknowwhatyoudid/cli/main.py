"""Argument parsing, exit codes, and the stdout/stderr split."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..errors import EXIT_USAGE, IkwydError
from ..store.location import resolve_store_path
from . import commands


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


def _dispatch(args: argparse.Namespace) -> commands.Result:
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
    command = f"{args.group}.{args.action}"

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
