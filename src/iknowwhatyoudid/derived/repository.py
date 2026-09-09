"""Derived attributions: stored here, produced by a later feature (FR-010, FR-015, FR-019)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..records import timestamps
from ..store.connection import writing


@dataclass(frozen=True, slots=True)
class Attribution:
    """A mapping of a record to a project, produced by a rule.

    Always inferred. A *user's* statement is a `user_correction` in a different table,
    which is what makes FR-019's "distinguishable from a user-confirmed one" true by
    construction rather than by a flag someone could set wrongly.
    """

    id: int
    record_id: int
    project: str
    rule: str
    evidence: Mapping[str, Any]
    derived_at_utc: int


def add(
    connection: sqlite3.Connection,
    *,
    record_id: int,
    project: str,
    rule: str,
    evidence: Mapping[str, Any],
    derived_at_utc: int | None = None,
) -> int:
    at = timestamps.now_micros() if derived_at_utc is None else derived_at_utc
    with writing(connection):
        cursor = connection.execute(
            "INSERT INTO derived_attribution (record_id, project, rule, evidence, "
            "derived_at_utc) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (record_id, project, rule, json.dumps(evidence, sort_keys=True), at),
        )
        return int(cursor.fetchone()[0])


def for_record(connection: sqlite3.Connection, record_id: int) -> list[Attribution]:
    rows = connection.execute(
        "SELECT id, record_id, project, rule, evidence, derived_at_utc "
        "FROM derived_attribution WHERE record_id = ? ORDER BY id",
        (record_id,),
    ).fetchall()
    return [
        Attribution(
            id=int(row["id"]),
            record_id=int(row["record_id"]),
            project=str(row["project"]),
            rule=str(row["rule"]),
            evidence=json.loads(row["evidence"]),
            derived_at_utc=int(row["derived_at_utc"]),
        )
        for row in rows
    ]


def count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT count(*) FROM derived_attribution").fetchone()[0])


def discard(connection: sqlite3.Connection) -> int:
    """Discard the derived region, leaving raw records and corrections untouched (FR-010).

    Re-deriving afterwards reads nothing from any source (FR-015) — everything it needs
    is already in the raw region.
    """
    with writing(connection):
        removed = count(connection)
        connection.execute("DELETE FROM derived_attribution")
    return removed
