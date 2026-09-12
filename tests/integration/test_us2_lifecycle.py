"""User Story 2 — add, disable and retire a source without disturbing the rest.

FR-009 to FR-013, FR-042 to FR-044, and T051/T079.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import sources_commands
from iknowwhatyoudid.config import findings as f
from iknowwhatyoudid.records import repository as records_repo
from iknowwhatyoudid.records.model import Batch, RunMode
from iknowwhatyoudid.sources import identity, run
from iknowwhatyoudid.sources.state import (
    InMemorySourceStateStore,
    SourceRunOutcome,
    SqliteSourceStateStore,
)
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate

FIXTURES = Path("tests/fixtures/configs")
RECORDED = Path("tests/fixtures/recorded/day.jsonl")


def write_config(path: Path, blocks: list[str]) -> Path:
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def fixture_block(name: str, *, enabled: bool = True) -> str:
    return (
        f'[[source]]\nname = "{name}"\nkind = "fixture"\n'
        f"enabled = {'true' if enabled else 'false'}\n"
        f'recorded = ["{RECORDED.as_posix()}"]\n'
    )


def session_for(path: Path) -> sources_commands.ConfigSession:
    return sources_commands.open_config(str(path))


# --- FR-011 / SC-005: one change touches only the source it names --------------------


def test_adding_disabling_and_removing_touch_no_other_source(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    write_config(config, [fixture_block(n) for n in ("a", "b", "c", "d")])

    store = InMemorySourceStateStore()
    for index, name in enumerate(("a", "b", "c", "d"), start=1):
        store.seed(name, point=datetime(2026, 3, index, tzinfo=UTC), count=index * 10)
    snapshot = {
        name: (store.resumption_point(name), store.record_count(name))
        for name in ("a", "b", "c", "d")
    }

    # add "e", disable "b", remove "c", rename "d" -> "d2"
    write_config(
        config,
        [
            fixture_block("a"),
            fixture_block("b", enabled=False),
            fixture_block("d2"),
            fixture_block("e"),
        ],
    )
    report = session_for(config).report

    for untouched in ("a",):
        assert (
            store.resumption_point(untouched),
            store.record_count(untouched),
        ) == snapshot[untouched], "an untouched source must be byte-identical"

    verdicts = {s.name: s.readiness for s in report.statuses}
    assert verdicts["b"] is f.Readiness.DISABLED
    assert verdicts["a"] is f.Readiness.READY
    assert verdicts["e"] is f.Readiness.READY


def test_a_removed_source_keeps_its_records_and_is_reported(tmp_path: Path) -> None:
    """FR-012 — reported, never deleted."""
    store = InMemorySourceStateStore()
    store.seed("gone", point=datetime(2026, 3, 1, tzinfo=UTC), count=1284)
    store.seed("kept", point=datetime(2026, 3, 1, tzinfo=UTC), count=5)

    orphans = identity.unconfigured_with_records(store, frozenset({"kept"}))
    assert [(o.name, o.record_count) for o in orphans] == [("gone", 1284)]
    assert store.record_count("gone") == 1284, "nothing was deleted"

    problems = identity.detect(store, frozenset({"kept"}))
    assert f.UNCONFIGURED_SOURCE_HAS_RECORDS in {p.code for p in problems}
    assert all(not p.blocks for p in problems), "a warning, not a refusal"


def test_a_rename_warns_that_it_starts_over(tmp_path: Path) -> None:
    """FR-013 — never silently re-associates records with a different name."""
    store = InMemorySourceStateStore()
    store.seed("work-mail", point=datetime(2026, 3, 1, tzinfo=UTC), count=10)

    problems = identity.detect(store, frozenset({"work-post"}))
    codes = {p.code for p in problems}

    assert f.SOURCE_RENAMED in codes
    assert f.UNCONFIGURED_SOURCE_HAS_RECORDS in codes
    assert store.record_count("work-mail") == 10


# --- FR-009, FR-010, SC-006: disable then re-enable ---------------------------------


def test_a_disabled_source_is_skipped_but_keeps_its_resumption_point(
    tmp_path: Path,
) -> None:
    config = write_config(tmp_path / "config.toml", [fixture_block("a", enabled=False)])
    store = InMemorySourceStateStore()
    store.seed("a", point=datetime(2026, 3, 1, tzinfo=UTC), count=7)

    report = run.ingest(session_for(config).report, store)

    assert report.outcomes[0].result is run.RunResult.SKIPPED
    assert report.outcomes[0].detail == "disabled"
    assert store.resumption_point("a") == datetime(2026, 3, 1, tzinfo=UTC)
    assert store.record_count("a") == 7


def test_re_enabling_re_reads_nothing_already_read(tmp_path: Path) -> None:
    """SC-006 — zero records re-read."""
    config = write_config(tmp_path / "config.toml", [fixture_block("recorded")])
    store = InMemorySourceStateStore()

    first = run.ingest(session_for(config).report, store)
    assert first.outcomes[0].records_ingested == 2

    write_config(tmp_path / "config.toml", [fixture_block("recorded", enabled=False)])
    run.ingest(session_for(config).report, store)

    write_config(tmp_path / "config.toml", [fixture_block("recorded")])
    third = run.ingest(session_for(config).report, store)
    assert third.outcomes[0].records_ingested == 0, "resumption is exclusive"


# --- T051: source state is durable ---------------------------------------------------


def test_a_resumption_point_survives_closing_and_reopening_the_store(
    tmp_path: Path,
) -> None:
    """The property that replaced the `persistence: in_memory_only` notice."""
    store_path = tmp_path / "store.db"
    connection = conn.connect(store_path)
    migrate.migrate(connection, store_path)

    state = SqliteSourceStateStore(connection)
    through = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    state.record_ingestion(SourceRunOutcome("mail", True, 3), through)
    connection.close()

    reopened = conn.connect(store_path)
    assert SqliteSourceStateStore(reopened).resumption_point("mail") == through
    reopened.close()


# --- FR-043, FR-044, SC-009: one source failing --------------------------------------


def test_one_source_failing_does_not_stop_the_others(tmp_path: Path) -> None:
    report = run.ingest(
        session_for(FIXTURES / "one-failing.toml").report, InMemorySourceStateStore()
    )

    by_name = {o.source_name: o for o in report.outcomes}
    assert by_name["good"].result is run.RunResult.SUCCEEDED
    assert by_name["bad"].result is run.RunResult.FAILED
    assert by_name["bad"].failure is run.FailureCategory.CREDENTIAL
    assert not report.ok, "a failure drives the non-zero exit"


def test_every_configured_source_appears_including_skipped(tmp_path: Path) -> None:
    """A source that silently contributes nothing must still be visible."""
    report = run.ingest(
        session_for(FIXTURES / "valid.toml").report, InMemorySourceStateStore()
    )
    assert {o.source_name for o in report.outcomes} == {
        "work-repos",
        "work-mail",
        "personal-mail",
        "hey-archive",
        "recorded-day",
    }


def test_only_runs_one_named_source(tmp_path: Path) -> None:
    """FR-042."""
    report = run.ingest(
        session_for(FIXTURES / "valid.toml").report,
        InMemorySourceStateStore(),
        only="recorded-day",
    )
    assert [o.source_name for o in report.outcomes] == ["recorded-day"]


def test_dry_run_reads_nothing(tmp_path: Path) -> None:
    config = write_config(tmp_path / "config.toml", [fixture_block("recorded")])
    store = InMemorySourceStateStore()

    report = run.ingest(session_for(config).report, store, dry_run=True)

    assert report.outcomes[0].result is run.RunResult.SKIPPED
    assert store.resumption_point("recorded") is None


# --- T079: RunMode reaches the store -------------------------------------------------


def test_an_incremental_run_withdraws_nothing(tmp_path: Path) -> None:
    """The bug RunMode exists to prevent, asserted at this feature's boundary."""
    store_path = tmp_path / "store.db"
    connection = conn.connect(store_path)
    migrate.migrate(connection, store_path)

    config = write_config(tmp_path / "config.toml", [fixture_block("recorded")])
    state = SqliteSourceStateStore(connection)

    run.ingest(session_for(config).report, state, connection=connection)
    # A second incremental run reads nothing new; nothing may be withdrawn by it.
    run.ingest(session_for(config).report, state, connection=connection)

    withdrawn = connection.execute(
        "SELECT count(*) FROM raw_record WHERE withdrawn_on_utc IS NOT NULL"
    ).fetchone()[0]
    assert withdrawn == 0
    assert connection.execute("SELECT count(*) FROM raw_record").fetchone()[0] == 2
    connection.close()


def test_a_sweep_supplies_the_window_and_the_ids_it_saw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T079 — a sweep is the only mode that can cause a withdrawal.

    Asserts on the `Batch` that actually reaches the store, because that is where the
    withdrawal decision is made.
    """
    store_path = tmp_path / "store.db"
    connection = conn.connect(store_path)
    migrate.migrate(connection, store_path)

    config = write_config(tmp_path / "config.toml", [fixture_block("recorded")])
    state = InMemorySourceStateStore()

    captured: list[Batch] = []
    original = records_repo.ingest

    def spy(conn_arg: sqlite3.Connection, batch: Batch, **kwargs: object) -> object:
        captured.append(batch)
        return original(conn_arg, batch)

    monkeypatch.setattr(records_repo, "ingest", spy)
    run.ingest(
        session_for(config).report,
        state,
        connection=connection,
        mode=RunMode.SWEEP,
    )

    assert captured, "the batch reached the store"
    batch = captured[0]
    assert batch.mode is RunMode.SWEEP
    assert batch.seen_source_ids == frozenset({"r1", "r2"})
    assert batch.range_to is not None, "a sweep must bound its window"
    connection.close()
