"""User Story 1 — a durable place for a day's traces, plus the record-layer invariants."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import make_batch, make_record, sweep
from iknowwhatyoudid.errors import BatchError, StoreLockedError
from iknowwhatyoudid.protection.permissions import PermissionStatus, check
from iknowwhatyoudid.records import repository as repo
from iknowwhatyoudid.records import timestamps
from iknowwhatyoudid.records.model import Batch, RunMode
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate, stats


def test_store_is_created_on_first_use(tmp_path: Path) -> None:
    """Scenario 1: a store appears with no setup step, and its location is knowable."""
    path = tmp_path / "nested" / "store.db"
    assert not path.exists()

    connection = conn.connect(path)
    migrate.migrate(connection, path)

    assert path.exists()
    assert conn.user_version(connection) == 1
    connection.close()


def test_new_store_is_not_world_readable(tmp_path: Path) -> None:
    """FR-005. Never asserts OWNER_ONLY where the platform cannot verify it."""
    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    connection.close()
    assert check(path).status is not PermissionStatus.OTHERS_CAN_READ


def test_records_go_in_and_come_back_with_evidence(store: sqlite3.Connection) -> None:
    """Scenario 4: every record traces back to its source, id, time and payload."""
    repo.ingest(store, make_batch("mail", records=[make_record("m1", title="hello")]))

    found = repo.query(store, source="mail")
    assert len(found) == 1
    record = found[0]
    assert record.source == "mail"
    assert record.source_id == "m1"
    assert record.title == "hello"
    assert record.payload == {"body": "x"}
    assert record.ingestion_run > 0


def test_query_filters_by_day_and_source(store: sqlite3.Connection) -> None:
    repo.ingest(
        store,
        make_batch("mail", records=[make_record("a", day=1), make_record("b", day=5)]),
    )
    repo.ingest(store, make_batch("git", records=[make_record("c", day=1)]))

    day_one = repo.query(store, since=datetime(2026, 3, 1, tzinfo=UTC), until=datetime(2026, 3, 1, 23, 59, tzinfo=UTC))
    assert {r.source_id for r in day_one} == {"a", "c"}
    assert {r.source_id for r in repo.query(store, source="mail")} == {"a", "b"}


def test_store_info_reports_counts_span_and_last_ingestion(
    store: sqlite3.Connection, store_path: Path
) -> None:
    """Scenario 2."""
    repo.ingest(
        store,
        make_batch("mail", records=[make_record("a", day=1), make_record("b", day=9)]),
    )
    gathered = stats.gather(store, store_path, 1)

    assert [s.name for s in gathered.sources] == ["mail"]
    source = gathered.sources[0]
    assert source.records == 2
    assert source.earliest_utc is not None and source.latest_utc is not None
    assert source.earliest_utc < source.latest_utc
    assert source.last_ingested_utc is not None


def test_reingesting_creates_no_duplicates(store: sqlite3.Connection) -> None:
    """FR-011, SC-005 — a full re-run and an overlapping range both upsert."""
    batch = make_batch("mail", records=[make_record("a"), make_record("b", day=2)])
    repo.ingest(store, batch)
    repo.ingest(store, batch)
    overlapping = make_batch(
        "mail", records=[make_record("b", day=2), make_record("c", day=3)]
    )
    repo.ingest(store, overlapping)

    assert repo.record_count(store, "mail") == 3


def test_changed_content_is_a_new_revision_not_a_new_record(
    store: sqlite3.Connection,
) -> None:
    """FR-014."""
    repo.ingest(store, make_batch("mail", records=[make_record("a", title="first")]))
    repo.ingest(store, make_batch("mail", records=[make_record("a", title="second")]))

    found = repo.query(store, source="mail")
    assert len(found) == 1
    assert found[0].title == "second"
    assert found[0].revision == 2


def test_source_without_an_id_gets_a_stable_derived_one(
    store: sqlite3.Connection,
) -> None:
    """FR-009 — so that FR-011 still holds for such sources."""
    batch = make_batch("git", records=[make_record(None, title="commit")])
    repo.ingest(store, batch)
    repo.ingest(store, batch)

    found = repo.query(store, source="git")
    assert len(found) == 1
    assert found[0].source_id_is_derived
    assert found[0].source_id.startswith("derived:")


def test_resumption_point_advances_only_within_a_committed_batch(
    store: sqlite3.Connection,
) -> None:
    """FR-012, FR-013."""
    assert repo.resumption_point(store, "mail") is None
    repo.ingest(store, make_batch("mail", records=[make_record("a", day=4)]))
    first = repo.resumption_point(store, "mail")
    assert first is not None

    repo.ingest(store, make_batch("mail", records=[make_record("b", day=2)]))
    assert repo.resumption_point(store, "mail") == first, "must never move backwards"


def test_interrupted_batch_leaves_nothing_behind(
    store: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-013, SC-010 — a batch is fully applied or not applied at all."""
    repo.ingest(store, make_batch("mail", records=[make_record("a")]))
    before = repo.record_count(store, "mail")
    runs_before = int(store.execute("SELECT count(*) FROM raw_ingestion_run").fetchone()[0])

    boom = make_batch("mail", records=[make_record("b", day=2), make_record("c", day=3)])
    original = repo._withdraw_missing

    def explode(*args: object, **kwargs: object) -> int:
        raise RuntimeError("killed mid-batch")

    monkeypatch.setattr(timestamps, "now_micros", explode)
    with pytest.raises(RuntimeError):
        repo.ingest(store, boom, started_at_utc=1)

    monkeypatch.undo()
    assert repo.record_count(store, "mail") == before
    assert int(store.execute("SELECT count(*) FROM raw_ingestion_run").fetchone()[0]) == runs_before
    assert original is repo._withdraw_missing


# --- Withdrawal (FR-027 to FR-029) --------------------------------------------------
# The negative case first: it is the bug RunMode exists to prevent.


def test_incremental_run_never_withdraws_anything(store: sqlite3.Connection) -> None:
    """Without the RunMode gate this marks every record outside the window withdrawn."""
    repo.ingest(
        store,
        make_batch("mail", records=[make_record("a"), make_record("b", day=2)]),
    )
    result = repo.ingest(
        store, make_batch("mail", mode=RunMode.INCREMENTAL, records=[make_record("c", day=3)])
    )

    assert result.withdrawn == 0
    assert all(not r.withdrawn for r in repo.query(store, include_withdrawn=True))


def test_sweep_withdraws_only_inside_its_window(store: sqlite3.Connection) -> None:
    repo.ingest(
        store,
        make_batch(
            "mail",
            records=[make_record("a", day=1), make_record("b", day=2), make_record("z", day=28)],
        ),
    )
    result = repo.ingest(
        store,
        sweep(
            "mail",
            [make_record("a", day=1)],
            frozenset({"a"}),
            range_from=datetime(2026, 3, 1, tzinfo=UTC),
            range_to=datetime(2026, 3, 3, tzinfo=UTC),
        ),
    )

    assert result.withdrawn == 1
    by_id = {r.source_id: r for r in repo.query(store, include_withdrawn=True)}
    assert by_id["b"].withdrawn, "inside the window and unseen"
    assert not by_id["z"].withdrawn, "outside the window — the sweep never looked"


def test_withdrawal_never_reduces_the_record_count(store: sqlite3.Connection) -> None:
    """SC-011 — marked, never deleted."""
    repo.ingest(store, make_batch("mail", records=[make_record("a"), make_record("b", day=2)]))
    before = repo.record_count(store, "mail")

    repo.ingest(
        store,
        sweep(
            "mail",
            [],
            frozenset(),
            range_from=datetime(2026, 3, 1, tzinfo=UTC),
            range_to=datetime(2026, 3, 3, tzinfo=UTC),
        ),
    )
    assert repo.record_count(store, "mail") == before


def test_withdrawn_records_are_hidden_by_default_and_available_on_request(
    store: sqlite3.Connection,
) -> None:
    """FR-028."""
    repo.ingest(store, make_batch("mail", records=[make_record("a"), make_record("b", day=2)]))
    repo.ingest(
        store,
        sweep(
            "mail",
            [make_record("a")],
            frozenset({"a"}),
            range_from=datetime(2026, 3, 1, tzinfo=UTC),
            range_to=datetime(2026, 3, 3, tzinfo=UTC),
        ),
    )

    assert {r.source_id for r in repo.query(store)} == {"a"}
    assert {r.source_id for r in repo.query(store, include_withdrawn=True)} == {"a", "b"}


def test_reappearing_record_clears_its_withdrawal(store: sqlite3.Connection) -> None:
    """FR-029 — no second row."""
    repo.ingest(store, make_batch("mail", records=[make_record("a"), make_record("b", day=2)]))
    repo.ingest(
        store,
        sweep(
            "mail",
            [make_record("a")],
            frozenset({"a"}),
            range_from=datetime(2026, 3, 1, tzinfo=UTC),
            range_to=datetime(2026, 3, 3, tzinfo=UTC),
        ),
    )
    result = repo.ingest(store, make_batch("mail", records=[make_record("b", day=2)]))

    assert result.unwithdrawn == 1
    assert repo.record_count(store, "mail") == 2
    assert all(not r.withdrawn for r in repo.query(store, include_withdrawn=True))


@pytest.mark.parametrize(
    "batch",
    [
        Batch(source="m", mode=RunMode.SWEEP, records=[]),
        Batch(source="m", mode=RunMode.SWEEP, range_from=datetime(2026, 1, 1, tzinfo=UTC)),
        Batch(source="m", seen_source_ids=frozenset({"a"})),
        Batch(source=""),
    ],
)
def test_batch_contract_violations_are_rejected(batch: Batch) -> None:
    with pytest.raises(BatchError):
        batch.validate()


# --- Future-dated (FR-035 to FR-038) ------------------------------------------------


def test_future_dated_record_is_stored_unmodified(store: sqlite3.Connection) -> None:
    """FR-035 — rewriting the time would destroy the evidence that a clock is wrong."""
    future = make_record("f", year=2099, title="next century")
    repo.ingest(store, make_batch("mail", records=[future]))

    found = repo.query(store, source="mail")[0]
    assert found.occurred_utc > 0
    from iknowwhatyoudid.records import timestamps

    assert timestamps.from_storage(
        found.occurred_utc, found.occurred_offset_minutes, found.occurred_zone
    ).year == 2099


def test_not_yet_elapsed_records_are_excluded_then_counted(
    store: sqlite3.Connection,
) -> None:
    """FR-036, FR-037, SC-013 — it becomes countable with nothing re-ingested."""
    from iknowwhatyoudid.records import timestamps

    repo.ingest(
        store,
        make_batch("cal", records=[make_record("past", day=1), make_record("soon", year=2099)]),
    )
    all_records = repo.query(store, source="cal")
    assert len(all_records) == 2

    assert {r.source_id for r in repo.elapsed(all_records)} == {"past"}

    later = timestamps.to_utc_micros(datetime(2100, 1, 1, tzinfo=UTC))
    assert {r.source_id for r in repo.elapsed(all_records, at=later)} == {"past", "soon"}


def test_future_dated_count_makes_a_wrong_clock_visible(
    store: sqlite3.Connection, store_path: Path
) -> None:
    """FR-038."""
    repo.ingest(
        store,
        make_batch("mail", records=[make_record("ok", day=1), make_record("skewed", year=2099)]),
    )
    gathered = stats.gather(store, store_path, 1)
    assert gathered.sources[0].future_dated == 1


# --- Concurrency and corruption (FR-025, FR-026) ------------------------------------


def test_a_second_writer_fails_clearly_rather_than_corrupting(
    store: sqlite3.Connection, store_path: Path
) -> None:
    """FR-025."""
    other = conn.connect(store_path, busy_timeout_ms=200)
    store.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(StoreLockedError):
            with conn.writing(other):
                other.execute("DELETE FROM raw_record")
    finally:
        store.execute("ROLLBACK")
        other.close()


def test_a_file_that_is_not_a_store_is_reported_and_left_alone(tmp_path: Path) -> None:
    """FR-026 — a corrupt store may be the only copy of unregenerable data."""
    from iknowwhatyoudid.errors import StoreCorruptError

    impostor = tmp_path / "store.db"
    original = b"this is definitely not a database" * 20
    impostor.write_bytes(original)

    with pytest.raises(StoreCorruptError) as caught:
        conn.connect(impostor)

    assert str(impostor) in caught.value.message
    assert caught.value.remedy is not None, "a recovery step must be stated"
    assert impostor.read_bytes() == original, "the file must not be touched"


def test_a_truncated_store_is_reported_and_left_alone(tmp_path: Path) -> None:
    """The other half of FR-026: a real store, damaged."""
    from iknowwhatyoudid.errors import StoreCorruptError
    from iknowwhatyoudid.store import integrity

    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    repo.ingest(connection, make_batch("mail", records=[make_record("a")]))
    connection.close()

    intact = path.read_bytes()
    path.write_bytes(intact[: len(intact) // 3])
    damaged = path.read_bytes()

    try:
        connection = conn.connect(path)
        report = integrity.check_quick(connection, path)
        connection.close()
        assert not report.ok
        with pytest.raises(StoreCorruptError):
            integrity.raise_if_corrupt(report)
    except StoreCorruptError:
        pass  # detected at open, which is equally acceptable

    assert path.read_bytes() == damaged, "the tool must not repair or delete it"
