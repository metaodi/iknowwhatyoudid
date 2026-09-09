"""Shared fixtures. Every test runs against fixture batches — never a real account."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from iknowwhatyoudid.obs import logging as obs
from iknowwhatyoudid.records.model import Batch, NormalizedRecord, RunMode
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "store.db"


@pytest.fixture
def store(store_path: Path) -> Iterator[sqlite3.Connection]:
    connection = conn.connect(store_path)
    migrate.migrate(connection, store_path)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def _quiet_logging() -> Iterator[None]:
    obs.reset_for_tests()
    yield
    obs.reset_for_tests()


def make_record(
    source_id: str | None,
    *,
    day: int = 1,
    month: int = 3,
    year: int = 2026,
    hour: int = 9,
    title: str = "a record",
    payload: dict[str, Any] | None = None,
    duration: timedelta | None = None,
    tz: Any = UTC,
) -> NormalizedRecord:
    return NormalizedRecord(
        source_id=source_id,
        occurred=datetime(year, month, day, hour, 0, tzinfo=tz),
        title=title,
        payload={"body": "x"} if payload is None else payload,
        duration=duration,
    )


def make_batch(
    source: str = "fixture-mail",
    *,
    records: list[NormalizedRecord] | None = None,
    mode: RunMode = RunMode.INCREMENTAL,
    range_from: datetime | None = None,
    range_to: datetime | None = None,
    seen_source_ids: frozenset[str] | None = None,
) -> Batch:
    return Batch(
        source=source,
        mode=mode,
        records=records if records is not None else [make_record("a"), make_record("b", day=2)],
        range_from=range_from,
        range_to=range_to,
        seen_source_ids=seen_source_ids,
    )


def sweep(
    source: str,
    records: list[NormalizedRecord],
    seen: frozenset[str],
    *,
    range_from: datetime,
    range_to: datetime,
) -> Batch:
    return Batch(
        source=source,
        mode=RunMode.SWEEP,
        records=records,
        range_from=range_from,
        range_to=range_to,
        seen_source_ids=seen,
    )
