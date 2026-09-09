"""Storing corrections so they outlive everything else (FR-017 to FR-019, FR-032)."""

from __future__ import annotations

import sqlite3

from ..records import timestamps
from ..store.connection import writing
from .model import Correction


def _row(row: sqlite3.Row) -> Correction:
    return Correction(
        id=int(row["id"]),
        source=str(row["source"]),
        source_id=str(row["source_id"]),
        project=row["project"],
        note=row["note"],
        made_at_utc=int(row["made_at_utc"]),
        pending=bool(row["pending"]),
    )


def _record_exists(connection: sqlite3.Connection, source: str, source_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM raw_record WHERE source = ? AND source_id = ?", (source, source_id)
    ).fetchone()
    return row is not None


def record(
    connection: sqlite3.Connection,
    *,
    source: str,
    source_id: str,
    project: str | None,
    note: str | None = None,
    made_at_utc: int | None = None,
) -> Correction:
    """Make or replace this user's standing correction for a record."""
    made_at = timestamps.now_micros() if made_at_utc is None else made_at_utc
    with writing(connection):
        pending = not _record_exists(connection, source, source_id)
        connection.execute(
            "INSERT INTO user_correction (source, source_id, project, note, made_at_utc, "
            "pending) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, source_id) DO UPDATE SET "
            "  project = excluded.project, note = excluded.note, "
            "  made_at_utc = excluded.made_at_utc, pending = excluded.pending",
            (source, source_id, project, note, made_at, int(pending)),
        )
    found = get(connection, source, source_id)
    assert found is not None
    return found


def get(connection: sqlite3.Connection, source: str, source_id: str) -> Correction | None:
    row = connection.execute(
        "SELECT id, source, source_id, project, note, made_at_utc, pending "
        "FROM user_correction WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    return None if row is None else _row(row)


def all_corrections(
    connection: sqlite3.Connection, *, pending_only: bool = False
) -> list[Correction]:
    where = " WHERE pending = 1" if pending_only else ""
    rows = connection.execute(
        "SELECT id, source, source_id, project, note, made_at_utc, pending "
        f"FROM user_correction{where} ORDER BY source, source_id",
        (),
    ).fetchall()
    return [_row(row) for row in rows]


def count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT count(*) FROM user_correction").fetchone()[0])


def refresh_pending(connection: sqlite3.Connection) -> int:
    """Clear the pending flag on corrections whose record has since been ingested.

    FR-018: a correction imported for an absent record is retained and reported as
    pending; it stops being pending when the record arrives, with no user action.
    """
    with writing(connection):
        cursor = connection.execute(
            "UPDATE user_correction SET pending = 0 WHERE pending = 1 AND EXISTS ("
            "  SELECT 1 FROM raw_record r WHERE r.source = user_correction.source "
            "  AND r.source_id = user_correction.source_id)"
        )
        return int(cursor.rowcount)


def project_for(
    connection: sqlite3.Connection, source: str, source_id: str
) -> tuple[str | None, bool]:
    """The project a record belongs to, and whether that came from the user.

    A correction always wins over an inferred attribution (FR-019, Principle V). The
    boolean is what keeps an inference from being presented as an established fact.
    """
    correction = get(connection, source, source_id)
    if correction is not None:
        return correction.project, True

    row = connection.execute(
        "SELECT d.project FROM derived_attribution d "
        "JOIN raw_record r ON r.id = d.record_id "
        "WHERE r.source = ? AND r.source_id = ? ORDER BY d.derived_at_utc DESC LIMIT 1",
        (source, source_id),
    ).fetchone()
    return (None, False) if row is None else (str(row["project"]), False)
