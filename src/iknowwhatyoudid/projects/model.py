"""Projects, repositories, and the mapping between them (data-model.md)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
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
    correspondents: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    note: str | None = None
    index: int = 0
    line: int | None = None

    @property
    def key_path(self) -> str:
        return f"project[{self.index}]"

    @property
    def addresses(self) -> tuple[str, ...]:
        """Correspondent entries that name one address."""
        return tuple(c for c in self.correspondents if "@" in c)

    @property
    def domains(self) -> tuple[str, ...]:
        """Correspondent entries that name a whole domain."""
        return tuple(c for c in self.correspondents if "@" not in c)


class MailRule(StrEnum):
    """Why a message landed where it did, and in what order the rules were tried.

    The order is the point. A **subject** rule beats a **correspondent** rule because a
    subject is a statement about *this message*, while a correspondent is a statement
    about a person who may work on several things. An **address** rule beats a **domain**
    rule regardless of declaration order, because any other choice would let a broad
    domain rule declared early make every precise rule below it unreachable — the kind of
    silent shadowing that is very hard to notice in a billing record.
    """

    SUBJECT = "mapping:subject"
    CORRESPONDENT = "mapping:correspondent"
    CORRESPONDENT_DOMAIN = "mapping:correspondent-domain"
    AD_HOC_DOMAIN = "mapping:ad-hoc-domain"


#: Lower sorts first, and first wins. Ties are broken by declaration order in the file,
#: which makes the outcome a property of the text rather than of the order mail was read
#: in (SC-010b).
RULE_PRECEDENCE: dict[MailRule, int] = {
    MailRule.SUBJECT: 1,
    MailRule.CORRESPONDENT: 2,
    MailRule.CORRESPONDENT_DOMAIN: 3,
    MailRule.AD_HOC_DOMAIN: 4,
}


@dataclass(frozen=True, slots=True)
class Match:
    """One rule firing: which project, why, and on what evidence."""

    project_name: str
    rule: MailRule
    evidence: str
    declaration_index: int = 0

    @property
    def rank(self) -> tuple[int, int]:
        return (RULE_PRECEDENCE[self.rule], self.declaration_index)


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

    # --- mail --------------------------------------------------------------------------

    def match_message(self, *, subject: str, addresses: Sequence[str]) -> Match | None:
        """The one project a message belongs to, or None if no rule fires.

        Every matching rule is collected and the best-ranked one wins, rather than
        returning at the first hit. Collecting is what makes the result independent of
        the order the entries happen to be walked in, and it is also what lets the winner
        be *reported* — FR-037 asks which rule won, which only means something if there
        was a contest.
        """
        candidates: list[Match] = []
        lowered_subject = subject.casefold()
        normalised = [a.casefold().strip() for a in addresses if a]

        for entry in self.entries:
            for text in entry.subjects:
                if text and text.casefold() in lowered_subject:
                    candidates.append(
                        Match(entry.project_name, MailRule.SUBJECT, text, entry.index)
                    )
            for address in entry.addresses:
                if address.casefold() in normalised:
                    candidates.append(
                        Match(
                            entry.project_name,
                            MailRule.CORRESPONDENT,
                            address,
                            entry.index,
                        )
                    )
            for domain in entry.domains:
                if any(_domain_matches(domain, a) for a in normalised):
                    candidates.append(
                        Match(
                            entry.project_name,
                            MailRule.CORRESPONDENT_DOMAIN,
                            domain,
                            entry.index,
                        )
                    )

        if not candidates:
            return None
        return min(candidates, key=lambda m: m.rank)


def _domain_matches(rule: str, address: str) -> bool:
    """Suffix matching on **domain labels**, not on characters.

    `acme.example` matches `anna@acme.example` and `bob@mail.acme.example`, and must not
    match `eve@notacme.example` — which a plain `endswith` would.
    """
    _, _, domain = address.partition("@")
    if not domain:
        return False
    wanted = rule.casefold().strip(".").split(".")
    have = domain.casefold().strip(".").split(".")
    return len(have) >= len(wanted) and have[-len(wanted):] == wanted


def build_index(entries: tuple[MappingEntry, ...]) -> dict[str, str]:
    """Repository key → project name, for `Mapping.project_for`."""
    index: dict[str, str] = {}
    for entry in entries:
        for repository in entry.repositories:
            expanded = str(Path(repository).expanduser())
            index.setdefault(normalise(repository), entry.project_name)
            index.setdefault(normalise(expanded), entry.project_name)
    return index
