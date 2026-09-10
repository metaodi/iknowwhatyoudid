"""Finding repositories under configured locations (FR-001 to FR-009)."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from glob import glob
from pathlib import Path

from ..config import findings as f
from . import identity
from .identity import RepositoryFacts

#: Above this, a first ingestion warns and asks the user to proceed deliberately. The
#: number's job is to catch `paths = ["~"]`, not to express a capacity limit — a working
#: developer plausibly has tens of repositories under one root and implausibly has
#: hundreds they actively commit to.
LARGE_MATCH_THRESHOLD = 100

#: Never descended into. `.git` is not a working tree, and the rest are noise that can
#: hold thousands of directories.
_SKIP_DIRECTORIES = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}
)

LOCATION_MATCHED_NOTHING = "location-matched-nothing"
LOCATION_UNREADABLE = "location-unreadable"
NESTED_REPOSITORY = "nested-repository"
MANY_REPOSITORIES = "many-repositories"


@dataclass(frozen=True, slots=True)
class Discovered:
    repositories: tuple[RepositoryFacts, ...] = ()
    findings: tuple[f.Finding, ...] = ()
    #: Identity → every path it was found at. One repository, many checkouts.
    paths_by_identity: dict[str, list[RepositoryFacts]] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.repositories)


def _expand(location: str) -> list[Path]:
    """Expand `~` and any glob, returning existing directories."""
    expanded = os.path.expanduser(location)
    if any(ch in expanded for ch in "*?["):
        return [Path(p) for p in sorted(glob(expanded)) if Path(p).is_dir()]
    path = Path(expanded)
    return [path] if path.is_dir() else []


def _might_be_a_repository(path: Path) -> bool:
    """A cheap filesystem test for whether it is worth asking git at all.

    Git remains the authority on what *is* a repository — a `.git` folder full of
    unrelated files is not one, and only git knows that. This decides only what to
    **ask about**, and the difference is the whole cost of a listing: a developer's
    `dev` folder holds tens of thousands of directories, all but a few dozen of which
    obviously cannot be repositories, and a `git` spawn on Windows costs tens of
    milliseconds. Asking every one of them takes an hour and a half; asking only these
    takes seconds.

    Both shapes count. `.git` is a directory in an ordinary checkout and a *file* in a
    linked worktree or submodule, so its mere existence is the test. A bare repository
    has no `.git` at all and is recognised by what it holds instead.
    """
    if (path / ".git").exists():
        return True
    return (
        (path / "HEAD").is_file()
        and (path / "objects").is_dir()
        and (path / "refs").is_dir()
    )


def _walk(root: Path) -> Iterable[Path]:
    """Yield candidate directories under *root*, root first.

    Descends **into** a repository's working tree so nested repositories are found
    (FR-006), but never into `.git`. Symbolic links are not followed, so a link into `/`
    cannot turn a narrow configuration into a filesystem-wide scan (FR-008).

    What is *yielded* is filtered to directories that could plausibly be repositories;
    what is *descended into* is not, because a nested repository can sit any depth below
    an ordinary folder.
    """
    if _might_be_a_repository(root):
        yield root
    for current, directories, _ in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in _SKIP_DIRECTORIES)
        # Do not descend through a symlinked directory even if os.walk lists it.
        directories[:] = [d for d in directories if not Path(current, d).is_symlink()]
        for directory in directories:
            candidate = Path(current, directory)
            if _might_be_a_repository(candidate):
                yield candidate


def check_locations(
    locations: Sequence[str],
    *,
    source_name: str | None = None,
) -> list[f.Finding]:
    """Cheap validation: do the configured locations resolve at all?

    `sources validate` is documented as fast and contacting nothing, and it is run
    constantly. A full recursive walk of every configured root — which on a developer's
    machine can be thousands of directories and a git invocation each — does not belong
    behind it. Finding the repositories is `repos list`, `repos check` and `ingest`.
    """
    problems: list[f.Finding] = []
    for index, location in enumerate(locations):
        if not _expand(location):
            problems.append(
                f.warning(
                    LOCATION_MATCHED_NOTHING,
                    f"{location!r} matched no directory",
                    source_name=source_name,
                    key_path=f"paths[{index}]",
                    remedy=(
                        "Check the path or pattern. Run `ikwyd repos list` to see what "
                        "it finds."
                    ),
                )
            )
    return problems


def discover(
    locations: Sequence[str],
    excluded: Sequence[str] = (),
    *,
    source_name: str | None = None,
    threshold: int = LARGE_MATCH_THRESHOLD,
) -> Discovered:
    """Find every repository the configuration matches, reading no history."""
    problems: list[f.Finding] = []

    exclude_paths: set[Path] = set()
    for entry in excluded:
        for path in _expand(entry):
            exclude_paths.add(path.resolve())

    by_identity: dict[str, list[RepositoryFacts]] = {}
    ordered: list[RepositoryFacts] = []

    for index, location in enumerate(locations):
        roots = _expand(location)
        if not roots:
            problems.append(
                f.warning(
                    LOCATION_MATCHED_NOTHING,
                    f"{location!r} matched no directory",
                    source_name=source_name,
                    key_path=f"paths[{index}]",
                    remedy=(
                        "Check the path or pattern. A location that quietly contributes "
                        "nothing looks the same as one with no work in it."
                    ),
                )
            )
            continue

        found_here = 0
        for root in roots:
            try:
                candidates = list(_walk(root))
            except OSError as exc:
                problems.append(
                    f.warning(
                        LOCATION_UNREADABLE,
                        f"{root} could not be searched: {exc}",
                        source_name=source_name,
                        key_path=f"paths[{index}]",
                    )
                )
                continue

            for candidate in candidates:
                if candidate.resolve() in exclude_paths:
                    continue
                if any(
                    parent in exclude_paths for parent in candidate.resolve().parents
                ):
                    continue
                facts = identity.describe(candidate)
                if facts is None:
                    continue
                found_here += 1
                # A repository is listed once per *identity*, however many directories
                # answered "yes" — `rev-parse` resolves upward, so every subdirectory of
                # a working tree does.
                is_new = facts.identity not in by_identity
                seen = by_identity.setdefault(facts.identity, [])
                if all(existing.path != facts.path for existing in seen):
                    seen.append(facts)
                if is_new:
                    ordered.append(facts)

        if found_here == 0:
            problems.append(
                f.warning(
                    LOCATION_MATCHED_NOTHING,
                    f"{location!r} matched no repository",
                    source_name=source_name,
                    key_path=f"paths[{index}]",
                    remedy="Check the path or pattern.",
                )
            )

    problems.extend(_nested_findings(ordered, source_name))

    if len(ordered) > threshold:
        problems.append(
            f.warning(
                MANY_REPOSITORIES,
                f"{len(ordered)} repositories matched, which is more than {threshold}",
                source_name=source_name,
                remedy=(
                    "Check the pattern is not broader than you meant before a year of "
                    "history is read. Narrow it with `exclude`, or proceed knowingly."
                ),
            )
        )

    return Discovered(
        repositories=tuple(ordered),
        findings=tuple(problems),
        paths_by_identity=by_identity,
    )


def _nested_findings(
    repositories: Sequence[RepositoryFacts], source_name: str | None
) -> list[f.Finding]:
    """Report a repository sitting inside another's working tree (FR-006)."""
    problems: list[f.Finding] = []
    paths = {facts.path: facts for facts in repositories}
    for path, facts in paths.items():
        for parent in path.parents:
            outer = paths.get(parent)
            if outer is not None and outer.identity != facts.identity:
                problems.append(
                    f.warning(
                        NESTED_REPOSITORY,
                        f"{facts.name!r} sits inside {outer.name!r}; "
                        "both are read separately",
                        source_name=source_name,
                        remedy="Exclude one of them if that is not what you want.",
                    )
                )
                break
    return problems
