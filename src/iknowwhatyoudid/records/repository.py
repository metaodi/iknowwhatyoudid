"""Reading and writing raw records (FR-011 to FR-014, FR-027 to FR-029, FR-035 to FR-038)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime

from ..errors import BatchError
from ..store.connection import writing
from . import identity, timestamps
from .model import Batch, IngestResult, NormalizedRecord, RunMode, StoredRecord


def _ensure_source(connection: sqlite3.Connection, source: str, now: int) -> None:
    connection.execute(
        "INSERT INTO raw_source (name, first_seen_utc) VALUES (?, ?) "
        "ON CONFLICT(name) DO NOTHING",
        (source, now),
    )


def _prepared(source: str, record: NormalizedRecord) -> tuple[str, bool, int, int, str | None]:
    occurred_utc = timestamps.to_utc_micros(record.occurred)
    source_id = record.source_id
    derived = source_id is None
    if derived:
        source_id = identity.derive_source_id(
            source, occurred_utc, record.title, record.payload
        )
    assert source_id is not None
    return (
        source_id,
        derived,
        occurred_utc,
        timestamps.offset_minutes(record.occurred),
        timestamps.zone_name(record.occurred),
    )


def ingest(
    connection: sqlite3.Connection,
    batch: Batch,
    *,
    started_at_utc: int | None = None,
) -> IngestResult:
    """Apply one batch in a single transaction: all of it lands, or none of it does.

    The source's resumption point advances inside the same transaction, so an
    interrupted ingestion resumes from the last *completed* batch and never duplicates
    or skips (FR-013).
    """
    batch.validate()
    started = timestamps.now_micros() if started_at_utc is None else started_at_utc

    inserted = updated = unchanged = withdrawn = unwithdrawn = 0

    with writing(connection):
        _ensure_source(connection, batch.source, started)

        range_from = (
            timestamps.to_utc_micros(batch.range_from) if batch.range_from else None
        )
        range_to = timestamps.to_utc_micros(batch.range_to) if batch.range_to else None

        cursor = connection.execute(
            "INSERT INTO raw_ingestion_run "
            "(source, mode, range_from_utc, range_to_utc, started_at_utc) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            (batch.source, batch.mode.value, range_from, range_to, started),
        )
        run_id = int(cursor.fetchone()[0])

        latest_occurred: int | None = None
        for record in batch.records:
            source_id, derived, occurred_utc, offset, zone = _prepared(batch.source, record)
            payload = identity.canonical_json(record.payload)
            duration = timestamps.duration_micros(record.duration)

            existing = connection.execute(
                "SELECT id, occurred_utc, occurred_offset_minutes, occurred_zone, "
                "       duration_us, title, payload, withdrawn_on_utc "
                "FROM raw_record WHERE source = ? AND source_id = ?",
                (batch.source, source_id),
            ).fetchone()

            if existing is None:
                connection.execute(
                    "INSERT INTO raw_record ("
                    "  source, source_id, source_id_is_derived, occurred_utc,"
                    "  occurred_offset_minutes, occurred_zone, duration_us, title,"
                    "  payload, ingestion_run"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        batch.source,
                        source_id,
                        int(derived),
                        occurred_utc,
                        offset,
                        zone,
                        duration,
                        record.title,
                        payload,
                        run_id,
                    ),
                )
                inserted += 1
            else:
                changed = (
                    existing["occurred_utc"] != occurred_utc
                    or existing["occurred_offset_minutes"] != offset
                    or existing["occurred_zone"] != zone
                    or existing["duration_us"] != duration
                    or existing["title"] != record.title
                    or existing["payload"] != payload
                )
                was_withdrawn = existing["withdrawn_on_utc"] is not None
                if changed:
                    # Same record, new revision (FR-014) — not a second row.
                    connection.execute(
                        "UPDATE raw_record SET occurred_utc = ?, "
                        "  occurred_offset_minutes = ?, occurred_zone = ?, "
                        "  duration_us = ?, title = ?, payload = ?, "
                        "  ingestion_run = ?, revision = revision + 1, "
                        "  withdrawn_on_utc = NULL "
                        "WHERE id = ?",
                        (
                            occurred_utc,
                            offset,
                            zone,
                            duration,
                            record.title,
                            payload,
                            run_id,
                            existing["id"],
                        ),
                    )
                    updated += 1
                else:
                    unchanged += 1
                    if was_withdrawn:
                        # Reappeared: clear the withdrawal, do not insert again (FR-029).
                        connection.execute(
                            "UPDATE raw_record SET withdrawn_on_utc = NULL WHERE id = ?",
                            (existing["id"],),
                        )
                if was_withdrawn:
                    unwithdrawn += 1

            latest_occurred = (
                occurred_utc if latest_occurred is None else max(latest_occurred, occurred_utc)
            )

        if batch.mode is RunMode.SWEEP:
            withdrawn = _withdraw_missing(connection, batch, range_from, range_to, started)

        finished = timestamps.now_micros()
        connection.execute(
            "UPDATE raw_ingestion_run SET finished_at_utc = ?, record_count = ?, "
            "completed = 1 WHERE id = ?",
            (finished, len(batch.records), run_id),
        )

        resumption = range_to if range_to is not None else latest_occurred
        if resumption is not None:
            connection.execute(
                "UPDATE raw_source SET resumption_point_utc = ? WHERE name = ? "
                "AND (resumption_point_utc IS NULL OR resumption_point_utc < ?)",
                (resumption, batch.source, resumption),
            )

    return IngestResult(
        run_id=run_id,
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        withdrawn=withdrawn,
        unwithdrawn=unwithdrawn,
    )


def _withdraw_missing(
    connection: sqlite3.Connection,
    batch: Batch,
    range_from: int | None,
    range_to: int | None,
    observed_at: int,
) -> int:
    """Mark records the sweep did not see as withdrawn (FR-027).

    Only ever reached for RunMode.SWEEP, and bounded to the window the sweep covered
    and the source it read. Records are marked, never deleted.
    """
    assert batch.seen_source_ids is not None
    assert range_from is not None and range_to is not None

    candidates = connection.execute(
        "SELECT id, source_id FROM raw_record "
        "WHERE source = ? AND occurred_utc >= ? AND occurred_utc <= ? "
        "AND withdrawn_on_utc IS NULL",
        (batch.source, range_from, range_to),
    ).fetchall()

    missing = [
        row["id"] for row in candidates if row["source_id"] not in batch.seen_source_ids
    ]
    for record_id in missing:
        connection.execute(
            "UPDATE raw_record SET withdrawn_on_utc = ? WHERE id = ?",
            (observed_at, record_id),
        )
    return len(missing)


def _row_to_record(row: sqlite3.Row) -> StoredRecord:
    return StoredRecord(
        id=int(row["id"]),
        source=str(row["source"]),
        source_id=str(row["source_id"]),
        source_id_is_derived=bool(row["source_id_is_derived"]),
        occurred_utc=int(row["occurred_utc"]),
        occurred_offset_minutes=int(row["occurred_offset_minutes"]),
        occurred_zone=row["occurred_zone"],
        duration_us=row["duration_us"],
        title=str(row["title"]),
        payload=json.loads(row["payload"]),
        ingestion_run=int(row["ingestion_run"]),
        revision=int(row["revision"]),
        withdrawn_on_utc=row["withdrawn_on_utc"],
    )


def query(
    connection: sqlite3.Connection,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    source: str | None = None,
    include_withdrawn: bool = False,
) -> list[StoredRecord]:
    """Records by time range and source. Withdrawn ones are excluded by default (FR-028)."""
    clauses: list[str] = []
    params: list[object] = []
    if since is not None:
        clauses.append("occurred_utc >= ?")
        params.append(timestamps.to_utc_micros(since))
    if until is not None:
        clauses.append("occurred_utc <= ?")
        params.append(timestamps.to_utc_micros(until))
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if not include_withdrawn:
        clauses.append("withdrawn_on_utc IS NULL")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        "SELECT id, source, source_id, source_id_is_derived, occurred_utc, "
        "occurred_offset_minutes, occurred_zone, duration_us, title, payload, "
        "ingestion_run, revision, withdrawn_on_utc "
        f"FROM raw_record{where} ORDER BY occurred_utc, id",
        params,
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def elapsed(records: Iterable[StoredRecord], at: int | None = None) -> list[StoredRecord]:
    """Only records whose time has passed — what a summary of elapsed time may count.

    FR-036 and FR-037: evaluated now, not at ingestion, so a record starts counting the
    moment its time arrives without anything being re-ingested.
    """
    moment = timestamps.now_micros() if at is None else at
    return [r for r in records if not timestamps.not_yet_elapsed(r.occurred_utc, moment)]


def resumption_point(connection: sqlite3.Connection, source: str) -> int | None:
    row = connection.execute(
        "SELECT resumption_point_utc FROM raw_source WHERE name = ?", (source,)
    ).fetchone()
    return None if row is None else row["resumption_point_utc"]


def discard_raw(connection: sqlite3.Connection) -> int:
    """Discard the raw region. Cascades into derived; corrections are untouched (FR-010)."""
    with writing(connection):
        count = int(connection.execute("SELECT count(*) FROM raw_record").fetchone()[0])
        connection.execute("DELETE FROM raw_record")
        connection.execute("DELETE FROM raw_ingestion_run")
        connection.execute("DELETE FROM raw_source")
    return count


def source_names(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute("SELECT DISTINCT source FROM raw_record").fetchall()
    return frozenset(str(row["source"]) for row in rows)


def record_count(connection: sqlite3.Connection, source: str) -> int:
    row = connection.execute(
        "SELECT count(*) FROM raw_record WHERE source = ?", (source,)
    ).fetchone()
    return int(row[0])


def require_records(records: Sequence[NormalizedRecord]) -> None:
    if not records:
        raise BatchError("batch contains no records")
