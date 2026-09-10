"""Projects, the mapping, and re-derivation (US2, US3 — FR-024 to FR-042)."""

from __future__ import annotations

import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest

from fixtures import gitrepos
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.config import findings as f
from iknowwhatyoudid.corrections import repository as corrections_repo
from iknowwhatyoudid.projects import attribution, mapping
from iknowwhatyoudid.projects import repository as projects_repo
from iknowwhatyoudid.projects.model import normalise
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Three repositories, a config, and a mapping covering two of them."""
    dev = tmp_path / "dev"
    dev.mkdir()
    for name in ("acme-api", "acme-web", "scratchpad"):
        gitrepos.plain(dev, name)

    (tmp_path / "config.toml").write_text(
        '[[source]]\nname = "work-repos"\nkind = "git.local"\n'
        f'paths = ["{dev.as_posix()}"]\nidentities = ["{gitrepos.ME_EMAIL}"]\n',
        encoding="utf-8",
    )
    (tmp_path / "projects.toml").write_text(
        '[[project]]\nname = "acme-migration"\n'
        'repositories = ["acme-api", "acme-web"]\n',
        encoding="utf-8",
    )
    return tmp_path


def run(space: Path, *argv: str) -> int:
    return main(
        [
            *argv,
            "--config",
            str(space / "config.toml"),
            "--projects",
            str(space / "projects.toml"),
            "--store",
            str(space / "store.db"),
        ]
    )


def store_of(space: Path) -> sqlite3.Connection:
    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    return connection


def ingest(space: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(space, "ingest")
    capsys.readouterr()


def _remove_tree(root: Path) -> None:
    """Delete a tree containing a repository.

    Git marks objects read-only, and Windows refuses to unlink a read-only file, so a
    plain `rmtree` fails here.
    """
    import shutil
    import stat

    def clear_readonly(func: object, path: str, _exc: BaseException) -> None:
        Path(path).chmod(stat.S_IWRITE)
        func(path)  # type: ignore[operator]

    shutil.rmtree(root, onexc=clear_readonly)


# --- US2: everything lands on a project ---------------------------------------------


def test_every_activity_carries_a_project(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-002 — no activity is left unattributed."""
    ingest(workspace, capsys)
    store = store_of(workspace)

    total = store.execute("SELECT count(*) FROM raw_record").fetchone()[0]
    attributed = store.execute(
        "SELECT count(DISTINCT record_id) FROM derived_attribution"
    ).fetchone()[0]

    assert total > 0
    assert attributed == total
    store.close()


def test_a_mapped_repository_uses_the_declared_project(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ingest(workspace, capsys)
    store = store_of(workspace)

    rows = store.execute(
        "SELECT p.name, p.ad_hoc, d.rule FROM derived_attribution d "
        "JOIN user_project p ON p.id = d.project_id "
        "JOIN raw_record r ON r.id = d.record_id "
        "WHERE json_extract(r.payload, '$.repository_name') = 'acme-api'"
    ).fetchall()

    assert rows
    assert all(row["name"] == "acme-migration" for row in rows)
    assert all(row["ad_hoc"] == 0 for row in rows)
    assert all(row["rule"] == attribution.Rule.DECLARED.value for row in rows)
    store.close()


def test_an_unmapped_repository_gets_an_ad_hoc_project(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-034, FR-035 — named after the repository, and marked as invented."""
    ingest(workspace, capsys)
    store = store_of(workspace)

    project = projects_repo.get_project(store, "scratchpad")
    assert project is not None
    assert project.ad_hoc is True
    assert "(ad hoc)" in project.label
    store.close()


def test_two_repositories_can_share_one_project(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ingest(workspace, capsys)
    store = store_of(workspace)

    summaries = {s.project.name: s for s in projects_repo.list_projects(store)}
    assert summaries["acme-migration"].repositories == 2
    store.close()


def test_a_declared_project_with_no_activity_is_still_listed(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The user said it exists; an empty ad-hoc one is different (FR-040)."""
    (workspace / "projects.toml").write_text(
        '[[project]]\nname = "acme-migration"\nrepositories = ["acme-api"]\n\n'
        '[[project]]\nname = "admin"\n',
        encoding="utf-8",
    )
    ingest(workspace, capsys)
    store = store_of(workspace)

    names = {s.project.name for s in projects_repo.list_projects(store)}
    assert "admin" in names
    store.close()


# --- the mapping file ----------------------------------------------------------------


def test_an_absent_mapping_is_valid_and_means_all_ad_hoc(tmp_path: Path) -> None:
    """FR-030 — the state a new user starts in."""
    loaded, problems = mapping.load(tmp_path / "projects.toml")

    assert not loaded.present
    assert loaded.entries == ()
    assert problems == []


def test_a_duplicate_project_name_blocks_including_case(tmp_path: Path) -> None:
    """FR-027."""
    path = tmp_path / "projects.toml"
    path.write_text(
        '[[project]]\nname = "Acme"\n\n[[project]]\nname = "acme"\n', encoding="utf-8"
    )
    _, problems = mapping.load(path)
    assert mapping.DUPLICATE_PROJECT_NAME in {p.code for p in problems}


def test_a_repository_claimed_twice_blocks(tmp_path: Path) -> None:
    """An activity must land on exactly one project."""
    path = tmp_path / "projects.toml"
    path.write_text(
        '[[project]]\nname = "one"\nrepositories = ["shared"]\n\n'
        '[[project]]\nname = "two"\nrepositories = ["shared"]\n',
        encoding="utf-8",
    )
    _, problems = mapping.load(path)
    assert mapping.REPOSITORY_MAPPED_TWICE in {p.code for p in problems}


def test_a_repository_that_matches_nothing_only_warns(tmp_path: Path) -> None:
    """FR-042 — mapping one you have not configured yet is reasonable."""
    path = tmp_path / "projects.toml"
    path.write_text(
        '[[project]]\nname = "one"\nrepositories = ["nowhere"]\n', encoding="utf-8"
    )
    loaded, problems = mapping.load(path)
    unmatched = mapping.unmatched(loaded, [])

    assert not problems
    assert mapping.REPOSITORY_NOT_FOUND in {p.code for p in unmatched}
    assert all(not p.blocks for p in unmatched)


def test_an_unknown_key_blocks(tmp_path: Path) -> None:
    path = tmp_path / "projects.toml"
    path.write_text('[[project]]\nname = "one"\nnonsense = 1\n', encoding="utf-8")
    _, problems = mapping.load(path)
    assert f.UNKNOWN_SETTING in {p.code for p in problems}


def test_every_fault_is_reported_in_one_run(tmp_path: Path) -> None:
    path = tmp_path / "projects.toml"
    path.write_text(
        'nonsense = 1\n\n[[project]]\nname = "Acme"\nrepositories = ["r"]\n\n'
        '[[project]]\nname = "acme"\nrepositories = ["r"]\n',
        encoding="utf-8",
    )
    _, problems = mapping.load(path)
    codes = {p.code for p in problems}

    assert f.UNKNOWN_TOP_LEVEL_KEY in codes
    assert mapping.DUPLICATE_PROJECT_NAME in codes
    assert mapping.REPOSITORY_MAPPED_TWICE in codes


def test_the_mapping_file_is_never_written(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-029, across the whole surface."""
    path = workspace / "projects.toml"
    before = path.read_bytes()
    config_before = (workspace / "config.toml").read_bytes()

    for argv in (
        ["repos", "list"],
        ["repos", "check"],
        ["projects", "validate"],
        ["ingest"],
        ["projects", "list"],
        ["projects", "rederive"],
    ):
        run(workspace, *argv)
        capsys.readouterr()

    assert path.read_bytes() == before
    assert (workspace / "config.toml").read_bytes() == config_before


def test_normalisation_folds_case_and_whitespace() -> None:
    assert normalise("  Acme   Migration ") == normalise("acme migration")


# --- US3: changing the mapping -------------------------------------------------------


def test_rederiving_moves_activity_without_reading_a_repository(
    workspace: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-037, SC-006 — the repositories are deleted, so it cannot pass by accident."""
    ingest(workspace, capsys)

    (workspace / "projects.toml").write_text(
        '[[project]]\nname = "acme-migration"\n'
        'repositories = ["acme-api", "acme-web", "scratchpad"]\n',
        encoding="utf-8",
    )

    # Nothing may be read: no repository on disk, no subprocess, no socket.
    _remove_tree(workspace / "dev")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("re-derivation reached outside the store")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    store = store_of(workspace)
    loaded, _ = mapping.load(workspace / "projects.toml")
    report = attribution.rederive(store, loaded)

    assert report.moved, "the scratchpad activity moved"
    assert all(m.to_project == "acme-migration" for m in report.moved)
    store.close()


def test_an_emptied_ad_hoc_project_stops_being_listed(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-040."""
    ingest(workspace, capsys)
    store = store_of(workspace)
    assert projects_repo.get_project(store, "scratchpad") is not None

    (workspace / "projects.toml").write_text(
        '[[project]]\nname = "acme-migration"\n'
        'repositories = ["acme-api", "acme-web", "scratchpad"]\n',
        encoding="utf-8",
    )
    loaded, _ = mapping.load(workspace / "projects.toml")
    report = attribution.rederive(store, loaded)

    assert "scratchpad" in report.pruned_ad_hoc
    names = {s.project.name for s in projects_repo.list_projects(store)}
    assert "scratchpad" not in names
    store.close()


def test_a_correction_still_wins_after_a_mapping_change(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-038, SC-007 — a rule never overrides the user's own statement."""
    ingest(workspace, capsys)
    store = store_of(workspace)

    row = store.execute(
        "SELECT source, source_id FROM raw_record LIMIT 1"
    ).fetchone()
    corrections_repo.record(
        store,
        source=str(row["source"]),
        source_id=str(row["source_id"]),
        project="hand-picked",
        made_at_utc=1,
    )

    (workspace / "projects.toml").write_text(
        '[[project]]\nname = "everything"\n'
        'repositories = ["acme-api", "acme-web", "scratchpad"]\n',
        encoding="utf-8",
    )
    loaded, _ = mapping.load(workspace / "projects.toml")
    report = attribution.rederive(store, loaded)

    assert report.held_by_correction >= 1
    project, from_user = corrections_repo.project_for(
        store, str(row["source"]), str(row["source_id"])
    )
    assert project == "hand-picked" and from_user is True
    store.close()


def test_the_preview_matches_what_applying_it_does(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-041, SC-012."""
    ingest(workspace, capsys)
    store = store_of(workspace)

    (workspace / "projects.toml").write_text(
        '[[project]]\nname = "everything"\n'
        'repositories = ["acme-api", "acme-web", "scratchpad"]\n',
        encoding="utf-8",
    )
    loaded, _ = mapping.load(workspace / "projects.toml")

    predicted = attribution.rederive(store, loaded, dry_run=True)
    applied = attribution.rederive(store, loaded)

    assert predicted.move_summary == applied.move_summary
    assert len(predicted.moved) == len(applied.moved)
    store.close()


def test_a_dry_run_changes_nothing(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ingest(workspace, capsys)
    store = store_of(workspace)
    before = [
        tuple(r)
        for r in store.execute(
            "SELECT record_id, project_id FROM derived_attribution ORDER BY record_id"
        )
    ]

    (workspace / "projects.toml").write_text(
        '[[project]]\nname = "everything"\nrepositories = ["acme-api", "scratchpad"]\n',
        encoding="utf-8",
    )
    loaded, _ = mapping.load(workspace / "projects.toml")
    attribution.rederive(store, loaded, dry_run=True)

    after = [
        tuple(r)
        for r in store.execute(
            "SELECT record_id, project_id FROM derived_attribution ORDER BY record_id"
        )
    ]
    assert after == before
    store.close()


def test_an_ad_hoc_project_is_promoted_when_declared(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-039 — declaring a name the tool invented is the user confirming it."""
    ingest(workspace, capsys)
    store = store_of(workspace)
    initial = projects_repo.get_project(store, "scratchpad")
    assert initial is not None and initial.ad_hoc is True

    (workspace / "projects.toml").write_text(
        '[[project]]\nname = "scratchpad"\nrepositories = ["scratchpad"]\n',
        encoding="utf-8",
    )
    loaded, _ = mapping.load(workspace / "projects.toml")
    attribution.rederive(store, loaded)

    promoted = projects_repo.get_project(store, "scratchpad")
    assert promoted is not None and promoted.ad_hoc is False
    store.close()


# --- the package boundary ------------------------------------------------------------


def test_projects_cannot_read_a_repository() -> None:
    """What makes FR-037 structural rather than a rule someone must remember.

    Inspects the *imports* rather than the text: a module that merely mentions
    `subprocess` in a comment explaining why it must not use one is fine, and a text
    scan would fail on exactly the documentation that makes the rule clear.
    """
    import ast

    forbidden = {"subprocess", "socket"}
    for module in Path("src/iknowwhatyoudid/projects").glob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
                if node.level and node.module:
                    imported.add(node.module)

        assert not (imported & forbidden), f"{module.name} imports {imported & forbidden}"
        assert "git" not in imported, f"{module.name} imports the git package"
