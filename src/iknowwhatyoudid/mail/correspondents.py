"""Recording who a message was sent to (FR-031, FR-054).

Addresses are lifted out of the payload into their own tables because they are
*queried*: "which correspondents contribute most to this project" is a group-by, and
answering it by parsing every record's JSON would be slow and impossible to index.

`bcc` is never recorded. It names people the other recipients were not told about, it is
the most sensitive field in a header, and attribution has no use for it — the schema has
no role for it either, so this is enforced rather than remembered.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..records import timestamps
from .. import addresses as addr
from .message import Message, Role


@dataclass(frozen=True, slots=True)
class Correspondent:
    id: int
    address: str
    domain: str
    display_name: str | None


def ensure(
    connection: sqlite3.Connection,
    address: str,
    *,
    display_name: str | None = None,
    now: int | None = None,
) -> int:
    """The id for an address, inserting it the first time it is seen.

    The address is normalised before it gets here, so the table's UNIQUE constraint does
    the deduplicating rather than a query having to.
    """
    at = timestamps.now_micros() if now is None else now
    normalised = addr.normalise(address)
    row = connection.execute(
        "SELECT id FROM raw_correspondent WHERE address = ?", (normalised,)
    ).fetchone()
    if row is not None:
        if display_name:
            # The most recently seen name wins. It is shown to a person and never used
            # for matching — a display name is set by whoever sent the message.
            connection.execute(
                "UPDATE raw_correspondent SET display_name = ? WHERE id = ?",
                (display_name, int(row["id"])),
            )
        return int(row["id"])

    cursor = connection.execute(
        "INSERT INTO raw_correspondent (address, display_name, domain, first_seen_utc) "
        "VALUES (?, ?, ?, ?)",
        (normalised, display_name, addr.domain_of(normalised), at),
    )
    return int(cursor.lastrowid or 0)


def link(connection: sqlite3.Connection, record_id: int, message: Message) -> int:
    """Record every address on a message, with the role it appeared in.

    A broadcast to fifty people is fifty rows, deliberately: a correspondent rule matches
    when an address appears in *any* role, and truncating the list would hide that this
    was a broadcast rather than an exchange.
    """
    now = timestamps.now_micros()
    written = 0

    pairs: list[tuple[str, Role]] = [(message.sender, Role.SENDER)]
    pairs.extend((r.address, r.role) for r in message.recipients)

    for address, role in pairs:
        if not address:
            continue
        correspondent = ensure(
            connection, address, display_name=message.display_names.get(address), now=now
        )
        connection.execute(
            "INSERT OR IGNORE INTO raw_record_correspondent "
            "(record_id, correspondent_id, role) VALUES (?, ?, ?)",
            (record_id, correspondent, role.value),
        )
        written += 1
    return written


def record_from_payload(
    connection: sqlite3.Connection, record_id: int, payload: Mapping[str, Any]
) -> int:
    """Build a record's correspondent rows from what it stored.

    Taking the addresses from the payload rather than from a `Message` keeps this usable
    from `sources/run.py`, which is deliberately source-agnostic, and means re-deriving
    the index never needs a provider.
    """
    now = timestamps.now_micros()
    written = 0

    names_raw = payload.get("display_names")
    names = names_raw if isinstance(names_raw, dict) else {}

    pairs: list[tuple[str, str]] = []
    sender = payload.get("sent_by")
    if isinstance(sender, str) and sender:
        pairs.append((sender, Role.SENDER.value))

    raw = payload.get("recipients")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, list | tuple) and len(entry) == 2:
                address, role = str(entry[0]), str(entry[1])
                if address and role in {Role.TO.value, Role.CC.value}:
                    pairs.append((address, role))

    for address, role in pairs:
        display = names.get(address)
        correspondent = ensure(
            connection,
            address,
            display_name=str(display) if isinstance(display, str) else None,
            now=now,
        )
        connection.execute(
            "INSERT OR IGNORE INTO raw_record_correspondent "
            "(record_id, correspondent_id, role) VALUES (?, ?, ?)",
            (record_id, correspondent, role),
        )
        written += 1
    return written


def record_id_for(connection: sqlite3.Connection, source_id: str) -> int | None:
    row = connection.execute(
        "SELECT id FROM raw_record WHERE source_id = ?", (source_id,)
    ).fetchone()
    return int(row["id"]) if row is not None else None


def for_record(connection: sqlite3.Connection, record_id: int) -> list[tuple[str, str]]:
    """`(address, role)` for one message, in a stable order."""
    rows = connection.execute(
        "SELECT c.address, rc.role FROM raw_record_correspondent rc "
        "JOIN raw_correspondent c ON c.id = rc.correspondent_id "
        "WHERE rc.record_id = ? ORDER BY rc.role, c.address",
        (record_id,),
    ).fetchall()
    return [(str(row["address"]), str(row["role"])) for row in rows]


def recipients_of(connection: sqlite3.Connection, record_id: int) -> list[str]:
    """Only the recipients — what the ad-hoc domain fallback counts (FR-039)."""
    rows = connection.execute(
        "SELECT c.address FROM raw_record_correspondent rc "
        "JOIN raw_correspondent c ON c.id = rc.correspondent_id "
        "WHERE rc.record_id = ? AND rc.role IN ('to','cc') ORDER BY c.address",
        (record_id,),
    ).fetchall()
    return [str(row["address"]) for row in rows]


@dataclass(frozen=True, slots=True)
class Contribution:
    address: str
    domain: str
    display_name: str | None
    project: str | None
    project_is_ad_hoc: bool
    messages: int
    last_seen_utc: int


def contributions(
    connection: sqlite3.Connection, *, project: str | None = None
) -> list[Contribution]:
    """Who contributes most to a project (FR-054).

    The point of this query is the *unmapped* rows it returns: a correspondent sitting in
    an ad-hoc project is a mapping that has not been written yet, and seeing them ranked
    is how that becomes discoverable rather than something to guess at.
    """
    clause = "AND p.name = ?" if project else ""
    params: tuple[object, ...] = (project,) if project else ()
    rows = connection.execute(
        f"""
        SELECT c.address           AS address,
               c.domain            AS domain,
               c.display_name      AS display_name,
               p.name              AS project,
               p.ad_hoc            AS ad_hoc,
               count(*)            AS messages,
               max(r.occurred_utc) AS last_seen
        FROM raw_record_correspondent rc
        JOIN raw_correspondent c ON c.id = rc.correspondent_id
        JOIN raw_record r        ON r.id = rc.record_id
        LEFT JOIN derived_attribution d ON d.record_id = r.id
        LEFT JOIN user_project p        ON p.id = d.project_id
        -- The sender is always the user, and nobody needs telling they corresponded with
        -- themselves. The role is still stored, because FR-021 asks which of several own
        -- addresses sent a message; it is just not a *correspondent*.
        WHERE rc.role IN ('to', 'cc')
        {clause}
        GROUP BY c.address, p.name
        ORDER BY messages DESC, c.address
        """,  # noqa: S608 — `clause` is one of two literals above
        params,
    ).fetchall()
    return [
        Contribution(
            address=str(row["address"]),
            domain=str(row["domain"]),
            display_name=row["display_name"],
            project=row["project"],
            project_is_ad_hoc=bool(row["ad_hoc"]),
            messages=int(row["messages"]),
            last_seen_utc=int(row["last_seen"]),
        )
        for row in rows
    ]


def counts_by_project(connection: sqlite3.Connection) -> dict[int, int]:
    """Project id → how many distinct correspondents contribute to it.

    Shown beside the repository count in `projects list`, so a project fed by mail is as
    visible as one fed by commits. A project with no repositories and forty
    correspondents is not empty; it just is not a coding project.
    """
    rows = connection.execute(
        """
        SELECT d.project_id AS project_id, count(DISTINCT rc.correspondent_id) AS people
        FROM derived_attribution d
        JOIN raw_record_correspondent rc ON rc.record_id = d.record_id
        WHERE rc.role IN ('to', 'cc')
        GROUP BY d.project_id
        """
    ).fetchall()
    return {int(row["project_id"]): int(row["people"]) for row in rows}
