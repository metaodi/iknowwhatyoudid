"""Branches, and best-effort branch creation (FR-010, research R2).

**Branch creation is not in git's object model.** `for-each-ref` gives a branch's tip
commit date and nothing about when the branch came into existence. The event exists only
in the reflog — which is *local* (never transferred by clone) and *expires* after 90 days
by default.

That has one consequence the rest of the system must honour: a branch creation is
**never withdrawn**. If it were treated like a commit, then ninety days after creating a
branch the reflog entry would expire, an exhaustive read would not see it, and the tool
would mark an event that genuinely happened as withdrawn — a retention policy reported as
data loss, in the record that feeds a timesheet.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..records.model import NormalizedRecord
from . import binary
from .history import ActivityKind

#: A reflog entry whose "from" hash is all zeros is a creation, not an update.
_ZERO = "0" * 40


@dataclass(frozen=True, slots=True)
class Branch:
    name: str
    tip: str


@dataclass(frozen=True, slots=True)
class BranchCreated:
    branch: str
    created: datetime
    tip: str
    by_email: str
    index: int


def branches(repository: Path) -> list[Branch]:
    lines = binary.run_lines(
        repository, "for-each-ref", "--format=%(refname:short)\x1f%(objectname)", "refs/heads"
    )
    found: list[Branch] = []
    for line in lines:
        parts = line.split("\x1f")
        if len(parts) == 2:
            found.append(Branch(parts[0], parts[1]))
    return found


def _parse_reflog_line(line: str) -> tuple[str, datetime, str, str] | None:
    """`<old> <new> <name> <email> <epoch> <offset>\\t<message>`"""
    if "\t" not in line:
        return None
    head, message = line.split("\t", 1)
    parts = head.split()
    if len(parts) < 5:
        return None
    old, new = parts[0], parts[1]
    try:
        epoch = int(parts[-2])
        offset = parts[-1]
    except (ValueError, IndexError):
        return None

    email = ""
    for token in parts[2:-2]:
        if token.startswith("<") and token.endswith(">"):
            email = token[1:-1]
    try:
        sign = 1 if offset.startswith("+") else -1
        hours, minutes = int(offset[1:3]), int(offset[3:5])
        tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
    except (ValueError, IndexError):
        tz = UTC
    return old + ":" + new, datetime.fromtimestamp(epoch, tz=tz), email, message.strip()


def created_branches(repository: Path) -> Iterator[BranchCreated]:
    """Branch creations, where the reflog still holds the evidence.

    A freshly cloned repository yields nothing here, however old its branches are. That
    is a property of git, not a defect, and the tool says so rather than presenting a
    partial branch history as complete.
    """
    logs = repository / ".git" / "logs" / "refs" / "heads"
    if not logs.is_dir():
        return
    for index, log in enumerate(sorted(logs.rglob("*"))):
        if not log.is_file():
            continue
        branch = log.relative_to(logs).as_posix()
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for entry_index, line in enumerate(text.splitlines()):
            parsed = _parse_reflog_line(line)
            if parsed is None:
                continue
            hashes, when, email, message = parsed
            old, new = hashes.split(":", 1)
            if old == _ZERO and message.lower().startswith("branch: created"):
                yield BranchCreated(branch, when, new, email, entry_index)


def to_record(
    event: BranchCreated,
    *,
    repository_identity: str,
    repository_name: str,
    repository_path: str,
    root_commit: str | None,
) -> NormalizedRecord:
    payload: dict[str, Any] = {
        "repository": repository_identity,
        "repository_name": repository_name,
        "repository_path": repository_path,
        "root_commit": root_commit,
        "kind": ActivityKind.BRANCH_CREATED.value,
        "branch": event.branch,
        "tip": event.tip,
        "matched_identity": event.by_email,
        # Read from the reflog, which is local and expires. Carried on the record so a
        # later reader knows this evidence is inherently incomplete.
        "evidence": "reflog",
        "withdrawable": False,
    }
    return NormalizedRecord(
        source_id=(
            f"{ActivityKind.BRANCH_CREATED.value}:{repository_identity}:"
            f"{event.branch}:{event.index}"
        ),
        occurred=event.created,
        title=f"created branch {event.branch}",
        payload=payload,
        duration=None,
    )


def mine(event: BranchCreated, identities: Sequence[str]) -> bool:
    wanted = {identity.strip().casefold() for identity in identities if identity.strip()}
    return event.by_email.casefold() in wanted
