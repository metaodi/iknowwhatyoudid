"""User Story 3 — corrections are never lost (FR-017 to FR-019, FR-032 to FR-034)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import make_batch, make_record
from iknowwhatyoudid.corrections import portable
from iknowwhatyoudid.corrections import repository as corrections_repo
from iknowwhatyoudid.corrections.model import Correction, ImportOutcome
from iknowwhatyoudid.derived import repository as derived_repo
from iknowwhatyoudid.errors import IkwydError
from iknowwhatyoudid.records import repository as repo
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate

HOUR = 3_600_000_000


def _seeded(store: sqlite3.Connection) -> None:
    repo.ingest(
        store, make_batch("mail", records=[make_record("a"), make_record("b", day=2)])
    )
    corrections_repo.record(
        store, source="mail", source_id="a", project="acme", made_at_utc=HOUR
    )
    corrections_repo.record(
        store, source="mail", source_id="b", project=None, note="personal", made_at_utc=HOUR
    )


def test_correction_wins_over_an_inferred_attribution(store: sqlite3.Connection) -> None:
    """FR-019, Principle V — an inference is never presented as an established fact."""
    _seeded(store)
    record_id = repo.query(store, source="mail")[0].id
    derived_repo.add(
        store, record_id=record_id, project="wrong-guess", rule="r", evidence={}
    )

    project, from_user = corrections_repo.project_for(store, "mail", "a")
    assert project == "acme"
    assert from_user is True

    project, from_user = corrections_repo.project_for(store, "mail", "unknown")
    assert from_user is False


def test_corrections_survive_discarding_derived(store: sqlite3.Connection) -> None:
    """FR-017, path 1 of 3."""
    _seeded(store)
    derived_repo.discard(store)
    assert corrections_repo.count(store) == 2
    assert corrections_repo.get(store, "mail", "a").project == "acme"  # type: ignore[union-attr]


def test_corrections_survive_a_migration(
    store: sqlite3.Connection, store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-017, path 2 of 3."""
    _seeded(store)
    before = corrections_repo.count(store)

    def upgrade(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE raw_scratch (x INTEGER)")

    extra = migrate.MigrationStep(2, "m0002_test", upgrade)
    monkeypatch.setattr(migrate, "discover", lambda: (*_original_steps(), extra))

    migrate.migrate(store, store_path)

    assert conn.user_version(store) == 2
    assert corrections_repo.count(store) == before
    assert corrections_repo.get(store, "mail", "a").project == "acme"  # type: ignore[union-attr]


def _original_steps() -> tuple[migrate.MigrationStep, ...]:
    from iknowwhatyoudid.store.migrations import m0001_initial

    return (migrate.MigrationStep(1, "m0001_initial", m0001_initial.upgrade),)


def test_corrections_survive_delete_and_rebuild(tmp_path: Path) -> None:
    """FR-017, path 3 of 3 — the hardest one: every internal id changes.

    This is why corrections are keyed by ``(source, source_id)`` and never by row id.
    """
    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    _seeded(connection)

    exported = list(portable.export(connection))
    connection.close()
    path.unlink()

    rebuilt = conn.connect(path)
    migrate.migrate(rebuilt, path)
    repo.ingest(
        rebuilt, make_batch("mail", records=[make_record("a"), make_record("b", day=2)])
    )
    report = portable.import_corrections(rebuilt, portable.parse(exported))
    corrections_repo.refresh_pending(rebuilt)

    assert len(report.new) == 2
    assert corrections_repo.count(rebuilt) == 2
    restored = corrections_repo.get(rebuilt, "mail", "a")
    assert restored is not None and restored.project == "acme"
    assert not restored.pending, "the record is present, so it is not pending"
    rebuilt.close()


def test_export_import_round_trip_is_identical(store: sqlite3.Connection, tmp_path: Path) -> None:
    """The test that keeps the portable format honest."""
    _seeded(store)
    exported = list(portable.export(store))

    empty_path = tmp_path / "other.db"
    other = conn.connect(empty_path)
    migrate.migrate(other, empty_path)
    portable.import_corrections(other, portable.parse(exported))

    assert list(portable.export(other)) == exported
    other.close()


def test_a_correction_for_an_absent_record_is_kept_as_pending(
    store: sqlite3.Connection,
) -> None:
    """FR-018 — retained and reported, never dropped."""
    incoming = Correction(
        source="mail", source_id="not-here", project="acme", note=None, made_at_utc=HOUR
    )
    report = portable.import_corrections(store, [incoming])

    assert len(report.pending) == 1
    stored = corrections_repo.get(store, "mail", "not-here")
    assert stored is not None and stored.pending


def test_pending_clears_when_the_record_arrives(store: sqlite3.Connection) -> None:
    """FR-018 — with no user action."""
    portable.import_corrections(
        store,
        [Correction("mail", "later", "acme", None, made_at_utc=HOUR)],
    )
    assert corrections_repo.get(store, "mail", "later").pending  # type: ignore[union-attr]

    repo.ingest(store, make_batch("mail", records=[make_record("later")]))
    corrections_repo.refresh_pending(store)

    assert not corrections_repo.get(store, "mail", "later").pending  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("incoming_made_at", "expected_outcome", "expected_project"),
    [
        (2 * HOUR, ImportOutcome.REPLACED, "imported"),
        (HOUR // 2, ImportOutcome.DECLINED, "local"),
        (HOUR, ImportOutcome.DECLINED, "local"),  # FR-033 tie-break keeps the local one
    ],
)
def test_import_conflicts_resolve_newest_wins(
    store: sqlite3.Connection,
    incoming_made_at: int,
    expected_outcome: ImportOutcome,
    expected_project: str,
) -> None:
    """FR-033."""
    repo.ingest(store, make_batch("mail", records=[make_record("a")]))
    corrections_repo.record(
        store, source="mail", source_id="a", project="local", made_at_utc=HOUR
    )

    report = portable.import_corrections(
        store, [Correction("mail", "a", "imported", None, made_at_utc=incoming_made_at)]
    )

    assert report.decisions[0].outcome is expected_outcome
    assert corrections_repo.get(store, "mail", "a").project == expected_project  # type: ignore[union-attr]


def test_every_replacement_and_refusal_is_named(store: sqlite3.Connection) -> None:
    """FR-034 — the guarantee that can actually be made: nothing changes silently."""
    repo.ingest(
        store, make_batch("mail", records=[make_record("a"), make_record("b", day=2)])
    )
    corrections_repo.record(store, source="mail", source_id="a", project="local-a", made_at_utc=HOUR)
    corrections_repo.record(store, source="mail", source_id="b", project="local-b", made_at_utc=HOUR)

    report = portable.import_corrections(
        store,
        [
            Correction("mail", "a", "newer", None, made_at_utc=2 * HOUR),
            Correction("mail", "b", "older", None, made_at_utc=HOUR // 2),
        ],
    )

    replaced = report.replaced[0]
    assert replaced.existing is not None and replaced.existing.project == "local-a"
    assert replaced.imported.project == "newer"

    declined = report.declined[0]
    assert declined.existing is not None and declined.existing.project == "local-b"
    assert declined.imported.project == "older"


def test_dry_run_changes_nothing(store: sqlite3.Connection) -> None:
    repo.ingest(store, make_batch("mail", records=[make_record("a")]))
    corrections_repo.record(store, source="mail", source_id="a", project="local", made_at_utc=HOUR)

    report = portable.import_corrections(
        store,
        [Correction("mail", "a", "imported", None, made_at_utc=2 * HOUR)],
        dry_run=True,
    )

    assert len(report.replaced) == 1, "it still reports what it would do"
    assert corrections_repo.get(store, "mail", "a").project == "local"  # type: ignore[union-attr]


def test_made_at_is_always_utc_on_the_wire(store: sqlite3.Connection) -> None:
    """Two machines in different zones must order corrections consistently (FR-032)."""
    _seeded(store)
    line = next(iter(portable.export(store)))
    assert '"made_at"' in line
    assert line.count("Z") >= 1
    assert portable.from_line(line).made_at_utc == HOUR


def test_an_unknown_format_version_is_refused(store: sqlite3.Connection) -> None:
    with pytest.raises(IkwydError):
        portable.from_line('{"v": 99, "source": "m", "source_id": "a", "made_at": "2026-01-01T00:00:00Z"}')


def test_a_malformed_line_names_its_line_number(store: sqlite3.Connection) -> None:
    with pytest.raises(IkwydError, match="line 2"):
        portable.parse(['{"v":1,"source":"m","source_id":"a","made_at":"2026-01-01T00:00:00Z"}', "{nonsense"])
