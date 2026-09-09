"""Detecting a store that cannot be read (FR-026).

Nothing here ever deletes or overwrites the store. A corrupt store may still be the only
copy of a year of withdrawn records and corrections — data no source can supply again —
so the tool reports and stops.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..errors import StoreCorruptError
from . import connection as conn

_OK = "ok"


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    path: Path
    ok: bool
    problems: tuple[str, ...]


def check_quick(connection: sqlite3.Connection, path: Path) -> IntegrityReport:
    try:
        result = conn.quick_check(connection)
    except sqlite3.DatabaseError as exc:
        return IntegrityReport(path, False, (str(exc),))
    return IntegrityReport(path, result == _OK, () if result == _OK else (result,))


def check_full(connection: sqlite3.Connection, path: Path) -> IntegrityReport:
    try:
        results = conn.integrity_check(connection)
    except sqlite3.DatabaseError as exc:
        return IntegrityReport(path, False, (str(exc),))
    if results == [_OK]:
        return IntegrityReport(path, True, ())
    return IntegrityReport(path, False, tuple(results))


def raise_if_corrupt(report: IntegrityReport) -> None:
    if report.ok:
        return
    raise StoreCorruptError(
        f"{report.path} failed its integrity check:\n  "
        + "\n  ".join(report.problems[:10]),
        remedy=(
            "The store has NOT been modified. Restore it from a backup, or move it "
            "aside and re-ingest — but export your corrections first if the store "
            "still opens, since those cannot be regenerated."
        ),
    )
