"""Projects, repositories, and the mapping between them (data-model.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def normalise(name: str) -> str:
    """The key uniqueness is enforced on.

    Case-folded and whitespace-collapsed, because FR-027 forbids two projects differing
    only in case — while the display name keeps whatever the user typed.
    """
    return " ".join(name.split()).casefold()


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    name: str
    normalised_name: str
    ad_hoc: bool
    first_seen_utc: int

    @property
    def label(self) -> str:
        """How a project is shown — an invented one always says so (FR-035)."""
        return f"{self.name}  (ad hoc)" if self.ad_hoc else self.name


@dataclass(frozen=True, slots=True)
class RepositoryPath:
    path: Path
    is_bare: bool = False
    is_worktree: bool = False


@dataclass(frozen=True, slots=True)
class Repository:
    """One repository, however many places it was found.

    A bare clone, a linked worktree and the original share a root commit and therefore
    one identity (verified, research R3). That is the right answer for a timesheet — the
    user worked on the repository, not on a checkout — so `paths` is a set rather than a
    single location.
    """

    id: int
    identity: str
    identity_kind: str
    name: str
    paths: tuple[RepositoryPath, ...] = ()
    first_seen_utc: int = 0
    last_seen_utc: int = 0

    @property
    def primary_path(self) -> Path | None:
        for candidate in self.paths:
            if not candidate.is_bare and not candidate.is_worktree:
                return candidate.path
        return self.paths[0].path if self.paths else None


@dataclass(frozen=True, slots=True)
class MappingEntry:
    """One `[[project]]` block from `projects.toml`."""

    project_name: str
    repositories: tuple[str, ...] = ()
    note: str | None = None
    index: int = 0
    line: int | None = None

    @property
    def key_path(self) -> str:
        return f"project[{self.index}]"


@dataclass(frozen=True, slots=True)
class Mapping:
    """The whole mapping file, parsed.

    An absent file is a valid `Mapping` with no entries (FR-030) — every repository then
    falls back to its own ad-hoc project, which is the state a new user starts in.
    """

    path: Path
    entries: tuple[MappingEntry, ...] = ()
    version: int = 1
    present: bool = True
    raw_text: str = ""
    _by_key: dict[str, str] = field(default_factory=dict, compare=False)

    def project_for(self, repository: Repository) -> str | None:
        """The declared project for *repository*, matched by name then by path.

        Name first: it is the common case and survives the repository moving. Path is
        there for when two repositories share a name.
        """
        by_name = self._by_key.get(normalise(repository.name))
        if by_name is not None:
            return by_name
        for candidate in repository.paths:
            found = self._by_key.get(normalise(str(candidate.path)))
            if found is not None:
                return found
        return None

    @property
    def project_names(self) -> tuple[str, ...]:
        return tuple(entry.project_name for entry in self.entries)


def build_index(entries: tuple[MappingEntry, ...]) -> dict[str, str]:
    """Repository key → project name, for `Mapping.project_for`."""
    index: dict[str, str] = {}
    for entry in entries:
        for repository in entry.repositories:
            expanded = str(Path(repository).expanduser())
            index.setdefault(normalise(repository), entry.project_name)
            index.setdefault(normalise(expanded), entry.project_name)
    return index
