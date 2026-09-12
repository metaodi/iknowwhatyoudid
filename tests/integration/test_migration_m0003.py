"""v2 → v3, against an empty store and a populated one.

The constitution requires a migration to be tested both ways round. An empty store only
proves the DDL parses; everything that can actually go wrong needs rows in the tables
first — and the thing that must never go wrong is that a correction, the only
irreplaceable data in the store, is left exactly as it was.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iknowwhatyoudid.records import timestamps
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate, schema


def v2_store(path: Path) -> sqlite3.Connection:
    """A store exactly as `m0002` left it: schema v2, no correspondents."""
    connection = conn.connect(path)
    for statement in schema.statements(*schema.V2_DDL):
        connection.execute(statement)
    conn.set_user_version(connection, 2)
    connection.commit()
    return connection


def populate(connection: sqlite3.Connection) -> dict[str, int]:
    """A store with git records, a project, an attribution and a correction."""
    now = timestamps.now_micros()
    connection.execute(
        "INSERT INTO raw_source (name, first_seen_utc) VALUES ('dev-git', ?)", (now,)
    )
    run = connection.execute(
        "INSERT INTO raw_ingestion_run (source, mode, started_at_utc) "
        "VALUES ('dev-git', 'incremental', ?)",
        (now,),
    ).lastrowid
    project = connection.execute(
        "INSERT INTO user_project (name, normalised_name, ad_hoc, first_seen_utc) "
        "VALUES ('acme', 'acme', 0, ?)",
        (now,),
    ).lastrowid
    for index in range(3):
        record = connection.execute(
            "INSERT INTO raw_record (source, source_id, occurred_utc, "
            "occurred_offset_minutes, title, payload, ingestion_run) "
            "VALUES ('dev-git', ?, ?, 0, 'a commit', '{}', ?)",
            (f"commit:{index}", now + index, run),
        ).lastrowid
        connection.execute(
            "INSERT INTO derived_attribution (record_id, project_id, rule, evidence, "
            "derived_at_utc) VALUES (?, ?, 'mapping:declared', '{}', ?)",
            (record, project, now),
        )
    connection.execute(
        "INSERT INTO user_correction (source, source_id, project, note, made_at_utc) "
        "VALUES ('dev-git', 'commit:0', 'a project I named myself', 'mine', ?)",
        (now,),
    )
    connection.commit()
    return counts(connection)


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = ["raw_record", "user_project", "derived_attribution", "user_correction"]
    return {
        table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


# --- both ways round, as the constitution requires -------------------------------------


def test_an_empty_v2_store_reaches_v3(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    connection = v2_store(path)

    migrate.migrate(connection, path)

    assert conn.user_version(connection) == schema.SCHEMA_VERSION == 3
    assert {"raw_correspondent", "raw_record_correspondent"} <= table_names(connection)
    connection.close()


def test_a_populated_store_keeps_every_count(tmp_path: Path) -> None:
    """Nothing that existed before this feature may be disturbed by it."""
    path = tmp_path / "store.db"
    connection = v2_store(path)
    before = populate(connection)

    migrate.migrate(connection, path)

    assert counts(connection) == before
    assert conn.user_version(connection) == 3
    connection.close()


def test_a_correction_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """The only irreplaceable data in the store, and a migration has no business in it."""
    path = tmp_path / "store.db"
    connection = v2_store(path)
    populate(connection)
    before = [tuple(row) for row in connection.execute("SELECT * FROM user_correction")]

    migrate.migrate(connection, path)

    after = [tuple(row) for row in connection.execute("SELECT * FROM user_correction")]
    assert after == before
    connection.close()


# --- rollback ----------------------------------------------------------------------------


def test_a_failing_migration_leaves_the_store_at_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-021 — the guarantee the whole store design rests on, at this step.

    Asserted by failing *after* the tables are created, which is the case that would
    leave a half-made schema behind if the transaction were not doing its job.
    """
    path = tmp_path / "store.db"
    connection = v2_store(path)
    before = populate(connection)

    from iknowwhatyoudid.store.migrations import m0003_correspondents

    def fail_after_creating_tables(c: sqlite3.Connection) -> None:
        m0003_correspondents.upgrade(c)
        raise RuntimeError("deliberate")

    monkeypatch.setattr(
        migrate,
        "discover",
        lambda: (migrate.MigrationStep(3, "m0003_correspondents", fail_after_creating_tables),),
    )

    with pytest.raises(Exception):  # noqa: B017 — any failure must roll back
        migrate.migrate(connection, path)

    assert conn.user_version(connection) == 2
    assert counts(connection) == before
    assert "raw_correspondent" not in table_names(connection), "a half-made v3 survived"
    connection.close()


# --- the new tables behave -----------------------------------------------------------------


def test_two_addresses_differing_only_in_case_collapse(tmp_path: Path) -> None:
    """Addresses are stored already normalised, so UNIQUE does the deduplicating."""
    path = tmp_path / "store.db"
    connection = v2_store(path)
    migrate.migrate(connection, path)

    now = timestamps.now_micros()
    connection.execute(
        "INSERT INTO raw_correspondent (address, domain, first_seen_utc) VALUES (?, ?, ?)",
        ("anna@acme.example", "acme.example", now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO raw_correspondent (address, domain, first_seen_utc) "
            "VALUES (?, ?, ?)",
            ("anna@acme.example", "acme.example", now),
        )
    connection.close()


def test_deleting_a_record_forgets_its_links_but_keeps_the_correspondent(
    tmp_path: Path,
) -> None:
    """A correspondent outlives any single message they appeared on."""
    path = tmp_path / "store.db"
    connection = v2_store(path)
    populate(connection)
    migrate.migrate(connection, path)
    connection.execute("PRAGMA foreign_keys = ON")

    now = timestamps.now_micros()
    correspondent = connection.execute(
        "INSERT INTO raw_correspondent (address, domain, first_seen_utc) VALUES (?, ?, ?)",
        ("anna@acme.example", "acme.example", now),
    ).lastrowid
    record = int(connection.execute("SELECT id FROM raw_record LIMIT 1").fetchone()[0])
    connection.execute(
        "INSERT INTO raw_record_correspondent (record_id, correspondent_id, role) "
        "VALUES (?, ?, 'to')",
        (record, correspondent),
    )
    connection.commit()

    connection.execute("DELETE FROM raw_record WHERE id = ?", (record,))
    connection.commit()

    links = connection.execute("SELECT count(*) FROM raw_record_correspondent").fetchone()[0]
    people = connection.execute("SELECT count(*) FROM raw_correspondent").fetchone()[0]
    assert links == 0, "the links went with the record"
    assert people == 1, "the correspondent did not"
    connection.close()


def test_an_unknown_role_is_refused(tmp_path: Path) -> None:
    """`bcc` has no role, deliberately — the CHECK constraint is what enforces it."""
    path = tmp_path / "store.db"
    connection = v2_store(path)
    populate(connection)
    migrate.migrate(connection, path)

    now = timestamps.now_micros()
    correspondent = connection.execute(
        "INSERT INTO raw_correspondent (address, domain, first_seen_utc) VALUES (?, ?, ?)",
        ("carol@northwind.example", "northwind.example", now),
    ).lastrowid
    record = int(connection.execute("SELECT id FROM raw_record LIMIT 1").fetchone()[0])

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO raw_record_correspondent (record_id, correspondent_id, role) "
            "VALUES (?, ?, 'bcc')",
            (record, correspondent),
        )
    connection.close()
