"""Running ingestion across configured sources (FR-042 to FR-045, T079).

One source failing never aborts the others, and every configured source appears in the
report — including skipped ones. A source that silently contributes nothing must still
be visible, because an invisible gap is the failure mode this project cares about most.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ..config.findings import Readiness
from ..config.validate import SourceStatus, ValidationReport
from ..kinds.spec import ReportsSkips
from ..records import repository as records_repo
from collections.abc import Sequence
from pathlib import Path

from ..records.model import Batch, NormalizedRecord, RunMode
from .state import SourceRunOutcome, SourceStateStore


class RunResult(StrEnum):
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


class FailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    CREDENTIAL = "credential"
    UNREACHABLE = "unreachable"
    SOURCE_ERROR = "source_error"


@dataclass(frozen=True, slots=True)
class Outcome:
    source_name: str
    kind: str
    result: RunResult
    failure: FailureCategory | None = None
    detail: str | None = None
    records_ingested: int = 0
    #: Parts of a source that could not be read while the rest still contributed. A
    #: partial success is still a success, but never a silent one (FR-020, SC-011).
    skipped_parts: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.result is RunResult.SUCCEEDED


@dataclass(frozen=True, slots=True)
class RunReport:
    outcomes: tuple[Outcome, ...]

    def _count(self, result: RunResult) -> int:
        return sum(1 for o in self.outcomes if o.result is result)

    @property
    def succeeded(self) -> int:
        return self._count(RunResult.SUCCEEDED)

    @property
    def failed(self) -> int:
        return self._count(RunResult.FAILED)

    @property
    def skipped(self) -> int:
        return self._count(RunResult.SKIPPED)

    @property
    def records_ingested(self) -> int:
        return sum(o.records_ingested for o in self.outcomes)

    @property
    def skipped_parts(self) -> int:
        return sum(len(o.skipped_parts) for o in self.outcomes)

    @property
    def ok(self) -> bool:
        """False when any source failed, which drives the non-zero exit (FR-044)."""
        return self.failed == 0


#: The window a sweep covers when nothing narrows it.
#:
#: A sweep must state its window, because that window bounds what may be withdrawn. A
#: source with no `since` and no resumption point — every source on its first run — is
#: sweeping everything it can present, and saying so is what lets a first `--sweep`
#: work at all.
BEGINNING_OF_TIME = datetime.min.replace(tzinfo=UTC)


_SKIP_REASONS: dict[Readiness, str] = {
    Readiness.DISABLED: "disabled",
    Readiness.NOT_READABLE: "reading not yet implemented",
    Readiness.UNKNOWN_KIND: "unknown kind",
}

_FAILURE_FOR: dict[Readiness, FailureCategory] = {
    Readiness.INVALID: FailureCategory.CONFIGURATION,
    Readiness.CREDENTIAL_MISSING: FailureCategory.CREDENTIAL,
}


def _ingest_one(
    status: SourceStatus,
    store: SourceStateStore,
    connection: sqlite3.Connection | None,
    mode: RunMode,
) -> Outcome:
    kind = status.kind
    assert kind is not None and kind.reader is not None

    resumed = store.resumption_point(status.name)
    since: datetime | None
    if mode is RunMode.SWEEP:
        # A sweep deliberately ignores the resumption point. Withdrawal concludes that
        # something the source no longer presents has gone, and that conclusion is only
        # sound over a window the run actually re-read. A sweep that resumed would read
        # almost nothing, and so could never notice a rewritten history — which is the
        # one thing a sweep exists to notice.
        since = status.source.since
    elif resumed is not None:
        # The stored point is the instant we have already read *through*, so resuming
        # from it unchanged would re-read the boundary record every run. SC-006 asks
        # for zero records re-read, so the next read starts just after it.
        since = resumed + timedelta(microseconds=1)
    else:
        since = status.source.since
    try:
        records = list(
            kind.reader.read(status.source, None, since, mode)
        )
    except OSError as exc:
        return Outcome(
            status.name, kind.name, RunResult.FAILED, FailureCategory.UNREACHABLE, str(exc)
        )
    except Exception as exc:  # noqa: BLE001 — one source's failure must not abort others
        return Outcome(
            status.name,
            kind.name,
            RunResult.FAILED,
            FailureCategory.SOURCE_ERROR,
            str(exc),
        )

    skipped_parts = (
        tuple(kind.reader.drain_skips())
        if isinstance(kind.reader, ReportsSkips)
        else ()
    )

    if connection is not None:
        # T079: RunMode and, for a sweep, the covered window and the ids actually seen,
        # are what let the store decide whether anything may be marked withdrawn.
        # An INCREMENTAL run supplies neither, so it can never withdraw.
        seen = (
            frozenset(r.source_id for r in records if r.source_id is not None)
            if mode is RunMode.SWEEP
            else None
        )
        window_from = (since or BEGINNING_OF_TIME) if mode is RunMode.SWEEP else None
        window_to = datetime.now(tz=UTC) if mode is RunMode.SWEEP else None
        batch = Batch(
            source=status.name,
            mode=mode,
            records=records,
            range_from=window_from,
            range_to=window_to,
            seen_source_ids=seen,
        )
        try:
            records_repo.ingest(connection, batch)
        except Exception as exc:  # noqa: BLE001
            return Outcome(
                status.name,
                kind.name,
                RunResult.FAILED,
                FailureCategory.SOURCE_ERROR,
                str(exc),
            )

    if connection is not None:
        _record_repositories(connection, records)
        _record_correspondents(connection, records)

    through = max((r.occurred for r in records), default=None)
    outcome = Outcome(
        status.name,
        kind.name,
        RunResult.SUCCEEDED,
        records_ingested=len(records),
        skipped_parts=skipped_parts,
    )
    store.record_ingestion(
        SourceRunOutcome(status.name, True, len(records)), through
    )
    return outcome


def ingest(
    report: ValidationReport,
    store: SourceStateStore,
    *,
    connection: sqlite3.Connection | None = None,
    only: str | None = None,
    mode: RunMode = RunMode.INCREMENTAL,
    dry_run: bool = False,
) -> RunReport:
    """Run across every configured source, or one named source (FR-042).

    ``mode`` defaults to INCREMENTAL — the safe direction. Nothing is ever withdrawn
    unless a caller deliberately asks for a sweep and the reader reports what it saw.
    """
    outcomes: list[Outcome] = []

    for status in report.statuses:
        kind_name = status.kind.name if status.kind else status.source.kind

        if only is not None and status.name != only:
            continue

        if status.readiness in _SKIP_REASONS:
            outcomes.append(
                Outcome(
                    status.name,
                    kind_name,
                    RunResult.SKIPPED,
                    detail=_SKIP_REASONS[status.readiness],
                )
            )
            continue

        if status.readiness in _FAILURE_FOR:
            blocking = next(
                (f.message for f in status.findings if f.blocks), "not usable"
            )
            outcomes.append(
                Outcome(
                    status.name,
                    kind_name,
                    RunResult.FAILED,
                    _FAILURE_FOR[status.readiness],
                    blocking,
                )
            )
            continue

        if dry_run:
            outcomes.append(
                Outcome(status.name, kind_name, RunResult.SKIPPED, detail="dry run")
            )
            continue

        outcomes.append(_ingest_one(status, store, connection, mode))

    return RunReport(tuple(outcomes))


def _record_correspondents(
    connection: sqlite3.Connection, records: Sequence[NormalizedRecord]
) -> None:
    """Register every address the records mention, with the role it appeared in.

    Driven by the records for the same reason `_record_repositories` is: a record carries
    what it was read under, so the index built from it cannot drift from what was stored,
    and rebuilding the store from scratch reproduces both.
    """
    from ..mail import correspondents

    for record in records:
        if record.payload.get("kind") != "mail_sent":
            continue
        if record.source_id is None:
            continue
        record_id = correspondents.record_id_for(connection, record.source_id)
        if record_id is None:
            continue
        correspondents.record_from_payload(connection, record_id, record.payload)


def _record_repositories(
    connection: sqlite3.Connection, records: Sequence[NormalizedRecord]
) -> None:
    """Register every repository the records came from.

    Deliberately driven by the records rather than by re-running discovery: a record
    carries the identity it was read under, so this cannot disagree with what was stored.
    """
    from ..projects import repository as projects_repo

    seen: dict[str, tuple[str, str | None, str]] = {}
    for record in records:
        identity = record.payload.get("repository")
        name = record.payload.get("repository_name")
        if isinstance(identity, str) and isinstance(name, str):
            root = record.payload.get("root_commit")
            where = record.payload.get("repository_path")
            seen.setdefault(
                identity,
                (
                    name,
                    root if isinstance(root, str) else None,
                    str(where) if isinstance(where, str) else identity,
                ),
            )

    for identity, (name, root, where) in seen.items():
        projects_repo.record_repository(
            connection,
            identity=identity,
            identity_kind="git_dir",
            name=name,
            path=Path(where),
            root_commit=root,
        )


def destinations(report: ValidationReport) -> tuple[tuple[str, str, str], ...]:
    """Every destination the configuration could contact, before anything is contacted.

    FR-045 and SC-010: Principle I made inspectable. The user can see their whole egress
    surface without granting anything or running an ingestion.
    """
    rows: list[tuple[str, str, str]] = []
    for status in report.statuses:
        kind_name = status.kind.name if status.kind else status.source.kind
        if not status.destinations:
            rows.append((status.name, kind_name, "none (local only)"))
        for destination in status.destinations:
            rows.append((status.name, kind_name, destination))
    return tuple(rows)
