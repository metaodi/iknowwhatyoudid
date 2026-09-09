"""The portable correction file (FR-018, FR-032 to FR-034).

JSON Lines. Identity is ``(source, source_id)`` rather than any internal id, because the
target store's ids are different — after a rebuild even the *source* store's ids are
different. ``made_at`` is always UTC: it is used to compare corrections made on different
machines, and two machines in different zones must order them consistently.

See specs/0001-local-store-foundation/contracts/corrections-file.md.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from ..errors import IkwydError
from ..records.timestamps import MICROSECONDS
from ..store.connection import writing
from . import repository
from .model import Correction, ImportDecision, ImportOutcome, ImportReport

FORMAT_VERSION = 1


def _to_iso(micros: int) -> str:
    return (
        datetime.fromtimestamp(micros / MICROSECONDS, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _from_iso(text: str) -> int:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise IkwydError(f"made_at {text!r} has no time zone")
    return int(moment.timestamp() * MICROSECONDS)


def to_line(correction: Correction) -> str:
    return json.dumps(
        {
            "v": FORMAT_VERSION,
            "source": correction.source,
            "source_id": correction.source_id,
            "project": correction.project,
            "note": correction.note,
            "made_at": _to_iso(correction.made_at_utc),
        },
        ensure_ascii=False,
    )


def from_line(line: str) -> Correction:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise IkwydError(f"not a correction line: {exc}") from exc

    version = payload.get("v")
    if version != FORMAT_VERSION:
        raise IkwydError(
            f"correction file format v{version} is not supported (this tool writes "
            f"v{FORMAT_VERSION})"
        )
    for required in ("source", "source_id", "made_at"):
        if required not in payload:
            raise IkwydError(f"correction line is missing {required!r}")

    return Correction(
        source=str(payload["source"]),
        source_id=str(payload["source_id"]),
        project=payload.get("project"),
        note=payload.get("note"),
        made_at_utc=_from_iso(str(payload["made_at"])),
    )


def export(connection: sqlite3.Connection) -> Iterator[str]:
    for correction in repository.all_corrections(connection):
        yield to_line(correction)


def parse(lines: Iterable[str]) -> list[Correction]:
    found: list[Correction] = []
    for number, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text:
            continue
        try:
            found.append(from_line(text))
        except IkwydError as exc:
            raise IkwydError(f"line {number}: {exc}") from exc
    return found


def import_corrections(
    connection: sqlite3.Connection,
    incoming: Iterable[Correction],
    *,
    dry_run: bool = False,
) -> ImportReport:
    """Merge corrections, newest-wins by ``made_at`` (FR-033).

    Equal times keep the local correction — an arbitrary but deterministic tie-break, and
    the conservative direction: it never displaces something on the strength of a tie.

    Every replacement *and* every refusal is recorded in the report (FR-034). Newest-wins
    is only as trustworthy as the clocks involved, so the guarantee this can actually make
    is the weaker, honest one: nothing is replaced silently.

    The whole import is one transaction: it applies fully or not at all.
    """
    decisions: list[ImportDecision] = []
    to_write: list[tuple[Correction, bool]] = []

    for correction in incoming:
        existing = repository.get(connection, correction.source, correction.source_id)
        if existing is None:
            pending = not repository._record_exists(
                connection, correction.source, correction.source_id
            )
            outcome = ImportOutcome.PENDING if pending else ImportOutcome.NEW
            decisions.append(ImportDecision(outcome, correction))
            to_write.append((correction, pending))
            continue

        if correction.made_at_utc > existing.made_at_utc:
            pending = not repository._record_exists(
                connection, correction.source, correction.source_id
            )
            decisions.append(
                ImportDecision(ImportOutcome.REPLACED, correction, existing)
            )
            to_write.append((correction, pending))
        else:
            decisions.append(
                ImportDecision(ImportOutcome.DECLINED, correction, existing)
            )

    if not dry_run and to_write:
        with writing(connection):
            for correction, pending in to_write:
                connection.execute(
                    "INSERT INTO user_correction (source, source_id, project, note, "
                    "made_at_utc, pending) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(source, source_id) DO UPDATE SET "
                    "  project = excluded.project, note = excluded.note, "
                    "  made_at_utc = excluded.made_at_utc, pending = excluded.pending",
                    (
                        correction.source,
                        correction.source_id,
                        correction.project,
                        correction.note,
                        correction.made_at_utc,
                        int(pending),
                    ),
                )

    return ImportReport(tuple(decisions))
