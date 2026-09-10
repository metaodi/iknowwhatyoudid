"""Attributing activity to projects (FR-032 to FR-042).

This module must never read a repository. FR-037 requires that changing the mapping and
re-deriving reads nothing from any source, and that is enforced by the package boundary
rather than by intention: nothing under `projects/` imports `git/`, `subprocess` or
`socket`, and a test asserts it. Re-derivation therefore *cannot* regress into reading a
repository, because it has no way to.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..corrections import repository as corrections_repo
from ..records import timestamps
from ..store.connection import writing
from . import repository as projects_repo
from .model import Mapping, Repository


class Rule(StrEnum):
    DECLARED = "mapping:declared"
    AD_HOC = "mapping:ad-hoc"


@dataclass(frozen=True, slots=True)
class Move:
    """One activity changing project during a re-derivation."""

    record_id: int
    source_id: str
    from_project: str | None
    to_project: str


@dataclass(frozen=True, slots=True)
class RederiveReport:
    moved: tuple[Move, ...] = ()
    unchanged: int = 0
    held_by_correction: int = 0
    pruned_ad_hoc: tuple[str, ...] = ()
    total: int = 0

    @property
    def move_summary(self) -> dict[tuple[str | None, str], int]:
        counts: dict[tuple[str | None, str], int] = {}
        for move in self.moved:
            key = (move.from_project, move.to_project)
            counts[key] = counts.get(key, 0) + 1
        return counts


def project_for_repository(
    mapping: Mapping, repository: Repository
) -> tuple[str, Rule]:
    """Which project a repository's activity belongs to, and why.

    Declared mapping first; otherwise the repository's own name, so nothing is left
    unattributed (FR-034). Both record which rule fired, so a user can always see *why*
    a piece of work landed where it did.
    """
    declared = mapping.project_for(repository)
    if declared is not None:
        return declared, Rule.DECLARED
    return repository.name, Rule.AD_HOC


def _record_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT id, source, source_id, payload FROM raw_record ORDER BY id"
    ).fetchall()


def _repository_of(row: sqlite3.Row) -> str | None:
    try:
        payload = json.loads(row["payload"])
    except (TypeError, ValueError):
        return None
    identity = payload.get("repository")
    return str(identity) if identity else None


def attribute(
    connection: sqlite3.Connection,
    mapping: Mapping,
    *,
    now: int | None = None,
) -> RederiveReport:
    """Apply the mapping to every record that has a repository.

    A `user_correction` wins over whatever the mapping says (FR-038): the mapping is a
    rule, a correction is the user's statement, and a rule never overrides a statement.
    """
    at = timestamps.now_micros() if now is None else now
    repositories = {r.identity: r for r in projects_repo.list_repositories(connection)}

    # Every declared project exists as soon as it is declared, even with no repositories
    # and no activity. The user said it exists; a project only appearing once something
    # lands on it would make an empty one indistinguishable from a typo.
    for entry in mapping.entries:
        projects_repo.ensure_project(connection, entry.project_name, ad_hoc=False, now=at)

    existing: dict[int, tuple[int, str]] = {
        int(row["record_id"]): (int(row["project_id"]), str(row["name"]))
        for row in connection.execute(
            "SELECT d.record_id, d.project_id, p.name FROM derived_attribution d "
            "JOIN user_project p ON p.id = d.project_id"
        )
    }

    moved: list[Move] = []
    unchanged = 0
    held = 0
    to_write: list[tuple[int, int, Rule, str]] = []

    for row in _record_rows(connection):
        identity = _repository_of(row)
        if identity is None:
            continue
        repository = repositories.get(identity)
        if repository is None:
            continue

        record_id = int(row["id"])
        if corrections_repo.get(connection, str(row["source"]), str(row["source_id"])):
            held += 1
            continue

        name, rule = project_for_repository(mapping, repository)
        project = projects_repo.ensure_project(
            connection, name, ad_hoc=rule is Rule.AD_HOC, now=at
        )
        previous = existing.get(record_id)
        if previous is not None and previous[0] == project.id:
            unchanged += 1
        elif previous is not None:
            moved.append(
                Move(record_id, str(row["source_id"]), previous[1], project.name)
            )
        to_write.append((record_id, project.id, rule, identity))

    with writing(connection):
        connection.execute("DELETE FROM derived_attribution")
        for record_id, project_id, rule, identity in to_write:
            connection.execute(
                "INSERT INTO derived_attribution (record_id, project_id, rule, evidence, "
                "derived_at_utc) VALUES (?, ?, ?, ?, ?)",
                (
                    record_id,
                    project_id,
                    rule.value,
                    json.dumps({"repository": identity, "rule": rule.value}),
                    at,
                ),
            )

    pruned = _prune_and_name(connection)
    return RederiveReport(
        moved=tuple(moved),
        unchanged=unchanged,
        held_by_correction=held,
        pruned_ad_hoc=pruned,
        total=len(to_write),
    )


def _prune_and_name(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Drop ad-hoc projects that now hold nothing, reporting which (FR-040)."""
    rows = connection.execute(
        "SELECT name FROM user_project WHERE ad_hoc = 1 AND id NOT IN "
        "(SELECT DISTINCT project_id FROM derived_attribution)"
    ).fetchall()
    names = tuple(str(row["name"]) for row in rows)
    if names:
        projects_repo.prune_empty_ad_hoc(connection)
    return names


def preview(connection: sqlite3.Connection, mapping: Mapping) -> RederiveReport:
    """What `attribute` would do, without doing it (FR-041).

    Runs the same decision for every record and reports the moves, then rolls nothing
    forward — so the preview cannot drift from what applying it does (SC-012).
    """
    repositories = {r.identity: r for r in projects_repo.list_repositories(connection)}
    current: dict[int, str] = {
        int(row["record_id"]): str(row["name"])
        for row in connection.execute(
            "SELECT d.record_id, p.name FROM derived_attribution d "
            "JOIN user_project p ON p.id = d.project_id"
        )
    }

    moved: list[Move] = []
    unchanged = 0
    held = 0
    total = 0
    would_hold: set[str] = set()

    for row in _record_rows(connection):
        identity = _repository_of(row)
        if identity is None:
            continue
        repository = repositories.get(identity)
        if repository is None:
            continue
        record_id = int(row["id"])
        if corrections_repo.get(connection, str(row["source"]), str(row["source_id"])):
            held += 1
            continue

        total += 1
        name, _rule = project_for_repository(mapping, repository)
        would_hold.add(name)
        previous = current.get(record_id)
        if previous == name:
            unchanged += 1
        elif previous is not None:
            moved.append(Move(record_id, str(row["source_id"]), previous, name))

    emptied = tuple(
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM user_project WHERE ad_hoc = 1"
        ).fetchall()
        if str(row["name"]) not in would_hold
    )

    return RederiveReport(
        moved=tuple(moved),
        unchanged=unchanged,
        held_by_correction=held,
        pruned_ad_hoc=emptied,
        total=total,
    )


def rederive(
    connection: sqlite3.Connection, mapping: Mapping, *, dry_run: bool = False
) -> RederiveReport:
    """Re-apply the mapping to activity already recorded (FR-037).

    Reads no repository and opens no socket — structurally, not by intention.
    """
    if dry_run:
        return preview(connection, mapping)
    return attribute(connection, mapping)


def repositories_for_project(
    connection: sqlite3.Connection, project_id: int
) -> Sequence[str]:
    rows = connection.execute(
        """
        SELECT DISTINCT json_extract(r.payload, '$.repository_name') AS name
        FROM derived_attribution d
        JOIN raw_record r ON r.id = d.record_id
        WHERE d.project_id = ? AND name IS NOT NULL
        ORDER BY name
        """,
        (project_id,),
    ).fetchall()
    return [str(row["name"]) for row in rows]
