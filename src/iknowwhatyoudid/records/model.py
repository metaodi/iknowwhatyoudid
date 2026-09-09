"""The record contract a connector writes against.

See specs/0001-local-store-foundation/contracts/record-shape.md.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from ..errors import BatchError


class RunMode(StrEnum):
    """Whether a read was exhaustive over its window.

    This exists because withdrawal detection is impossible without it. An INCREMENTAL
    run asks the source only for what is new, so "absent from this run" and "deleted at
    the source" are indistinguishable. Withdrawing on any run would mark every record
    outside the window as withdrawn, on every run — a safety requirement turned into a
    data-destruction bug. Only the connector knows; so it must say. See research.md R6.
    """

    INCREMENTAL = "incremental"
    SWEEP = "sweep"


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    occurred: datetime
    title: str
    payload: Mapping[str, Any]
    source_id: str | None = None
    duration: timedelta | None = None


@dataclass(frozen=True, slots=True)
class Batch:
    source: str
    mode: RunMode = RunMode.INCREMENTAL
    records: Sequence[NormalizedRecord] = field(default_factory=tuple)
    range_from: datetime | None = None
    range_to: datetime | None = None
    seen_source_ids: frozenset[str] | None = None

    def validate(self) -> None:
        if not self.source:
            raise BatchError("a batch must name its source")
        if self.mode is RunMode.SWEEP:
            if self.range_from is None or self.range_to is None:
                raise BatchError(
                    "a sweep must state the window it covered",
                    remedy=(
                        "Withdrawal is bounded to the covered window; without bounds "
                        "it could withdraw records the run never looked at."
                    ),
                )
            if self.seen_source_ids is None:
                raise BatchError(
                    "a sweep must supply seen_source_ids",
                    remedy="These are what a stored record is checked against to decide "
                    "whether the source still presents it.",
                )
        elif self.seen_source_ids is not None:
            raise BatchError(
                "an incremental run must not supply seen_source_ids",
                remedy=(
                    "An incremental read is not exhaustive, so its record ids cannot "
                    "be used to conclude anything is missing. Use RunMode.SWEEP."
                ),
            )


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """A record as held in the store."""

    id: int
    source: str
    source_id: str
    source_id_is_derived: bool
    occurred_utc: int
    occurred_offset_minutes: int
    occurred_zone: str | None
    duration_us: int | None
    title: str
    payload: Mapping[str, Any]
    ingestion_run: int
    revision: int
    withdrawn_on_utc: int | None

    @property
    def withdrawn(self) -> bool:
        return self.withdrawn_on_utc is not None


@dataclass(frozen=True, slots=True)
class IngestionRun:
    id: int
    source: str
    mode: RunMode
    range_from_utc: int | None
    range_to_utc: int | None
    started_at_utc: int
    finished_at_utc: int | None
    record_count: int
    completed: bool


@dataclass(frozen=True, slots=True)
class IngestResult:
    run_id: int
    inserted: int
    updated: int
    unchanged: int
    withdrawn: int
    unwithdrawn: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged
