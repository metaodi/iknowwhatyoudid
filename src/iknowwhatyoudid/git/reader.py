"""The `SourceReader` for the `git.local` kind.

Read-only in the strongest sense: every git invocation goes through the allow-list in
`binary.py`, so there is no code path here that could modify a repository.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

from ..config import findings as f
from ..config.model import ConfiguredSource
from ..errors import GitReadError, GitUnavailableError
from ..kinds.spec import CredentialHandle, LiveCheckResult
from ..records.model import NormalizedRecord, RunMode
from . import binary, discovery, history, identity, refs
from .identity import RepositoryFacts

GIT_UNAVAILABLE = "git-unavailable"
REPOSITORY_UNREADABLE = "repository-unreadable"


def _locations(source: ConfiguredSource) -> tuple[list[str], list[str]]:
    raw = source.settings.get("paths", [])
    paths = [str(item) for item in raw] if isinstance(raw, list) else []
    raw_exclude = source.settings.get("exclude", [])
    excluded = [str(item) for item in raw_exclude] if isinstance(raw_exclude, list) else []
    return paths, excluded


def _identities(source: ConfiguredSource) -> list[str]:
    raw = source.settings.get("identities", [])
    return [str(item) for item in raw] if isinstance(raw, list) else []


def discover_for(source: ConfiguredSource) -> discovery.Discovered:
    paths, excluded = _locations(source)
    return discovery.discover(paths, excluded, source_name=source.name)


class GitReader:
    """Reads local git repositories. Never writes to one."""

    def __init__(self) -> None:
        self._skipped: list[str] = []

    def drain_skips(self) -> Sequence[str]:
        """Every repository skipped since the last call (FR-007, FR-020, SC-011)."""
        skipped = tuple(self._skipped)
        self._skipped.clear()
        return skipped

    def validate(self, source: ConfiguredSource) -> Sequence[f.Finding]:
        """Offline: checks git is usable and the locations resolve. Reads no history."""
        problems: list[f.Finding] = []
        try:
            binary.require_supported_git()
        except GitUnavailableError as exc:
            problems.append(
                f.blocking(
                    GIT_UNAVAILABLE,
                    exc.message,
                    source_name=source.name,
                    key_path=source.setting_path("kind"),
                    remedy=exc.remedy,
                )
            )
            return problems

        # Locations only — never a recursive walk. `sources validate` must stay fast.
        paths, _excluded = _locations(source)
        problems.extend(discovery.check_locations(paths, source_name=source.name))
        return problems

    def check_live(
        self, source: ConfiguredSource, credential: CredentialHandle | None
    ) -> LiveCheckResult:
        """Confirm the repositories are readable. Still reads no commit history."""
        try:
            version = binary.require_supported_git()
        except GitUnavailableError as exc:
            return LiveCheckResult(False, exc.message)

        found = discover_for(source)
        if not found.repositories:
            return LiveCheckResult(False, "no repositories matched")
        return LiveCheckResult(
            True, f"git {version}, {found.count} repositories readable (local only)"
        )

    def read(
        self,
        source: ConfiguredSource,
        credential: CredentialHandle | None,
        since: datetime | None,
        mode: RunMode,
    ) -> Iterator[NormalizedRecord]:
        """Yield one record per commit, merge and branch creation that is the user's.

        One repository failing never stops the others (FR-007): it is reported through
        the run's diagnostics and skipped. A repository the user believes is being read
        but is not produces a gap in a timesheet that nobody checks.
        """
        binary.require_supported_git()
        identities = _identities(source)
        found = discover_for(source)

        for facts in found.repositories:
            try:
                yield from self._read_one(facts, identities, since, mode)
            except GitReadError as exc:
                # Named in the run's report, never swallowed: a repository the user
                # believes is being read but is not produces a gap in a timesheet that
                # nobody checks.
                self._skipped.append(f"{facts.path}: {exc}")
                continue

    def _read_one(
        self,
        facts: RepositoryFacts,
        identities: Sequence[str],
        since: datetime | None,
        mode: RunMode,
    ) -> Iterator[NormalizedRecord]:
        # Discovery deliberately leaves this unset, because finding it walks the whole
        # commit graph. This is the point where reading history is what we came to do,
        # and it costs one walk per repository rather than one per candidate directory.
        root = identity.root_commit(facts.path) if facts.has_commits else None

        if facts.has_commits:
            for commit in history.commits(facts.path, since):
                matched = commit.mine(identities)
                if matched is None:
                    continue
                yield history.to_record(
                    commit,
                    repository_identity=facts.identity,
                    repository_name=facts.name,
                    repository_path=str(facts.path),
                    root_commit=root,
                    matched_identity=matched,
                )

        # Branch creations come from the reflog, which is local and expires. They are
        # yielded as records but never enter a sweep's seen set, so their disappearance
        # can never be read as the branch having been deleted (research R2).
        for event in refs.created_branches(facts.path):
            if identities and not refs.mine(event, identities):
                continue
            yield refs.to_record(
                event,
                repository_identity=facts.identity,
                repository_name=facts.name,
                repository_path=str(facts.path),
                root_commit=root,
            )


def withdrawable_ids(records: Sequence[NormalizedRecord]) -> frozenset[str]:
    """The seen set for a sweep — commits and merges only.

    A branch creation is deliberately excluded. Ninety days after it happened the reflog
    entry expires; if it were in the seen set, the next sweep would not find it and would
    mark a real event withdrawn.
    """
    seen: set[str] = set()
    for record in records:
        if record.payload.get("withdrawable") is False:
            continue
        if record.source_id:
            seen.add(record.source_id)
    return frozenset(seen)


def repository_paths(source: ConfiguredSource) -> list[Path]:
    return [facts.path for facts in discover_for(source).repositories]
