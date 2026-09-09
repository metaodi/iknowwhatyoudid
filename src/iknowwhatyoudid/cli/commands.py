"""Command implementations. Each returns a payload and an exit code; printing is `main`'s job."""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..corrections import portable
from ..corrections import repository as corrections_repo
from ..derived import repository as derived_repo
from ..errors import IkwydError, UsageError
from ..obs import logging as obs
from ..protection import encryption, permissions
from ..records import repository as records_repo
from ..store import connection as conn
from ..store import integrity, migrate, stats
from ..store.location import log_path_for, resolve_store_path
from .render import envelope, size, table, when


@dataclass(frozen=True, slots=True)
class Result:
    command: str
    ok: bool
    store_path: Path
    data: Mapping[str, Any]
    human: str

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def render(self, as_json: bool) -> str:
        if as_json:
            return envelope(
                self.command, ok=self.ok, store_path=str(self.store_path), data=self.data
            )
        return self.human


@dataclass(frozen=True, slots=True)
class Session:
    path: Path
    connection: sqlite3.Connection
    schema_version: int


def open_store(store: str | None, *, create: bool = True, verbose: bool = False) -> Session:
    path = resolve_store_path(store)
    obs.configure(log_path_for(path), verbose=verbose)
    connection = conn.connect(path, create=create)

    report = integrity.check_quick(connection, path)
    if not report.ok:
        obs.integrity_problem(path, len(report.problems))
        integrity.raise_if_corrupt(report)

    before = conn.user_version(connection)
    plan = migrate.ensure_current(connection, path)
    if not plan.is_noop:
        obs.migration_applied(before, plan.target)

    version = conn.user_version(connection)
    obs.store_opened(path, version)
    return Session(path, connection, version)


def store_info(session: Session) -> Result:
    gathered = stats.gather(session.connection, session.path, session.schema_version)
    rows = [
        [
            source.name,
            f"{source.records:,}",
            f"{source.withdrawn:,}",
            f"{source.future_dated:,}",
            when(source.earliest_utc, date_only=True),
            when(source.latest_utc, date_only=True),
            when(source.last_ingested_utc),
        ]
        for source in gathered.sources
    ]
    body = table(
        ["SOURCE", "RECORDS", "WITHDRAWN", "FUTURE-DATED", "EARLIEST", "LATEST", "LAST INGESTED"],
        rows,
    )
    summary = (
        f"{gathered.records:,} records · {gathered.withdrawn:,} withdrawn · "
        f"{gathered.future_dated:,} future-dated · {gathered.corrections:,} corrections"
    )
    human = "\n".join(
        part
        for part in [
            f"Store: {gathered.path}  (schema v{gathered.schema_version}, "
            f"{size(gathered.size_bytes)})",
            "",
            body or "No sources yet.",
            "",
            summary,
        ]
        if part is not None
    )
    return Result(
        "store.info",
        True,
        session.path,
        {
            "schema_version": gathered.schema_version,
            "size_bytes": gathered.size_bytes,
            "sources": [
                {
                    "name": s.name,
                    "records": s.records,
                    "withdrawn": s.withdrawn,
                    "future_dated": s.future_dated,
                    "earliest_utc": s.earliest_utc,
                    "latest_utc": s.latest_utc,
                    "last_ingested_utc": s.last_ingested_utc,
                }
                for s in gathered.sources
            ],
            "totals": {
                "records": gathered.records,
                "withdrawn": gathered.withdrawn,
                "future_dated": gathered.future_dated,
                "corrections": gathered.corrections,
                "pending_corrections": gathered.pending_corrections,
                "attributions": gathered.attributions,
            },
        },
        human,
    )


def store_check(session: Session) -> Result:
    report = integrity.check_full(session.connection, session.path)
    if report.ok:
        human = f"Store: {session.path}\n\n  integrity_check  ok"
    else:
        obs.integrity_problem(session.path, len(report.problems))
        problems = "\n".join(f"  {problem}" for problem in report.problems[:20])
        human = (
            f"Store: {session.path}\n\nintegrity_check FAILED\n{problems}\n\n"
            "The store has NOT been modified. Restore from a backup, or move it aside "
            "and re-ingest — exporting your corrections first if it still opens."
        )
    return Result(
        "store.check",
        report.ok,
        session.path,
        {"ok": report.ok, "problems": list(report.problems)},
        human,
    )


def store_migrate(session: Session, *, dry_run: bool) -> Result:
    pending = migrate.plan(session.connection)
    if pending.is_noop:
        human = f"Store is at schema v{pending.current}; nothing to migrate."
        return Result(
            "store.migrate",
            True,
            session.path,
            {"current": pending.current, "target": pending.target, "applied": []},
            human,
        )

    names = [step.name for step in pending.steps]
    if dry_run:
        listed = "\n".join(f"  v{step.version}  {step.name}" for step in pending.steps)
        human = (
            f"Store at schema v{pending.current}; would migrate to v{pending.target}:\n"
            f"{listed}\n\nNothing has been changed (--dry-run)."
        )
        return Result(
            "store.migrate",
            True,
            session.path,
            {"current": pending.current, "target": pending.target, "would_apply": names},
            human,
        )

    applied = migrate.migrate(session.connection, session.path)
    obs.migration_applied(applied.current, applied.target)
    human = (
        f"Migrated schema v{applied.current} -> v{applied.target}:\n"
        + "\n".join(f"  v{step.version}  {step.name} ... ok" for step in applied.steps)
    )
    return Result(
        "store.migrate",
        True,
        session.path,
        {"current": applied.current, "target": applied.target, "applied": names},
        human,
    )


def store_protection(session: Session) -> Result:
    perms = permissions.check(session.path)
    crypto = encryption.check(session.path)

    lines = [
        f"Store: {session.path}",
        "",
        f"  file permissions   {perms.status.value:<13} {perms.detail}",
        f"  disk encryption    {crypto.status.value:<13} {crypto.detail}",
    ]
    if crypto.status is encryption.EncryptionStatus.UNVERIFIED and crypto.how_to_check:
        lines += ["", "  To check disk encryption yourself:", f"      {crypto.how_to_check}"]

    return Result(
        "store.protection",
        True,
        session.path,
        {
            "permissions": {"status": perms.status.value, "detail": perms.detail},
            "disk_encryption": {
                "status": crypto.status.value,
                "detail": crypto.detail,
                "how_to_check": crypto.how_to_check,
            },
        },
        "\n".join(lines),
    )


def _parse_date(text: str | None, *, end_of_day: bool = False) -> datetime | None:
    if text is None:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise UsageError(f"{text!r} is not a date (expected YYYY-MM-DD)") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if end_of_day and len(text) == 10:
        moment = moment.replace(hour=23, minute=59, second=59, microsecond=999_999)
    return moment


def records_query(
    session: Session,
    *,
    since: str | None,
    until: str | None,
    source: str | None,
    include_withdrawn: bool,
) -> Result:
    found = records_repo.query(
        session.connection,
        since=_parse_date(since),
        until=_parse_date(until, end_of_day=True),
        source=source,
        include_withdrawn=include_withdrawn,
    )
    elapsed = records_repo.elapsed(found)
    not_yet = len(found) - len(elapsed)

    rows = [
        [
            when(record.occurred_utc),
            record.source,
            record.title[:48],
            "withdrawn" if record.withdrawn else "",
        ]
        for record in found
    ]
    body = table(["WHEN", "SOURCE", "TITLE", ""], rows) or "No records match."
    summary = f"{len(found):,} records"
    if not_yet:
        summary += f" · {not_yet:,} not yet elapsed (excluded from elapsed-time totals)"
    human = f"{body}\n\n{summary}"

    return Result(
        "records.query",
        True,
        session.path,
        {
            "records": [
                {
                    "source": r.source,
                    "source_id": r.source_id,
                    "occurred_utc": r.occurred_utc,
                    "title": r.title,
                    "withdrawn": r.withdrawn,
                    "revision": r.revision,
                }
                for r in found
            ],
            "count": len(found),
            "not_yet_elapsed": not_yet,
        },
        human,
    )


def derived_discard(session: Session) -> Result:
    removed = derived_repo.discard(session.connection)
    human = (
        f"Discarded {removed:,} derived attributions.\n"
        "Raw records and corrections are untouched; re-derivation needs no source."
    )
    return Result(
        "derived.discard", True, session.path, {"discarded": removed}, human
    )


def corrections_export(session: Session, *, out: str | None) -> Result:
    lines = list(portable.export(session.connection))
    if out is not None:
        Path(out).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        human = f"Exported {len(lines):,} corrections to {out}"
    else:
        human = "\n".join(lines)
    return Result(
        "corrections.export",
        True,
        session.path,
        {"count": len(lines), "corrections": lines},
        human,
    )


def corrections_import(session: Session, *, path: str, dry_run: bool) -> Result:
    source_file = Path(path)
    if not source_file.exists():
        raise UsageError(f"no such file: {path}")
    incoming = portable.parse(source_file.read_text(encoding="utf-8").splitlines())
    report = portable.import_corrections(session.connection, incoming, dry_run=dry_run)
    if not dry_run:
        corrections_repo.refresh_pending(session.connection)
        obs.corrections_imported(
            new=len(report.new),
            replaced=len(report.replaced),
            declined=len(report.declined),
            pending=len(report.pending),
        )

    lines = [
        f"{report.total:,} corrections read.",
        f"  {len(report.new):>5,} new",
        f"  {len(report.replaced):>5,} replaced an older local correction",
        f"  {len(report.declined):>5,} declined — the local correction is newer or equal",
        f"  {len(report.pending):>5,} kept as pending — no matching record in this store",
    ]
    # FR-034: every change and every refusal is named. Newest-wins is only as good as the
    # clocks involved, so the guarantee that can actually be made is that nothing is
    # replaced silently.
    for label, group in (("Replaced", report.replaced), ("Declined", report.declined)):
        if group:
            lines += ["", f"{label} (local → imported):"]
            for decision in group[:20]:
                existing = decision.existing
                lines.append(
                    f"  {decision.imported.source} / {decision.imported.source_id}  "
                    f"{existing.project!r} → {decision.imported.project!r}"
                    if existing
                    else f"  {decision.imported.source} / {decision.imported.source_id}"
                )
            if len(group) > 20:
                lines.append(f"  … {len(group) - 20} more, see --json")
    if dry_run:
        lines += ["", "Nothing has been written (--dry-run)."]

    return Result(
        "corrections.import",
        True,
        session.path,
        {
            "total": report.total,
            "new": len(report.new),
            "replaced": len(report.replaced),
            "declined": len(report.declined),
            "pending": len(report.pending),
            "decisions": [
                {
                    "outcome": d.outcome.value,
                    "source": d.imported.source,
                    "source_id": d.imported.source_id,
                    "imported_project": d.imported.project,
                    "imported_made_at_utc": d.imported.made_at_utc,
                    "existing_project": d.existing.project if d.existing else None,
                    "existing_made_at_utc": d.existing.made_at_utc if d.existing else None,
                }
                for d in report.decisions
            ],
            "dry_run": dry_run,
        },
        "\n".join(lines),
    )


def corrections_list(session: Session, *, pending_only: bool) -> Result:
    found = corrections_repo.all_corrections(session.connection, pending_only=pending_only)
    rows = [
        [c.source, c.source_id[:36], str(c.project), when(c.made_at_utc), "pending" if c.pending else ""]
        for c in found
    ]
    body = table(["SOURCE", "SOURCE ID", "PROJECT", "MADE AT", ""], rows) or "No corrections."
    return Result(
        "corrections.list",
        True,
        session.path,
        {
            "corrections": [
                {
                    "source": c.source,
                    "source_id": c.source_id,
                    "project": c.project,
                    "note": c.note,
                    "made_at_utc": c.made_at_utc,
                    "pending": c.pending,
                }
                for c in found
            ],
            "count": len(found),
        },
        f"{body}\n\n{len(found):,} corrections",
    )


def fail(command: str, store_path: Path, error: IkwydError) -> Result:
    lines = [error.message]
    if error.remedy:
        lines += ["", error.remedy]
    return Result(
        command,
        False,
        store_path,
        {"error": type(error).__name__, "message": error.message, "remedy": error.remedy},
        "\n".join(lines),
    )


def emit(result: Result, *, as_json: bool) -> int:
    """Results to stdout, diagnostics to stderr (Principle VI)."""
    text = result.render(as_json)
    stream = sys.stdout if result.ok or as_json else sys.stderr
    if text:
        print(text, file=stream)
    if not result.ok and as_json:
        print(result.human, file=sys.stderr)
    return result.exit_code
