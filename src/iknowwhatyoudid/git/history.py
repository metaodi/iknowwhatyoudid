"""Streaming commits and merges out of a repository (FR-010 to FR-017).

The format uses `\\x1f` as a field separator, which cannot occur in any field read, and
is parsed line by line so a decade of history is never materialised.

`rev-list --parents --pretty=format:` is deliberately **not** used: it was verified to
duplicate the hash and interleave the parent list into the formatted output — a parse
that looks correct on a small fixture and corrupts a real repository.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..records.model import NormalizedRecord
from . import binary

SEP = "\x1f"

#: %s is the SUBJECT ONLY. Never %b or %B: the body is where pasted logs, ticket text
#: and customer names accumulate, and FR-015 keeps it off disk.
FORMAT = SEP.join(("%H", "%P", "%an", "%ae", "%aI", "%cn", "%ce", "%cI", "%s"))


class ActivityKind(StrEnum):
    COMMIT = "commit"
    MERGE = "merge"
    BRANCH_CREATED = "branch_created"


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    authored: datetime
    committer_name: str
    committer_email: str
    committed: datetime
    subject: str

    @property
    def kind(self) -> ActivityKind:
        """A merge is a commit with two or more parents. Nothing is read from the message."""
        return ActivityKind.MERGE if len(self.parents) >= 2 else ActivityKind.COMMIT

    def mine(self, identities: Sequence[str]) -> str | None:
        """The declared identity this commit belongs to, if any (FR-011).

        Email is the key: names are inconsistent and get rewritten. Case-insensitive,
        because mail addresses are.
        """
        wanted = {identity.strip().casefold() for identity in identities if identity.strip()}
        for candidate in (self.author_email, self.committer_email):
            if candidate.casefold() in wanted:
                return candidate
        return None


def _parse(line: str) -> Commit | None:
    fields = line.split(SEP)
    if len(fields) < 9:
        return None
    sha, parents, an, ae, ai, cn, ce, ci, subject = fields[:9]
    try:
        authored = datetime.fromisoformat(ai)
        committed = datetime.fromisoformat(ci)
    except ValueError:
        return None
    return Commit(
        sha=sha.strip(),
        parents=tuple(p for p in parents.split() if p),
        author_name=an,
        author_email=ae,
        authored=authored,
        committer_name=cn,
        committer_email=ce,
        committed=committed,
        subject=subject,
    )


def commits(repository: Path, since: datetime | None = None) -> Iterator[Commit]:
    """Every commit reachable from every ref, newest first.

    `--all` rather than the current branch: work on a branch you have not merged is
    still work you did.
    """
    args = ["--all", "--no-decorate", f"--format={FORMAT}"]
    if since is not None:
        args.append(f"--since={since.isoformat()}")
    for line in binary.stream_lines(repository, "log", *args):
        parsed = _parse(line)
        if parsed is not None:
            yield parsed


def to_record(
    commit: Commit,
    *,
    repository_identity: str,
    repository_name: str,
    repository_path: str,
    root_commit: str | None,
    matched_identity: str,
) -> NormalizedRecord:
    """One commit as a store record.

    Author time is the record's time: FR-012 distinguishes work done from work landed,
    and "when I did it" is the timesheet-relevant one. A rebase weeks later would
    otherwise move a month of work to one afternoon.

    No duration is set (FR-016) and no zone name exists — git records an offset and
    never an IANA zone, so a daylight-saving repeated hour is genuinely unresolvable
    here, and the design does not pretend otherwise.
    """
    payload: dict[str, Any] = {
        "repository": repository_identity,
        "repository_name": repository_name,
        "repository_path": repository_path,
        "root_commit": root_commit,
        "kind": commit.kind.value,
        "sha": commit.sha,
        "parents": list(commit.parents),
        "parent_count": len(commit.parents),
        "committed": commit.committed.isoformat(),
        "matched_identity": matched_identity,
        "author_name": commit.author_name,
    }
    return NormalizedRecord(
        source_id=f"{commit.kind.value}:{commit.sha}",
        occurred=commit.authored,
        title=commit.subject,
        payload=payload,
        duration=None,
    )
