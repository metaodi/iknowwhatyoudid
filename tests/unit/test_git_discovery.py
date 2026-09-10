"""Discovery and identity (US4 — FR-001 to FR-009, FR-005)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fixtures import gitrepos
from iknowwhatyoudid.git import discovery, identity


def names(found: discovery.Discovered) -> set[str]:
    return {facts.name for facts in found.repositories}


def codes(found: discovery.Discovered) -> set[str]:
    return {finding.code for finding in found.findings}


# --- identity ------------------------------------------------------------------------


def test_a_linked_worktree_is_the_same_repository(tmp_path: Path) -> None:
    """FR-005 — the same repository reachable by two paths is recorded once."""
    built = gitrepos.plain(tmp_path)
    work = gitrepos.worktree(tmp_path, built.path)

    origin = identity.describe(built.path)
    linked = identity.describe(work)

    assert origin is not None and linked is not None
    assert origin.identity == linked.identity
    assert linked.is_worktree


def test_an_independent_clone_is_a_different_repository(tmp_path: Path) -> None:
    """The correction to research R3.

    Root-commit identity would merge these — and would merge two unrelated repositories
    that happen to share a root commit, silently mixing two projects' work.
    """
    built = gitrepos.plain(tmp_path)
    bare = gitrepos.bare_clone(tmp_path, built.path)

    origin = identity.describe(built.path)
    clone = identity.describe(bare)

    assert origin is not None and clone is not None
    assert origin.identity != clone.identity
    assert origin.root_commit == clone.root_commit, "the shared history is still visible"


def test_two_repositories_with_the_same_history_stay_separate(tmp_path: Path) -> None:
    """The bug that root-commit identity produced, asserted directly."""
    a = gitrepos.plain(tmp_path, "one")
    b = gitrepos.plain(tmp_path, "two")

    first = identity.describe(a.path)
    second = identity.describe(b.path)

    assert first is not None and second is not None
    assert first.identity != second.identity


def test_an_empty_repository_still_has_an_identity(tmp_path: Path) -> None:
    empty = gitrepos.empty(tmp_path)
    facts = identity.describe(empty)

    assert facts is not None
    assert facts.root_commit is None
    assert facts.has_commits is False
    assert facts.identity


def test_a_directory_with_a_junk_git_folder_is_not_a_repository(tmp_path: Path) -> None:
    """Verified: asking git rejects it; a `.git` existence check would not."""
    fake = gitrepos.not_a_repository(tmp_path)
    assert identity.describe(fake) is None
    assert not identity.is_repository(fake)


# --- discovery -----------------------------------------------------------------------


def test_repositories_under_a_root_are_found(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    for name in ("alpha", "beta"):
        gitrepos.plain(dev, name)

    found = discovery.discover([str(dev)])
    assert names(found) == {"alpha", "beta"}


def test_a_glob_expands(tmp_path: Path) -> None:
    """FR-001."""
    for parent in ("work", "personal"):
        (tmp_path / parent).mkdir()
        gitrepos.plain(tmp_path / parent, f"{parent}-repo")

    found = discovery.discover([str(tmp_path / "*")])
    assert names(found) == {"work-repo", "personal-repo"}


def test_an_excluded_location_is_skipped(tmp_path: Path) -> None:
    """FR-002."""
    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.plain(dev, "wanted")
    gitrepos.plain(dev, "unwanted")

    found = discovery.discover([str(dev)], [str(dev / "unwanted")])
    assert names(found) == {"wanted"}


def test_nested_repositories_are_both_found_and_reported(tmp_path: Path) -> None:
    """FR-006."""
    outer, inner = gitrepos.nested(tmp_path)
    found = discovery.discover([str(tmp_path)])

    assert names(found) == {"outer", "inner"}
    assert discovery.NESTED_REPOSITORY in codes(found)


def test_the_same_repository_by_two_paths_is_recorded_once(tmp_path: Path) -> None:
    """FR-005."""
    dev = tmp_path / "dev"
    dev.mkdir()
    built = gitrepos.plain(dev, "only-one")
    (built.path / "src" / "deep").mkdir(parents=True)

    found = discovery.discover([str(dev), str(dev / "only-one")])

    assert len(found.repositories) == 1
    assert len(found.paths_by_identity) == 1
    # And one path, not one per subdirectory: `rev-parse` resolves upward, so every
    # directory inside a working tree answers "yes, a repository".
    assert len(next(iter(found.paths_by_identity.values()))) == 1


def test_a_location_matching_nothing_warns(tmp_path: Path) -> None:
    """FR-004, SC-010 — silence would look identical to a week with no work."""
    empty_dir = tmp_path / "nothing"
    empty_dir.mkdir()

    found = discovery.discover([str(empty_dir)])
    assert discovery.LOCATION_MATCHED_NOTHING in codes(found)
    warning = next(
        f for f in found.findings if f.code == discovery.LOCATION_MATCHED_NOTHING
    )
    assert empty_dir.name in warning.message, "the location is named"


def test_a_location_that_does_not_exist_warns(tmp_path: Path) -> None:
    found = discovery.discover([str(tmp_path / "absent")])
    assert discovery.LOCATION_MATCHED_NOTHING in codes(found)


def test_the_large_match_warning_fires(tmp_path: Path) -> None:
    """FR-009 — a guardrail against `paths = ["~"]`, not a capacity limit."""
    dev = tmp_path / "many"
    dev.mkdir()
    gitrepos.many(dev, 3)

    found = discovery.discover([str(dev)], threshold=2)
    assert discovery.MANY_REPOSITORIES in codes(found)
    assert len(found.repositories) == 3, "it warns; it does not refuse"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privilege on Windows")
def test_a_symlink_out_of_the_root_is_not_followed(tmp_path: Path) -> None:
    """FR-008 — a link into `/` must not widen a narrow configuration."""
    outside = tmp_path / "outside"
    outside.mkdir()
    gitrepos.plain(outside, "elsewhere")

    inside = tmp_path / "inside"
    inside.mkdir()
    gitrepos.plain(inside, "here")
    (inside / "link").symlink_to(outside, target_is_directory=True)

    found = discovery.discover([str(inside)])
    assert names(found) == {"here"}


def test_discovery_reads_no_commit_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-003, SC-008 — deciding whether to proceed must be cheap."""
    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.plain(dev, "alpha")

    from iknowwhatyoudid.git import binary

    original = binary.run
    used: list[str] = []

    def spy(repository: Path, subcommand: str, *args: str, **kwargs: object) -> str:
        used.append(subcommand)
        return original(repository, subcommand, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(binary, "run", spy)
    discovery.discover([str(dev)])

    assert "log" not in used, "discovery must not read history"


# --- validation is cheap -------------------------------------------------------------


def test_check_locations_does_not_walk(tmp_path: Path) -> None:
    """`sources validate` is run constantly; it must not scan the filesystem.

    A full recursive walk of every configured root is thousands of directories and a
    git invocation each on a developer's machine.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.plain(dev, "alpha")

    from iknowwhatyoudid.git import binary

    used: list[str] = []
    original = binary.run

    def spy(repository: Path, subcommand: str, *args: str, **kwargs: object) -> str:
        used.append(subcommand)
        return original(repository, subcommand, *args, **kwargs)  # type: ignore[arg-type]

    import pytest as _pytest

    monkey = _pytest.MonkeyPatch()
    monkey.setattr(binary, "run", spy)
    try:
        problems = discovery.check_locations([str(dev)])
    finally:
        monkey.undo()

    assert problems == []
    assert used == [], "no git invocation at all"


def test_check_locations_warns_for_a_missing_location(tmp_path: Path) -> None:
    problems = discovery.check_locations([str(tmp_path / "absent")])
    assert discovery.LOCATION_MATCHED_NOTHING in {p.code for p in problems}


# --- what discovery is allowed to cost -----------------------------------------------


def _spy_on_git(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    from iknowwhatyoudid.git import binary

    calls: list[tuple[str, ...]] = []
    original = binary.try_run

    def spy(repository: Path, subcommand: str, *args: str) -> str | None:
        calls.append((subcommand, *args))
        return original(repository, subcommand, *args)

    monkeypatch.setattr(binary, "try_run", spy)
    return calls


def test_discovery_does_not_interrogate_every_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fault that made `repos list` take an hour and a half on a real machine.

    A developer's `dev` folder held 29,436 directories and two dozen repositories.
    Asking git about each directory costs tens of milliseconds on Windows, so the cost
    of a listing must scale with the number of *repositories*, not with the number of
    directories they happen to be surrounded by.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.plain(dev, "alpha")
    for index in range(200):
        (dev / f"notes-{index:03d}" / "deeper" / "deeper-still").mkdir(parents=True)

    calls = _spy_on_git(monkeypatch)
    found = discovery.discover([str(dev)])

    assert names(found) == {"alpha"}
    assert len(calls) <= 10, (
        f"{len(calls)} git invocations for one repository among 600 directories; "
        "discovery is asking git about directories that cannot be repositories"
    )


def test_discovery_never_walks_the_commit_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-003 — "reads no history" includes the tempting question.

    Finding a repository's root commit means walking every commit in it. It is history,
    it is unbounded, and deciding whether to proceed must not pay for it.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.plain(dev, "alpha")

    calls = _spy_on_git(monkeypatch)
    found = discovery.discover([str(dev)])

    assert found.count == 1
    assert found.repositories[0].root_commit is None, "not read, and not claimed"
    unbounded = [
        call
        for call in calls
        if call[0] == "rev-list" and "-n" not in call and "--max-count=1" not in call
    ]
    assert not unbounded, f"discovery walked history: {unbounded}"
