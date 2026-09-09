"""What the store holds (FR-003, FR-016, FR-038)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..records import timestamps


@dataclass(frozen=True, slots=True)
class SourceStats:
    name: str
    records: int
    withdrawn: int
    future_dated: int
    earliest_utc: int | None
    latest_utc: int | None
    last_ingested_utc: int | None


@dataclass(frozen=True, slots=True)
class StoreStats:
    path: Path
    schema_version: int
    size_bytes: int
    sources: tuple[SourceStats, ...]
    corrections: int
    pending_corrections: int
    attributions: int

    @property
    def records(self) -> int:
        return sum(source.records for source in self.sources)

    @property
    def withdrawn(self) -> int:
        return sum(source.withdrawn for source in self.sources)

    @property
    def future_dated(self) -> int:
        return sum(source.future_dated for source in self.sources)


def gather(connection: sqlite3.Connection, path: Path, schema_version: int) -> StoreStats:
    rows = connection.execute(
        """
        SELECT s.name                                              AS name,
               count(r.id)                                         AS records,
               coalesce(sum(r.withdrawn_on_utc IS NOT NULL), 0)     AS withdrawn,
               min(r.occurred_utc)                                 AS earliest,
               max(r.occurred_utc)                                 AS latest
        FROM raw_source s
        LEFT JOIN raw_record r ON r.source = s.name
        GROUP BY s.name
        ORDER BY s.name
        """
    ).fetchall()

    # FR-038: a record whose time was ahead of the run that ingested it. Compared against
    # the run, not against now, so it stays a permanent signal about a wrong source clock
    # rather than something that quietly resolves itself.
    future_rows = connection.execute(
        """
        SELECT r.source AS source, count(*) AS n
        FROM raw_record r
        JOIN raw_ingestion_run run ON run.id = r.ingestion_run
        WHERE r.occurred_utc > run.started_at_utc
        GROUP BY r.source
        """
    ).fetchall()
    future_by_source = {str(row["source"]): int(row["n"]) for row in future_rows}

    ingested_rows = connection.execute(
        "SELECT source, max(finished_at_utc) AS last FROM raw_ingestion_run "
        "WHERE completed = 1 GROUP BY source"
    ).fetchall()
    last_by_source = {str(row["source"]): row["last"] for row in ingested_rows}

    sources = tuple(
        SourceStats(
            name=str(row["name"]),
            records=int(row["records"]),
            withdrawn=int(row["withdrawn"]),
            future_dated=future_by_source.get(str(row["name"]), 0),
            earliest_utc=row["earliest"],
            latest_utc=row["latest"],
            last_ingested_utc=last_by_source.get(str(row["name"])),
        )
        for row in rows
    )

    corrections = int(
        connection.execute("SELECT count(*) FROM user_correction").fetchone()[0]
    )
    pending = int(
        connection.execute(
            "SELECT count(*) FROM user_correction WHERE pending = 1"
        ).fetchone()[0]
    )
    attributions = int(
        connection.execute("SELECT count(*) FROM derived_attribution").fetchone()[0]
    )

    return StoreStats(
        path=path,
        schema_version=schema_version,
        size_bytes=path.stat().st_size if path.exists() else 0,
        sources=sources,
        corrections=corrections,
        pending_corrections=pending,
        attributions=attributions,
    )


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """Records that a rebuild could not reproduce (FR-016)."""

    missing: tuple[tuple[str, str], ...]

    @property
    def count(self) -> int:
        return len(self.missing)


def rebuild_report(
    connection: sqlite3.Connection, before: dict[str, frozenset[str]]
) -> RebuildReport:
    """Compare a pre-rebuild census of ``source -> source ids`` against what is here now.

    A record the sources no longer expose cannot come back. Naming it is what stops it
    disappearing silently — the difference between an acknowledged gap and an
    unacknowledged one.
    """
    missing: list[tuple[str, str]] = []
    for source, ids in before.items():
        rows = connection.execute(
            "SELECT source_id FROM raw_record WHERE source = ?", (source,)
        ).fetchall()
        present = {str(row["source_id"]) for row in rows}
        missing.extend((source, sid) for sid in sorted(ids - present))
    return RebuildReport(tuple(missing))


def census(connection: sqlite3.Connection) -> dict[str, frozenset[str]]:
    """A snapshot of what each source currently contributes, for `rebuild_report`."""
    rows = connection.execute("SELECT source, source_id FROM raw_record").fetchall()
    found: dict[str, set[str]] = {}
    for row in rows:
        found.setdefault(str(row["source"]), set()).add(str(row["source_id"]))
    return {source: frozenset(ids) for source, ids in found.items()}


def elapsed_only(connection: sqlite3.Connection, source: str | None = None) -> int:
    """Count of records whose time has passed — what a summary may count (FR-036)."""
    now = timestamps.now_micros()
    if source is None:
        row = connection.execute(
            "SELECT count(*) FROM raw_record WHERE occurred_utc <= ? "
            "AND withdrawn_on_utc IS NULL",
            (now,),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT count(*) FROM raw_record WHERE source = ? AND occurred_utc <= ? "
            "AND withdrawn_on_utc IS NULL",
            (source, now),
        ).fetchone()
    return int(row[0])
