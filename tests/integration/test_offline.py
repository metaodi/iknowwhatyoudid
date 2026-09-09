"""No store operation may contact a network destination (FR-023, SC-001).

The assertion is on *socket creation*, not on output. A test that only checked results
would pass even if the tool phoned home.
"""

from __future__ import annotations

import socket
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import make_batch, make_record
from iknowwhatyoudid.corrections import portable
from iknowwhatyoudid.corrections import repository as corrections_repo
from iknowwhatyoudid.derived import repository as derived_repo
from iknowwhatyoudid.records import repository as repo
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate, stats


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a store operation opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.usefixtures("no_network")
def test_a_full_ingest_and_query_cycle_opens_no_socket(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)

    repo.ingest(
        connection,
        make_batch("mail", records=[make_record("a"), make_record("b", day=2)]),
    )
    corrections_repo.record(
        connection, source="mail", source_id="a", project="acme"
    )
    record_id = repo.query(connection, source="mail")[0].id
    derived_repo.add(
        connection, record_id=record_id, project="guess", rule="r1", evidence={}
    )

    assert len(repo.query(connection)) == 2
    assert stats.gather(connection, path, 1).records == 2
    assert list(portable.export(connection))
    connection.close()


@pytest.mark.usefixtures("no_network")
def test_previously_ingested_records_stay_queryable_offline(
    store: sqlite3.Connection,
) -> None:
    """SC-001 — 100% of ingested records remain queryable with no network."""
    repo.ingest(
        store,
        make_batch("mail", records=[make_record(f"r{n}", day=n) for n in range(1, 6)]),
    )
    found = repo.query(
        store,
        since=datetime(2026, 3, 1, tzinfo=UTC),
        until=datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert len(found) == 5
