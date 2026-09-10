"""Reading commits, merges and identities (FR-010 to FR-017, FR-022, FR-023)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fixtures import gitrepos
from iknowwhatyoudid.git import history, refs
from iknowwhatyoudid.git.reader import GitReader, withdrawable_ids
from iknowwhatyoudid.records.model import NormalizedRecord, RunMode
from test_git_readonly import git_source

BODY_SENTINEL = "A body that must never be stored."


def read(
    root: Path,
    mode: RunMode = RunMode.INCREMENTAL,
    identities: list[str] | None = None,
) -> list[NormalizedRecord]:
    source = git_source("repos", root)
    if identities is not None:
        source = type(source)(
            name=source.name,
            kind=source.kind,
            index=source.index,
            settings={"paths": [str(root)], "identities": identities},
        )
    return list(GitReader().read(source, None, None, mode))


def kinds(records: list[NormalizedRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.payload["kind"])
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def test_commits_and_merges_are_recorded(tmp_path: Path) -> None:
    gitrepos.plain(tmp_path)
    counts = kinds(read(tmp_path))

    assert counts.get("commit", 0) >= 3
    assert counts.get("merge", 0) == 1, "a merge is a commit with two or more parents"


def test_a_merge_is_identified_by_parent_count_not_its_message(tmp_path: Path) -> None:
    built = gitrepos.plain(tmp_path)
    merge = next(r for r in read(tmp_path) if r.payload["kind"] == "merge")

    assert merge.payload["parent_count"] >= 2
    assert merge.payload["sha"] == built.merge


def test_only_the_users_own_commits_are_recorded(tmp_path: Path) -> None:
    """FR-011 — other contributors' commits are read but not recorded."""
    gitrepos.with_other_authors(tmp_path)
    titles = {r.title for r in read(tmp_path, identities=[gitrepos.ME_EMAIL])}

    assert "mine one" in titles and "mine two" in titles
    assert "theirs one" not in titles, "neither author nor committer is me"


def test_a_patch_i_applied_counts_as_my_work(tmp_path: Path) -> None:
    """Author *or* committer: landing someone else's patch is work I did."""
    gitrepos.with_other_authors(tmp_path)
    titles = {r.title for r in read(tmp_path, identities=[gitrepos.ME_EMAIL])}
    assert "applied theirs" in titles


def test_identity_matching_is_case_insensitive(tmp_path: Path) -> None:
    gitrepos.with_other_authors(tmp_path)
    titles = {r.title for r in read(tmp_path, identities=[gitrepos.ME_EMAIL.upper()])}
    assert "mine one" in titles


def test_author_time_is_the_records_time_and_committer_time_is_kept(
    tmp_path: Path,
) -> None:
    """FR-012 — a rebase must not move a month of work to one afternoon."""
    gitrepos.plain(tmp_path)
    record = next(r for r in read(tmp_path) if r.title == "first commit")

    assert record.occurred.utcoffset() is not None, "git's own offset is preserved"
    assert "committed" in record.payload


def test_no_zone_name_is_invented(tmp_path: Path) -> None:
    """Git records an offset and never an IANA zone; the design does not pretend."""
    gitrepos.plain(tmp_path)
    record = read(tmp_path)[0]
    assert getattr(record.occurred.tzinfo, "key", None) is None


# --- what must never be stored ------------------------------------------------------


def test_no_commit_message_body_is_stored(tmp_path: Path) -> None:
    """FR-015, SC-014 — the subject is kept; the body never lands on disk."""
    gitrepos.plain(tmp_path)
    records = read(tmp_path)

    haystack = "\n".join(
        [r.title for r in records] + [json.dumps(dict(r.payload)) for r in records]
    )
    assert BODY_SENTINEL not in haystack
    assert "first commit" in haystack, "the subject is still there"


def test_no_duration_is_ever_set(tmp_path: Path) -> None:
    """FR-016, SC-013 — git knows when you committed, never how long you worked."""
    gitrepos.plain(tmp_path)
    assert all(record.duration is None for record in read(tmp_path))


def test_no_diff_or_file_name_is_stored(tmp_path: Path) -> None:
    """FR-014."""
    gitrepos.plain(tmp_path)
    for record in read(tmp_path):
        # Only the fields the record actually carries — `repository_path` legitimately
        # holds a filesystem path, and scanning it would just be reading the temp
        # directory's name back.
        assert "diff" not in record.payload
        assert "files" not in record.payload
        assert "stats" not in record.payload
        assert not any(
            isinstance(v, str) and v.endswith(".txt") for v in record.payload.values()
        )


# --- withdrawal, and the trap (research R2) -----------------------------------------


def test_branch_creations_are_read_from_the_reflog(tmp_path: Path) -> None:
    gitrepos.plain(tmp_path)
    created = [r for r in read(tmp_path) if r.payload["kind"] == "branch_created"]

    assert created, "the reflog holds the creation event"
    assert any("feature" in str(r.payload["branch"]) for r in created)
    assert all(r.payload["evidence"] == "reflog" for r in created)


def test_a_branch_creation_is_never_withdrawable(tmp_path: Path) -> None:
    """The finding that most shaped this feature.

    The reflog is local and expires after 90 days. If a branch creation entered a
    sweep's seen set, the next sweep after expiry would not find it and would mark a real
    event withdrawn — a retention policy reported as data loss.
    """
    gitrepos.plain(tmp_path)
    records = read(tmp_path, RunMode.SWEEP)
    seen = withdrawable_ids(records)

    creations = [r for r in records if r.payload["kind"] == "branch_created"]
    assert creations
    for creation in creations:
        assert creation.payload["withdrawable"] is False
        assert creation.source_id not in seen

    commits = [r for r in records if r.payload["kind"] in {"commit", "merge"}]
    assert commits and all(c.source_id in seen for c in commits)


def test_losing_the_reflog_does_not_lose_the_commits(tmp_path: Path) -> None:
    """Standing in for the 90-day expiry: history survives, branch events do not."""
    gitrepos.plain(tmp_path)
    before = read(tmp_path)
    gitrepos.drop_reflog(tmp_path / "plain-repo")
    after = read(tmp_path)

    assert not [r for r in after if r.payload["kind"] == "branch_created"]
    commits_before = {r.source_id for r in before if r.payload["kind"] != "branch_created"}
    commits_after = {r.source_id for r in after if r.payload["kind"] != "branch_created"}
    assert commits_before == commits_after


def test_a_rewritten_commit_disappears_from_the_seen_set(tmp_path: Path) -> None:
    """FR-023 — a rewritten history genuinely removes a commit."""
    built = gitrepos.plain(tmp_path)
    before = withdrawable_ids(read(tmp_path, RunMode.SWEEP))
    assert f"merge:{built.merge}" in before

    gitrepos.rewrite_history(built.path)
    after = withdrawable_ids(read(tmp_path, RunMode.SWEEP))

    assert f"merge:{built.merge}" not in after, "the old commit no longer exists"


# --- awkward repositories -----------------------------------------------------------


def test_an_empty_repository_contributes_nothing_and_is_not_an_error(
    tmp_path: Path,
) -> None:
    """FR-021."""
    gitrepos.empty(tmp_path)
    assert read(tmp_path) == []


def test_a_bare_clone_is_read(tmp_path: Path) -> None:
    built = gitrepos.plain(tmp_path)
    bare = gitrepos.bare_clone(tmp_path, built.path)
    records = list(
        GitReader().read(git_source("r", bare.parent), None, None, RunMode.INCREMENTAL)
    )
    assert records


def test_streaming_yields_rather_than_accumulating(tmp_path: Path) -> None:
    """`commits()` is a generator, so a decade of history is never materialised."""
    gitrepos.plain(tmp_path)
    stream = history.commits(tmp_path / "plain-repo")
    assert next(stream) is not None


def test_branches_are_listed(tmp_path: Path) -> None:
    built = gitrepos.plain(tmp_path)
    names = {branch.name for branch in refs.branches(built.path)}
    assert {"main", "feature"} <= names


# --- withdrawal through the store, not just the reader -------------------------------


def _sweep(space: Path) -> None:
    from iknowwhatyoudid.cli.main import main

    main(
        [
            "ingest",
            "--sweep",
            "--config",
            str(space / "config.toml"),
            "--store",
            str(space / "store.db"),
        ]
    )


def _configure(space: Path, dev: Path) -> None:
    (space / "config.toml").write_text(
        '[[source]]\nname = "repos"\nkind = "git.local"\n'
        f'paths = ["{dev.as_posix()}"]\nidentities = ["{gitrepos.ME_EMAIL}"]\n',
        encoding="utf-8",
    )


def _branch_creations(space: Path) -> list[tuple[str, object]]:
    from iknowwhatyoudid.store import connection as conn
    from iknowwhatyoudid.store import migrate

    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    rows = connection.execute(
        "SELECT source_id, withdrawn_on_utc FROM raw_record "
        "WHERE json_extract(payload, '$.kind') = 'branch_created'"
    ).fetchall()
    connection.close()
    return [(str(r["source_id"]), r["withdrawn_on_utc"]) for r in rows]


def test_a_sweep_after_the_reflog_expires_keeps_the_branch_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Quickstart scenario 8, step 3 — the research R2 trap, end to end.

    The reader-level test proves a branch creation is not *reported* as still existing.
    This proves the record already in the store is not *withdrawn* when it stops being
    reported: the reflog is a 90-day retention policy, and expiry is not deletion.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.plain(dev)
    _configure(tmp_path, dev)

    _sweep(tmp_path)
    capsys.readouterr()
    first = _branch_creations(tmp_path)
    assert first, "a branch creation was recorded"
    assert all(withdrawn is None for _, withdrawn in first)

    gitrepos.drop_reflog(dev / "plain-repo")
    _sweep(tmp_path)
    capsys.readouterr()

    after = dict(_branch_creations(tmp_path))
    assert set(after) == {source_id for source_id, _ in first}, "nothing was deleted"
    withdrawn = [source_id for source_id, when in after.items() if when is not None]
    assert not withdrawn, (
        f"{len(withdrawn)} branch creation(s) were withdrawn because the reflog expired; "
        "a retention policy has been recorded as data loss"
    )


def _records(space: Path) -> dict[str, object]:
    from iknowwhatyoudid.store import connection as conn
    from iknowwhatyoudid.store import migrate

    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    rows = connection.execute(
        "SELECT source_id, withdrawn_on_utc FROM raw_record"
    ).fetchall()
    connection.close()
    return {str(r["source_id"]): r["withdrawn_on_utc"] for r in rows}


def _ingest(space: Path, *extra: str) -> None:
    from iknowwhatyoudid.cli.main import main

    main(
        [
            "ingest",
            *extra,
            "--config",
            str(space / "config.toml"),
            "--store",
            str(space / "store.db"),
        ]
    )


def test_an_incremental_run_withdraws_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Quickstart scenario 8, step 1 — the trap, tested before the capability.

    An incremental read is not exhaustive, so nothing may be concluded from what it did
    not return. Rewriting history between two incremental runs must withdraw nothing.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    built = gitrepos.plain(dev)
    _configure(tmp_path, dev)

    _ingest(tmp_path)
    capsys.readouterr()
    before = _records(tmp_path)

    gitrepos.rewrite_history(built.path)
    _ingest(tmp_path)
    capsys.readouterr()

    after = _records(tmp_path)
    assert set(before) <= set(after), "nothing was deleted"
    assert all(after[source_id] is None for source_id in before), (
        "an incremental run withdrew a record it had no basis to withdraw"
    )


def test_a_sweep_withdraws_a_vanished_commit_without_deleting_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Quickstart scenario 8, step 2 — FR-022, FR-023.

    A sweep re-reads its whole window rather than resuming; that is what makes the
    absence of a commit evidence of anything at all.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    built = gitrepos.plain(dev)
    _configure(tmp_path, dev)

    _ingest(tmp_path, "--sweep")
    capsys.readouterr()
    before = _records(tmp_path)
    vanishing = f"merge:{built.merge}"
    assert before[vanishing] is None

    gitrepos.rewrite_history(built.path)
    _ingest(tmp_path, "--sweep")
    capsys.readouterr()

    after = _records(tmp_path)
    assert len(after) >= len(before), "records are marked, never deleted"
    assert after[vanishing] is not None, "the rewritten-away commit was not withdrawn"
    survivors = [
        source_id
        for source_id, withdrawn in after.items()
        if source_id != vanishing and withdrawn is not None
    ]
    assert not survivors, f"a sweep withdrew more than vanished: {survivors}"


# --- one repository failing never silences the others (FR-007, FR-020, SC-011) --------


def test_a_repository_lost_mid_run_is_named_and_the_others_still_ingest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quickstart scenario 11 — the repository deleted between discovery and reading.

    The run must continue *and* say what it lost. A partial ingestion reported as a
    clean one is worse than a failure: it produces a gap in a timesheet nobody checks.
    """
    import shutil
    import stat

    from iknowwhatyoudid.git import reader as git_reader

    dev = tmp_path / "dev"
    dev.mkdir()
    for name in ("alpha", "beta", "doomed"):
        gitrepos.plain(dev, name)
    _configure(tmp_path, dev)

    original = git_reader.discover_for

    def discover_then_lose_one(source: object) -> object:
        found = original(source)  # type: ignore[arg-type]

        def clear_readonly(func: object, path: str, _exc: BaseException) -> None:
            Path(path).chmod(stat.S_IWRITE)
            func(path)  # type: ignore[operator]

        shutil.rmtree(dev / "doomed", onexc=clear_readonly)
        return found

    monkeypatch.setattr(git_reader, "discover_for", discover_then_lose_one)

    _ingest(tmp_path)
    out = capsys.readouterr().out

    stored = _records(tmp_path)
    assert stored, "the surviving repositories were still ingested"
    assert "doomed" in out, "the lost repository was not named in the output"
    assert "skipped" in out.lower()


# --- history that the platform default cannot decode ---------------------------------

REPLACEMENT = chr(0xFFFD)


def test_a_subject_the_ansi_codepage_cannot_decode_is_read_intact(tmp_path: Path) -> None:
    """The fault that failed a whole source on a real machine.

    `text=True` decodes with the platform's preferred encoding — cp1252 on Windows — and
    one commit whose subject contained a symbol raised `UnicodeDecodeError`, which the
    run reported as the entire source failing. Git's convention is UTF-8, so that is
    what is asked for explicitly.
    """
    repo = gitrepos.with_awkward_encoding(tmp_path)
    subjects = [commit.subject for commit in history.commits(repo)]

    assert gitrepos.PENCIL_SUBJECT in subjects, subjects


def test_a_name_no_encoding_can_decode_costs_a_character_not_a_repository(
    tmp_path: Path,
) -> None:
    """Real history contains bytes that are valid in no encoding anyone still uses.

    Refusing to read the repository over one of them would be the wrong trade: the
    commit still happened, and its hash, time and parents are ASCII and intact.
    """
    repo = gitrepos.with_awkward_encoding(tmp_path)
    commits = list(history.commits(repo))

    assert len(commits) == 2, "both commits were read"
    mangled = [c for c in commits if REPLACEMENT in c.author_name]
    assert len(mangled) == 1
    assert mangled[0].sha, "the parts that are ASCII survived exactly"


def test_git_output_is_never_decoded_with_the_platform_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural, because the behavioural test only fails on some platforms.

    On Linux the preferred encoding is already UTF-8, so a machine there would never
    have seen the failure this guards against. What must hold everywhere is that the
    encoding is *stated*.
    """
    import subprocess as sp
    from typing import Any

    seen: list[dict[str, Any]] = []
    original_run = sp.run
    original_popen = sp.Popen

    def spy_run(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return original_run(*args, **kwargs)

    def spy_popen(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return original_popen(*args, **kwargs)

    # Build the repository *before* patching: the spy replaces subprocess globally, and
    # the fixture builder uses it too.
    built = gitrepos.plain(tmp_path)

    monkeypatch.setattr(sp, "run", spy_run)
    monkeypatch.setattr(sp, "Popen", spy_popen)
    list(history.commits(built.path))

    assert seen, "git was invoked"
    for kwargs in seen:
        assert kwargs.get("encoding") == "utf-8", kwargs
        assert kwargs.get("errors") == "replace", kwargs
