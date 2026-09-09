"""User Story 4 — upgrading does not cost the archive (FR-020 to FR-022).

Per the constitution, each path is exercised against **both an empty and a populated**
store.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import make_batch, make_record
from iknowwhatyoudid.corrections import repository as corrections_repo
from iknowwhatyoudid.errors import MigrationError, StoreTooNewError
from iknowwhatyoudid.records import repository as repo
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate
from iknowwhatyoudid.store.migrations import m0001_initial

BASE = migrate.MigrationStep(1, "m0001_initial", m0001_initial.upgrade)


def _add_column(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE raw_record ADD COLUMN participants TEXT")


def _explode(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE half_done (x INTEGER)")
    raise RuntimeError("disk full")


@pytest.fixture(params=["empty", "populated"])
def store_at_v1(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[tuple[sqlite3.Connection, Path, int, int]]:
    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)

    if request.param == "populated":
        repo.ingest(
            connection,
            make_batch("mail", records=[make_record("a"), make_record("b", day=2)]),
        )
        corrections_repo.record(
            connection, source="mail", source_id="a", project="acme", made_at_utc=1
        )

    records = int(connection.execute("SELECT count(*) FROM raw_record").fetchone()[0])
    corrections = corrections_repo.count(connection)
    yield connection, path, records, corrections
    connection.close()


def test_a_pending_migration_is_applied_without_intervention(
    store_at_v1: tuple[sqlite3.Connection, Path, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-020, SC-006 — counts identical afterwards."""
    connection, path, records, corrections = store_at_v1
    monkeypatch.setattr(
        migrate, "discover", lambda: (BASE, migrate.MigrationStep(2, "m0002", _add_column))
    )

    applied = migrate.ensure_current(connection, path)

    assert applied.current == 1 and applied.target == 2
    assert conn.user_version(connection) == 2
    assert int(connection.execute("SELECT count(*) FROM raw_record").fetchone()[0]) == records
    assert corrections_repo.count(connection) == corrections


def test_a_failed_migration_leaves_the_store_exactly_as_it_was(
    store_at_v1: tuple[sqlite3.Connection, Path, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-021, SC-007 — the behaviour that rests on transactional DDL."""
    connection, path, records, corrections = store_at_v1
    monkeypatch.setattr(
        migrate, "discover", lambda: (BASE, migrate.MigrationStep(2, "m0002", _explode))
    )

    with pytest.raises(MigrationError) as caught:
        migrate.migrate(connection, path)

    assert "unchanged" in (caught.value.remedy or "")
    assert conn.user_version(connection) == 1, "version rolled back with the transaction"

    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "half_done" not in tables, "DDL rolled back too"

    # Still fully usable, with nothing lost.
    assert int(connection.execute("SELECT count(*) FROM raw_record").fetchone()[0]) == records
    assert corrections_repo.count(connection) == corrections
    repo.ingest(connection, make_batch("mail", records=[make_record("post-failure", day=7)]))


def test_a_store_from_a_newer_version_is_refused_and_untouched(
    store_at_v1: tuple[sqlite3.Connection, Path, int, int],
) -> None:
    """FR-022 — exit code 2, and nothing changes."""
    connection, path, records, _ = store_at_v1
    conn.set_user_version(connection, 99)

    with pytest.raises(StoreTooNewError) as caught:
        migrate.plan(connection)

    assert caught.value.exit_code == 2
    assert conn.user_version(connection) == 99
    assert int(connection.execute("SELECT count(*) FROM raw_record").fetchone()[0]) == records


def test_migrating_an_already_current_store_is_a_noop(
    store_at_v1: tuple[sqlite3.Connection, Path, int, int],
) -> None:
    connection, path, _, _ = store_at_v1
    assert migrate.migrate(connection, path).is_noop


def test_a_failed_migration_retains_its_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second safety net, for what a transaction cannot cover."""
    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    repo.ingest(connection, make_batch("mail", records=[make_record("a")]))

    monkeypatch.setattr(
        migrate, "discover", lambda: (BASE, migrate.MigrationStep(2, "m0002", _explode))
    )
    with pytest.raises(MigrationError):
        migrate.migrate(connection, path)

    assert migrate.snapshot_path(path, 1).exists()
    connection.close()


def test_discovery_finds_the_shipped_migration() -> None:
    steps = migrate.discover()
    assert [step.version for step in steps] == sorted(step.version for step in steps)
    assert steps[0].version == 1
    assert migrate.highest_known_version() >= 1
