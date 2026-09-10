"""Repository identity.

A repository's identity is the resolved path of its **`--git-common-dir`**.

Research R3 proposed the *root commit* instead, on the grounds that it survives a move.
Implementation showed that over-merges: **two independent repositories that share a root
commit collapse into one** — verified with two fixture repositories built from identical
content, and reachable in the wild with template-generated or forked repositories. The
failure is silent and attributes one project's work to another, which is the worst shape
of error for something that feeds a timesheet.

The common directory has the opposite failure: a *moved* repository looks new, so its
history splits across two rows. That is visible, and the mapping can point both at one
project. Per the constitution — "a confident wrong guess is worse than an acknowledged
gap, because only the gap gets checked" — under-merging is the safe direction.

FR-005 asks that the same repository "reachable by more than one configured path" be
recorded once, and the common directory answers exactly that: verified, a linked worktree
resolves to its origin's common directory and so unifies, while an independent clone gets
its own and stays separate.

The root commit is still read and stored, so a later feature can recognise a move.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from . import binary

PATH_IDENTITY_PREFIX = "path:"


class IdentityKind(StrEnum):
    GIT_DIR = "git_dir"


@dataclass(frozen=True, slots=True)
class RepositoryFacts:
    """What discovery learns about a candidate directory without reading history."""

    path: Path
    identity: str
    identity_kind: IdentityKind
    name: str
    is_bare: bool
    is_worktree: bool
    common_dir: Path
    has_commits: bool
    #: Kept so a moved repository can be recognised later, and deliberately **not** the
    #: identity: repositories sharing one would otherwise collapse into a single row.
    #: Left unset by discovery — finding it walks the whole commit graph, which is
    #: history, and discovery reads none. The reader fills it once per repository when
    #: it is actually about to read (`identity.root_commit`).
    root_commit: str | None = None


def is_repository(path: Path) -> bool:
    """Ask git, rather than looking for a `.git` entry.

    Verified: a directory containing a `.git` *folder* full of unrelated files is not a
    repository and git says so, while a `.git` *file* (a worktree or submodule) is one —
    which the naive "is .git a directory?" test gets backwards.
    """
    if not path.is_dir():
        return False
    return binary.try_run(path, "rev-parse", "--git-dir") is not None


def root_commit(path: Path) -> str | None:
    """The earliest parentless commit, or None for a repository with no commits."""
    output = binary.try_run(path, "rev-list", "--max-parents=0", "--all")
    if not output:
        return None
    # A repository with several root commits (a merged unrelated history) has more than
    # one; the earliest in rev-list order is stable for a given history.
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return sorted(lines)[0] if lines else None


def has_any_commit(path: Path) -> bool:
    """Whether the repository has any commit, reading at most one.

    `-n 1` matters: the obvious question — "what is the root commit?" — walks the whole
    graph to answer, which is history, and discovery is defined as not reading history.
    """
    output = binary.try_run(path, "rev-list", "--all", "-n", "1")
    return bool(output and output.strip())


def _absolute(raw: str | None, relative_to: Path, fallback: Path) -> Path:
    if not raw or not raw.strip():
        return fallback.resolve()
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = relative_to / candidate
    return candidate.resolve()


def describe(path: Path) -> RepositoryFacts | None:
    """Everything identity needs, without reading any commit history.

    Deliberately few git invocations. Discovery asks this of every candidate directory,
    and on Windows a `git` spawn costs tens of milliseconds — so asking six questions
    instead of three is the difference between a listing and a coffee break. One
    `rev-parse` answers three of them; `--show-toplevel` cannot join it because a bare
    repository has no work tree and failing that argument fails the whole call.
    """
    combined = binary.try_run(
        path, "rev-parse", "--git-dir", "--git-common-dir", "--is-bare-repository"
    )
    if combined is None:
        return None
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    if len(lines) < 3:
        return None
    git_dir_raw, common_raw, bare_raw = lines[0], lines[1], lines[2]

    bare = bare_raw == "true"
    common = _absolute(common_raw, path, path / ".git")
    git_dir = _absolute(git_dir_raw, path, common)
    # A linked worktree has its own git dir under the origin's common dir.
    is_worktree = git_dir != common

    identity = str(common)
    kind = IdentityKind.GIT_DIR

    # The repository's own root, not the directory we happened to ask from. `rev-parse`
    # resolves upward, so every subdirectory of a working tree answers "yes, a
    # repository" — and recording each as a separate path would list one repository a
    # dozen times.
    if bare:
        top_level = common
    else:
        top = binary.try_run(path, "rev-parse", "--show-toplevel")
        top_level = _absolute(top, path, path)

    name = top_level.name
    if bare and name.endswith(".git"):
        name = name[: -len(".git")]

    return RepositoryFacts(
        path=top_level,
        identity=identity,
        identity_kind=kind,
        name=name or path.name,
        is_bare=bare,
        is_worktree=is_worktree,
        common_dir=common,
        has_commits=has_any_commit(path),
    )
