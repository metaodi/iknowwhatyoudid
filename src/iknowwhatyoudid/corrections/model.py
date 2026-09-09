"""The only irreplaceable data in the store."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Correction:
    """A user's authoritative statement about a record.

    Identified by ``(source, source_id)`` — the source's own keys — and never by an
    internal row id. That is what lets a correction survive a delete-and-rebuild, where
    every internal id changes (FR-017), and what lets one arrive for a record this store
    does not hold (FR-018).
    """

    source: str
    source_id: str
    project: str | None
    note: str | None
    made_at_utc: int
    pending: bool = False
    id: int | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.source_id)


class ImportOutcome(StrEnum):
    NEW = "new"
    REPLACED = "replaced"
    DECLINED = "declined"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class ImportDecision:
    """What happened to one imported correction, and what it displaced.

    ``existing`` is carried so that every replacement and every refusal can be reported
    with both versions (FR-034) — the mitigation for newest-wins being only as
    trustworthy as the clocks involved.
    """

    outcome: ImportOutcome
    imported: Correction
    existing: Correction | None = None


@dataclass(frozen=True, slots=True)
class ImportReport:
    decisions: tuple[ImportDecision, ...]

    def _of(self, outcome: ImportOutcome) -> tuple[ImportDecision, ...]:
        return tuple(d for d in self.decisions if d.outcome is outcome)

    @property
    def new(self) -> tuple[ImportDecision, ...]:
        return self._of(ImportOutcome.NEW)

    @property
    def replaced(self) -> tuple[ImportDecision, ...]:
        return self._of(ImportOutcome.REPLACED)

    @property
    def declined(self) -> tuple[ImportDecision, ...]:
        return self._of(ImportOutcome.DECLINED)

    @property
    def pending(self) -> tuple[ImportDecision, ...]:
        return self._of(ImportOutcome.PENDING)

    @property
    def total(self) -> int:
        return len(self.decisions)
