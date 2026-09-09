"""User Story 2 — change the guesses without re-downloading the year (FR-010, FR-015, FR-016)."""

from __future__ import annotations

import socket
import sqlite3

import pytest

from conftest import make_batch, make_record
from iknowwhatyoudid.corrections import repository as corrections_repo
from iknowwhatyoudid.derived import repository as derived_repo
from iknowwhatyoudid.records import repository as repo
from iknowwhatyoudid.store import stats


def _populate(store: sqlite3.Connection) -> list[int]:
    repo.ingest(
        store,
        make_batch("mail", records=[make_record("a"), make_record("b", day=2)]),
    )
    ids = [r.id for r in repo.query(store, source="mail")]
    for index, record_id in enumerate(ids):
        derived_repo.add(
            store,
            record_id=record_id,
            project=f"p{index}",
            rule="first-guess",
            evidence={"why": "test"},
        )
    return ids


def test_discarding_derived_leaves_raw_and_corrections_untouched(
    store: sqlite3.Connection,
) -> None:
    """FR-010 — three separately addressable regions."""
    _populate(store)
    corrections_repo.record(store, source="mail", source_id="a", project="acme")

    assert derived_repo.count(store) == 2
    removed = derived_repo.discard(store)

    assert removed == 2
    assert derived_repo.count(store) == 0
    assert repo.record_count(store, "mail") == 2, "raw records untouched"
    assert corrections_repo.count(store) == 1, "corrections untouched"


def test_rederivation_reads_from_no_source_and_no_network(
    store: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-015, SC-002 — the property that makes iterating on attribution affordable."""
    ids = _populate(store)
    derived_repo.discard(store)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("re-derivation reached for the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    # Everything a re-derivation needs is already in the raw region.
    for record in repo.query(store, source="mail"):
        derived_repo.add(
            store,
            record_id=record.id,
            project="second-guess",
            rule="revised",
            evidence={"title": record.title},
        )

    assert derived_repo.count(store) == len(ids)


def test_rederivation_is_deterministic(store: sqlite3.Connection) -> None:
    """The same raw records and the same rule produce the same result twice."""

    def derive() -> list[tuple[str, str]]:
        derived_repo.discard(store)
        for record in repo.query(store, source="mail"):
            derived_repo.add(
                store,
                record_id=record.id,
                project=record.title.upper(),
                rule="uppercase-title",
                evidence={"from": record.source_id},
                derived_at_utc=0,
            )
        return [
            (a.project, a.rule)
            for record in repo.query(store, source="mail")
            for a in derived_repo.for_record(store, record.id)
        ]

    _populate(store)
    assert derive() == derive()


def test_discarding_raw_cascades_derived_but_spares_corrections(
    store: sqlite3.Connection,
) -> None:
    """FR-010 — the irreplaceable region does not share a code path with the others."""
    _populate(store)
    corrections_repo.record(store, source="mail", source_id="a", project="acme")

    repo.discard_raw(store)

    assert repo.record_count(store, "mail") == 0
    assert derived_repo.count(store) == 0, "cascaded"
    assert corrections_repo.count(store) == 1, "corrections are never collateral"


def test_rebuild_names_every_record_the_sources_no_longer_expose(
    store: sqlite3.Connection,
) -> None:
    """FR-016 — a gap that is reported rather than one that is silent."""
    repo.ingest(
        store,
        make_batch("mail", records=[make_record("a"), make_record("gone", day=2)]),
    )
    before = stats.census(store)

    repo.discard_raw(store)
    repo.ingest(store, make_batch("mail", records=[make_record("a")]))

    report = stats.rebuild_report(store, before)
    assert report.count == 1
    assert report.missing == (("mail", "gone"),)
