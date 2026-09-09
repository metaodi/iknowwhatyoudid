"""The durable implementation of feature 0002's source-state port.

0002 was planned before this feature and runs against an in-memory stand-in. The port is
unchanged; only the backing changes. See contracts/source-state.md.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ..records import repository, timestamps


@dataclass(frozen=True, slots=True)
class SourceRunOutcome:
    """Mirrors 0002's outcome type, so the port signature matches."""

    source_name: str
    succeeded: bool
    records_ingested: int = 0
    failure: str | None = None


class SourceStateStore(Protocol):
    def resumption_point(self, source_name: str) -> datetime | None: ...

    def record_ingestion(
        self, outcome: SourceRunOutcome, through: datetime | None
    ) -> None: ...

    def known_source_names(self) -> frozenset[str]: ...

    def record_count(self, source_name: str) -> int: ...


class SqliteSourceStateStore:
    """Four operations, no query surface — narrow on purpose.

    This port must not become a general-purpose data-access layer, and it should be
    obvious at a glance that it has not.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def resumption_point(self, source_name: str) -> datetime | None:
        micros = repository.resumption_point(self._connection, source_name)
        if micros is None:
            return None
        return datetime.fromtimestamp(micros / timestamps.MICROSECONDS, tz=UTC)

    def record_ingestion(
        self, outcome: SourceRunOutcome, through: datetime | None
    ) -> None:
        """Advance the resumption point, but only for a run that completed (FR-013)."""
        if not outcome.succeeded or through is None:
            return
        micros = timestamps.to_utc_micros(through)
        from ..store.connection import writing

        with writing(self._connection):
            self._connection.execute(
                "INSERT INTO raw_source (name, first_seen_utc, resumption_point_utc) "
                "VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "  resumption_point_utc = max("
                "    coalesce(raw_source.resumption_point_utc, 0), excluded.resumption_point_utc)",
                (outcome.source_name, timestamps.now_micros(), micros),
            )

    def known_source_names(self) -> frozenset[str]:
        """Sources that *hold records*, including ones no longer configured.

        Reads from raw_record rather than raw_source deliberately: 0002 needs this to
        report a source removed from the configuration whose records remain, rather than
        letting them be silently orphaned. A source row with no records is not a source
        whose data would be lost.
        """
        return repository.source_names(self._connection)

    def record_count(self, source_name: str) -> int:
        return repository.record_count(self._connection, source_name)
