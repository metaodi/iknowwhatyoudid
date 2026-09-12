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

from .. import addresses
from ..corrections import repository as corrections_repo
from ..records import timestamps
from ..store.connection import writing
from . import repository as projects_repo
from .model import Mapping, Repository


class Rule(StrEnum):
    # Repositories (0003)
    DECLARED = "mapping:declared"
    AD_HOC = "mapping:ad-hoc"
    # Mail (0004). Precedence lives in `model.RULE_PRECEDENCE`, not here.
    SUBJECT = "mapping:subject"
    CORRESPONDENT = "mapping:correspondent"
    CORRESPONDENT_DOMAIN = "mapping:correspondent-domain"
    AD_HOC_DOMAIN = "mapping:ad-hoc-domain"


#: Which rules mean "the tool guessed" rather than "the user said". Every view marks
#: these, so an assumption never reads as a decision (FR-041, SC-009).
AD_HOC_RULES = frozenset({Rule.AD_HOC, Rule.AD_HOC_DOMAIN})


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


def ad_hoc_domain(recipients: Sequence[str], own_domains: Sequence[str]) -> str | None:
    """The project name for a message no rule matched (FR-039).

    "Named after its recipients' domain" has no single answer when a message went to two
    organisations, so the rule is stated as an algorithm and asserted for determinism
    (SC-010b): the result depends only on the message, never on the order mail was read.

    1. take every recipient;
    2. discard any whose domain is one of the account's own;
    3. of those remaining, take the most frequent domain, breaking a tie alphabetically;
    4. if none remain — a message sent only to colleagues — use the account's own domain.
    """
    mine = {d.casefold() for d in own_domains if d}
    domains = [addresses.domain_of(a) for a in recipients if a]
    external = [d for d in domains if d and d.casefold() not in mine]

    if external:
        counts: dict[str, int] = {}
        for domain in external:
            counts[domain] = counts.get(domain, 0) + 1
        # Most frequent first; alphabetical breaks a tie, so the answer is stable.
        return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]

    if domains:
        return domains[0]
    return sorted(mine)[0] if mine else None


def project_for_message(
    mapping: Mapping,
    *,
    subject: str,
    recipients: Sequence[str],
    sender: str,
    own_domains: Sequence[str],
) -> tuple[str, Rule, str] | None:
    """Which project a message belongs to, which rule decided, and on what evidence.

    Exactly one project, as `0003` gives each commit exactly one. A genuinely shared
    message is filed under the winner and corrected by hand where that matters; the
    alternative — one message on several projects — would make every "how much time on
    Acme?" answer ambiguous about double-counting, and that ambiguity would reach a
    billing record.
    """
    candidates = [*recipients, sender]
    match = mapping.match_message(subject=subject, addresses=candidates)
    if match is not None:
        return match.project_name, Rule(match.rule.value), match.evidence

    fallback = ad_hoc_domain(recipients, own_domains)
    if fallback is None:
        return None
    return fallback, Rule.AD_HOC_DOMAIN, fallback


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
    to_write: list[tuple[int, int, Rule, dict[str, str]]] = []

    for row in _record_rows(connection):
        decision = _decide(row, mapping, repositories)
        if decision is None:
            continue
        name, rule, evidence = decision

        record_id = int(row["id"])
        if corrections_repo.get(connection, str(row["source"]), str(row["source_id"])):
            held += 1
            continue

        project = projects_repo.ensure_project(
            connection, name, ad_hoc=rule in AD_HOC_RULES, now=at
        )
        previous = existing.get(record_id)
        if previous is not None and previous[0] == project.id:
            unchanged += 1
        elif previous is not None:
            moved.append(
                Move(record_id, str(row["source_id"]), previous[1], project.name)
            )
        to_write.append((record_id, project.id, rule, evidence))

    with writing(connection):
        connection.execute("DELETE FROM derived_attribution")
        for record_id, project_id, rule, evidence in to_write:
            connection.execute(
                "INSERT INTO derived_attribution (record_id, project_id, rule, evidence, "
                "derived_at_utc) VALUES (?, ?, ?, ?, ?)",
                (
                    record_id,
                    project_id,
                    rule.value,
                    json.dumps({**evidence, "rule": rule.value}),
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


def _decide(
    row: sqlite3.Row,
    mapping: Mapping,
    repositories: dict[str, Repository],
) -> tuple[str, Rule, dict[str, str]] | None:
    """Which project this record belongs to, whatever kind of record it is.

    One function so that `attribute` and `preview` cannot drift apart — SC-013 requires
    the preview's predicted moves to match applying it exactly, and the cheapest way to
    guarantee that is to have one decision rather than two that look alike.
    """
    payload = _payload_of(row)
    kind = payload.get("kind")

    if kind == "mail_sent":
        raw_recipients = payload.get("recipients", [])
        recipients = [
            str(entry[0])
            for entry in (raw_recipients if isinstance(raw_recipients, list) else [])
            if isinstance(entry, list | tuple) and entry
        ]
        sender = str(payload.get("sent_by", ""))
        own_domains = [addresses.domain_of(sender)] if sender else []
        decided = project_for_message(
            mapping,
            subject=str(payload.get("subject", "")),
            recipients=recipients,
            sender=sender,
            own_domains=own_domains,
        )
        if decided is None:
            return None
        name, rule, evidence = decided
        return name, rule, {"matched": evidence, "account": str(payload.get("account", ""))}

    identity = _repository_of(row)
    if identity is None:
        return None
    repository = repositories.get(identity)
    if repository is None:
        return None
    name, rule = project_for_repository(mapping, repository)
    return name, rule, {"repository": identity}


def _payload_of(row: sqlite3.Row) -> dict[str, object]:
    try:
        loaded = json.loads(row["payload"])
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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
        # The same `_decide` the real thing uses. Two functions that looked alike would
        # drift, and SC-013 requires the preview to match applying it exactly.
        decision = _decide(row, mapping, repositories)
        if decision is None:
            continue
        record_id = int(row["id"])
        if corrections_repo.get(connection, str(row["source"]), str(row["source_id"])):
            held += 1
            continue

        total += 1
        name, _rule, _evidence = decision
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
