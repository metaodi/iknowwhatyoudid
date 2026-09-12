"""Reading and validating `projects.toml` (FR-028 to FR-031, FR-042).

Kept out of `config.toml` because `0002` FR-041 rejects a project mapping there. That
separation is not bureaucratic: attribution rules change often and are expected to be
wrong at first, and a bad rule must not be able to break the configuration that says
where to read from.

`tomllib` is read-only by construction, so FR-029's "never rewritten" has no code path
to violate.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from pathlib import Path

from ..config import findings as f
from .. import addresses
from ..config.loader import _POSITION  # the same located-parse-error treatment
from ..errors import ConfigParseError
from ..protection import permissions
from .model import Mapping, MappingEntry, Repository, build_index, normalise

TOP_LEVEL_KEYS = frozenset({"version", "project"})
ENTRY_KEYS = frozenset({"name", "repositories", "correspondents", "subjects", "note"})

DUPLICATE_PROJECT_NAME = "duplicate-project-name"
#: A correspondent entry that can never match is a typo, not an intention.
MALFORMED_CORRESPONDENT = "mapping-correspondent-malformed"

#: An empty subject rule would match every message ever sent.
EMPTY_SUBJECT_RULE = "mapping-subject-empty"

#: Two projects claiming the same address, domain or subject: genuinely ambiguous, and
#: the user has to choose. Guessing would put billable work on the wrong line.
DUPLICATE_CORRESPONDENT = "mapping-correspondent-claimed-twice"
DUPLICATE_SUBJECT = "mapping-subject-claimed-twice"

#: A rule that matches nothing yet. A warning, never an error: mapping a colleague before
#: they mail you is entirely reasonable.
CORRESPONDENT_MATCHES_NOTHING = "mapping-correspondent-matches-nothing"
SUBJECT_MATCHES_NOTHING = "mapping-subject-matches-nothing"

INVALID_PROJECT_NAME = "invalid-project-name"
REPOSITORY_MAPPED_TWICE = "repository-mapped-twice"
REPOSITORY_NOT_FOUND = "repository-not-found"

_HEADER = re.compile(r"^\s*\[\[\s*project\s*\]\]", re.M)


def _entry_line(text: str, index: int) -> int | None:
    headers = list(_HEADER.finditer(text))
    if index >= len(headers):
        return None
    return text.count("\n", 0, headers[index].start()) + 1


def empty(path: Path) -> Mapping:
    """The mapping when the file is absent (FR-030).

    Valid, not an error: every repository then falls back to its own ad-hoc project,
    which is the state a new user starts in. The tool works before it is configured, and
    mapping is how you improve it.
    """
    return Mapping(path=path, entries=(), present=False)


def load(path: Path) -> tuple[Mapping, list[f.Finding]]:
    """Read and structurally parse the mapping. Raises only on an unparseable file."""
    if not path.exists():
        return empty(path), []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigParseError(
            f"{path} could not be read: {exc}",
            remedy="Check the file's permissions.",
        ) from exc

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        line = column = None
        match = _POSITION.search(str(exc))
        if match:
            line, column = int(match.group(1)), int(match.group(2))
        where = f" (line {line}, column {column})" if line else ""
        raise ConfigParseError(
            f"{path} is not valid TOML{where}: {exc}",
            remedy="Fix the syntax error. The file has not been modified.",
            line=line,
            column=column,
        ) from exc

    problems: list[f.Finding] = []

    report = permissions.check(path)
    if report.status is permissions.PermissionStatus.OTHERS_CAN_READ:
        problems.append(
            f.warning(
                f.FILE_PERMISSIONS,
                f"{path.name} is readable by other accounts ({report.detail})",
                key_path=path.name,
                remedy="Restrict it to your own account.",
            )
        )

    for key in document:
        if key not in TOP_LEVEL_KEYS:
            problems.append(
                f.blocking(
                    f.UNKNOWN_TOP_LEVEL_KEY,
                    f"unknown top-level key `{key}`",
                    key_path=key,
                    remedy="A misspelled key is a mapping you believe is in force.",
                )
            )

    version = document.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        problems.append(
            f.blocking(
                f.SETTING_TYPE_MISMATCH, "`version` must be an integer", key_path="version"
            )
        )
        version = 1

    raw_entries = document.get("project", [])
    if raw_entries and not isinstance(raw_entries, list):
        problems.append(
            f.blocking(
                f.UNKNOWN_TOP_LEVEL_KEY,
                "`project` must be a list of [[project]] blocks",
                key_path="project",
            )
        )
        raw_entries = []

    entries: list[MappingEntry] = []
    for index, table in enumerate(raw_entries):
        if not isinstance(table, dict):
            problems.append(
                f.blocking(
                    INVALID_PROJECT_NAME,
                    f"project[{index}] is not a table",
                    key_path=f"project[{index}]",
                )
            )
            continue

        name = table.get("name")
        line = _entry_line(text, index)
        if not isinstance(name, str) or not name.strip():
            problems.append(
                f.blocking(
                    INVALID_PROJECT_NAME,
                    "a project must have a name",
                    key_path=f"project[{index}].name",
                    line=line,
                )
            )
            continue

        for key in table:
            if key not in ENTRY_KEYS:
                problems.append(
                    f.blocking(
                        f.UNKNOWN_SETTING,
                        f"a project does not accept `{key}`",
                        source_name=name,
                        key_path=f"project[{index}].{key}",
                        line=line,
                        remedy="Accepted: " + ", ".join(sorted(ENTRY_KEYS)),
                    )
                )

        raw_repositories = table.get("repositories", [])
        if not isinstance(raw_repositories, list) or not all(
            isinstance(item, str) for item in raw_repositories
        ):
            problems.append(
                f.blocking(
                    f.SETTING_TYPE_MISMATCH,
                    "`repositories` must be a list of names or paths",
                    source_name=name,
                    key_path=f"project[{index}].repositories",
                    line=line,
                )
            )
            raw_repositories = []

        raw_correspondents = _string_list(
            table, "correspondents", name, index, line, problems
        )
        raw_subjects = _string_list(table, "subjects", name, index, line, problems)

        correspondents: list[str] = []
        for position, entry in enumerate(raw_correspondents):
            cleaned = entry.strip()
            if "@" in cleaned and not addresses.is_valid(cleaned):
                problems.append(
                    f.blocking(
                        MALFORMED_CORRESPONDENT,
                        f"{entry!r} is not an address or a domain",
                        source_name=name,
                        key_path=f"project[{index}].correspondents[{position}]",
                        line=line,
                        remedy=(
                            "It can never match, so it is a typo rather than an "
                            "intention. Use an address like `anna@acme.example`, or a "
                            "bare domain like `acme.example`."
                        ),
                    )
                )
                continue
            if not cleaned:
                continue
            correspondents.append(
                addresses.normalise(cleaned) if "@" in cleaned else cleaned.casefold()
            )

        subjects: list[str] = []
        for position, entry in enumerate(raw_subjects):
            if not entry.strip():
                problems.append(
                    f.blocking(
                        EMPTY_SUBJECT_RULE,
                        "an empty subject rule would match every message",
                        source_name=name,
                        key_path=f"project[{index}].subjects[{position}]",
                        line=line,
                        remedy="Give it the text you actually want to match, or remove it.",
                    )
                )
                continue
            subjects.append(entry.strip())

        note = table.get("note")
        entries.append(
            MappingEntry(
                project_name=name.strip(),
                repositories=tuple(str(r) for r in raw_repositories),
                correspondents=tuple(correspondents),
                subjects=tuple(subjects),
                note=str(note) if isinstance(note, str) else None,
                index=index,
                line=line,
            )
        )

    problems.extend(_uniqueness(entries))
    problems.extend(
        _claimed_twice(
            entries, lambda e: e.correspondents, DUPLICATE_CORRESPONDENT, "correspondent"
        )
    )
    problems.extend(
        _claimed_twice(
            entries,
            lambda e: tuple(s.casefold() for s in e.subjects),
            DUPLICATE_SUBJECT,
            "subject rule",
        )
    )

    mapping = Mapping(
        path=path,
        entries=tuple(entries),
        version=version,
        present=True,
        raw_text=text,
        _by_key=build_index(tuple(entries)),
    )
    return mapping, problems


def _string_list(
    table: dict[str, object],
    key: str,
    project: str,
    index: int,
    line: int | None,
    problems: list[f.Finding],
) -> list[str]:
    raw = table.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        problems.append(
            f.blocking(
                f.SETTING_TYPE_MISMATCH,
                f"`{key}` must be a list of strings",
                source_name=project,
                key_path=f"project[{index}].{key}",
                line=line,
            )
        )
        return []
    return [str(item) for item in raw]


def _claimed_twice(
    entries: list[MappingEntry],
    values: "Callable[[MappingEntry], tuple[str, ...]]",
    code: str,
    what: str,
) -> list[f.Finding]:
    """Two projects claiming the same rule is ambiguous, and the user must resolve it.

    Blocking rather than first-wins: silently preferring one project would put billable
    work on the wrong line, and nothing in the output would say so.
    """
    problems: list[f.Finding] = []
    seen: dict[str, str] = {}
    for entry in entries:
        for value in values(entry):
            owner = seen.get(value)
            if owner is not None and owner != entry.project_name:
                problems.append(
                    f.blocking(
                        code,
                        f"{what} {value!r} is claimed by both {owner!r} and "
                        f"{entry.project_name!r}",
                        source_name=entry.project_name,
                        key_path=entry.key_path,
                        line=entry.line,
                        remedy="Decide which project it belongs to and remove the other.",
                    )
                )
            else:
                seen.setdefault(value, entry.project_name)
    return problems


def _uniqueness(entries: list[MappingEntry]) -> list[f.Finding]:
    problems: list[f.Finding] = []

    seen_projects: dict[str, int] = {}
    for entry in entries:
        key = normalise(entry.project_name)
        if key in seen_projects:
            problems.append(
                f.blocking(
                    DUPLICATE_PROJECT_NAME,
                    f"duplicate project name (also at project[{seen_projects[key]}])",
                    source_name=entry.project_name,
                    key_path=f"{entry.key_path}.name",
                    line=entry.line,
                    remedy=(
                        "Two projects cannot share a name, including one differing only "
                        "in case."
                    ),
                )
            )
        else:
            seen_projects[key] = entry.index

    # A repository must land on exactly one project, or an activity would have two.
    claimed: dict[str, str] = {}
    for entry in entries:
        for repository in entry.repositories:
            key = normalise(repository)
            if key in claimed and claimed[key] != entry.project_name:
                problems.append(
                    f.blocking(
                        REPOSITORY_MAPPED_TWICE,
                        f"{repository!r} is also claimed by {claimed[key]!r}",
                        source_name=entry.project_name,
                        key_path=f"{entry.key_path}.repositories",
                        line=entry.line,
                        remedy="A repository maps to exactly one project.",
                    )
                )
            else:
                claimed[key] = entry.project_name
    return problems


def unmatched(mapping: Mapping, repositories: list[Repository]) -> list[f.Finding]:
    """Mapping entries that match no discovered repository (FR-042).

    A **warning**, not a refusal: mapping a repository you have not configured yet — or
    that lives on another machine — is a reasonable thing to do. It is still reported,
    because a mapping that silently does nothing is how a user comes to believe their
    time is being attributed when it is not.
    """
    known: set[str] = set()
    for repository in repositories:
        known.add(normalise(repository.name))
        for candidate in repository.paths:
            known.add(normalise(str(candidate.path)))

    problems: list[f.Finding] = []
    for entry in mapping.entries:
        for position, named in enumerate(entry.repositories):
            expanded = normalise(str(Path(named).expanduser()))
            if normalise(named) in known or expanded in known:
                continue
            problems.append(
                f.warning(
                    REPOSITORY_NOT_FOUND,
                    f"{named!r} matches no discovered repository",
                    source_name=entry.project_name,
                    key_path=f"{entry.key_path}.repositories[{position}]",
                    line=entry.line,
                    remedy=(
                        "It may not be configured yet, or may be on another machine. "
                        "Nothing is attributed to it until it is found."
                    ),
                )
            )
    return problems
