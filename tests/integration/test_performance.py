"""SC-008 — store info in under 5 seconds over a year of records."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from iknowwhatyoudid.records.model import Batch, NormalizedRecord
from iknowwhatyoudid.records import repository as repo
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate, stats

YEAR_OF_RECORDS = 60_000
BUDGET_SECONDS = 5.0


def test_store_info_over_a_year_of_records(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)

    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    for source, share in (("mail", 0.6), ("calendar", 0.1), ("git", 0.3)):
        count = int(YEAR_OF_RECORDS * share)
        repo.ingest(
            connection,
            Batch(
                source=source,
                records=[
                    NormalizedRecord(
                        source_id=f"{source}-{index}",
                        occurred=start + timedelta(minutes=index * 7),
                        title=f"record {index}",
                        payload={"n": index},
                    )
                    for index in range(count)
                ],
            ),
        )

    began = time.perf_counter()
    gathered = stats.gather(connection, path, 1)
    elapsed = time.perf_counter() - began

    assert gathered.records == YEAR_OF_RECORDS
    assert elapsed < BUDGET_SECONDS, f"store info took {elapsed:.2f}s (budget {BUDGET_SECONDS}s)"
    connection.close()


def test_the_partial_index_is_used_for_the_common_query(tmp_path: Path) -> None:
    """The five-second budget is an index question, not an engine question."""
    path = tmp_path / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)

    plan = connection.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM raw_record "
        "WHERE source = ? AND occurred_utc >= ? AND withdrawn_on_utc IS NULL",
        ("mail", 0),
    ).fetchall()
    detail = " ".join(str(row["detail"]) for row in plan)

    assert "raw_record_live" in detail, detail
    connection.close()
