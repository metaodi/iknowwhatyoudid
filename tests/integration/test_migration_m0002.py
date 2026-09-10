"""v1 → v2, against an empty store and a populated one (quickstart scenario 9).

The constitution requires a migration to be tested both ways round. An empty store only
proves the DDL parses; everything that can actually go wrong — a project name that two
attributions spell differently, a correction quietly rewritten — needs rows in the
tables first.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iknowwhatyoudid.records import timestamps
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate, schema


def v1_store(path: Path) -> sqlite3.Connection:
    """A store exactly as `0001` left it: schema v1, no projects table."""
    connection = conn.connect(path)
    for statement in schema.statements(*schema.V1_DDL):
        connection.execute(statement)
    conn.set_user_version(connection, 1)
    connection.commit()
    return connection


def add_record(connection: sqlite3.Connection, source_id: str, project: str) -> int:
    now = timestamps.now_micros()
    connection.execute(
        "INSERT OR IGNORE INTO raw_source (name, first_seen_utc) VALUES ('git', ?)",
        (now,),
    )
    run = connection.execute(
        "INSERT INTO raw_ingestion_run (source, mode, started_at_utc) "
        "VALUES ('git', 'incremental', ?)",
        (now,),
    ).lastrowid
    cursor = connection.execute(
        "INSERT INTO raw_record (source, source_id, occurred_utc, "
        "occurred_offset_minutes, title, payload, ingestion_run) "
        "VALUES ('git', ?, ?, 0, 'a commit', '{}', ?)",
        (source_id, now, run),
    )
    record_id = int(cursor.lastrowid or 0)
    connection.execute(
        "INSERT INTO derived_attribution (record_id, project, rule, evidence, "
        "derived_at_utc) VALUES (?, ?, 'mapping:declared', '{}', ?)",
        (record_id, project, now),
    )
    return record_id


def projects(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        str(row["name"]): int(row["id"])
        for row in connection.execute("SELECT id, name FROM user_project")
    }


def test_an_empty_v1_store_migrates_to_v2(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    connection = v1_store(path)

    migrate.migrate(connection, path)

    assert conn.user_version(connection) == schema.SCHEMA_VERSION
    assert projects(connection) == {}
    connection.close()


def test_a_populated_store_keeps_every_attribution(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    connection = v1_store(path)
    for index, project in enumerate(("Acme", "Acme", "Scratch")):
        add_record(connection, f"commit:{index}", project)
    connection.commit()
    before = connection.execute("SELECT count(*) c FROM derived_attribution").fetchone()["c"]

    migrate.migrate(connection, path)

    after = connection.execute("SELECT count(*) c FROM derived_attribution").fetchone()["c"]
    assert after == before == 3, "no attribution was dropped"
    assert set(projects(connection)) == {"Acme", "Scratch"}
    connection.close()


def test_names_differing_only_in_case_collapse_to_one_project(tmp_path: Path) -> None:
    """The load-bearing case: `Acme`, `acme` and ` ACME ` are one project, not three."""
    path = tmp_path / "store.db"
    connection = v1_store(path)
    for index, project in enumerate(("Acme", "acme", " ACME ")):
        add_record(connection, f"commit:{index}", project)
    connection.commit()

    migrate.migrate(connection, path)

    found = projects(connection)
    assert len(found) == 1, f"expected one project, got {sorted(found)}"
    assert "Acme" in found, "the first spelling seen is the one kept"
    attributed = connection.execute(
        "SELECT count(DISTINCT project_id) c FROM derived_attribution"
    ).fetchone()["c"]
    assert attributed == 1, "all three attributions point at the same project"
    connection.close()


def test_a_correction_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """A correction is the user's own statement — the one thing a migration may not edit."""
    path = tmp_path / "store.db"
    connection = v1_store(path)
    add_record(connection, "commit:0", "Acme")
    connection.execute(
        "INSERT INTO user_correction (source, source_id, project, note, made_at_utc) "
        "VALUES ('git', 'commit:0', 'a project I never declared', 'mine', ?)",
        (timestamps.now_micros(),),
    )
    connection.commit()
    before = connection.execute("SELECT * FROM user_correction").fetchall()

    migrate.migrate(connection, path)

    after = connection.execute("SELECT * FROM user_correction").fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert "a project I never declared" not in projects(connection), (
        "a correction naming an undeclared project must not invent one"
    )
    connection.close()


def test_a_failing_migration_leaves_the_store_at_v1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-021 — the rollback the whole store design rests on, at this step."""
    path = tmp_path / "store.db"
    connection = v1_store(path)
    add_record(connection, "commit:0", "Acme")
    connection.commit()
    before = connection.execute("SELECT count(*) c FROM derived_attribution").fetchone()["c"]

    from iknowwhatyoudid.store.migrations import m0002_projects

    original = m0002_projects.upgrade

    def fail_after_creating_tables(c: sqlite3.Connection) -> None:
        original(c)
        raise RuntimeError("deliberate")

    monkeypatch.setattr(m0002_projects, "upgrade", fail_after_creating_tables)
    monkeypatch.setattr(
        migrate,
        "discover",
        lambda: (
            migrate.MigrationStep(2, "m0002_projects", fail_after_creating_tables),
        ),
    )

    with pytest.raises(Exception):  # noqa: B017 — any failure must roll back
        migrate.migrate(connection, path)

    assert conn.user_version(connection) == 1
    after = connection.execute("SELECT count(*) c FROM derived_attribution").fetchone()["c"]
    assert after == before
    names = {row["name"] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "user_project" not in names, "the half-made v2 tables were rolled back"
    connection.close()
