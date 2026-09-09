"""Time storage (FR-007) and derived identifiers (FR-009)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from iknowwhatyoudid.errors import BatchError
from iknowwhatyoudid.records import identity, timestamps

ZURICH = ZoneInfo("Europe/Zurich")


def test_naive_datetime_is_rejected_not_guessed() -> None:
    """A naive time is not assumed to be local: that guess is invisible once stored."""
    with pytest.raises(BatchError):
        timestamps.to_utc_micros(datetime(2026, 3, 1, 9, 0))


def test_instant_and_offset_both_recoverable() -> None:
    moment = datetime(2026, 3, 1, 9, 0, tzinfo=ZURICH)
    micros = timestamps.to_utc_micros(moment)
    offset = timestamps.offset_minutes(moment)
    zone = timestamps.zone_name(moment)

    assert offset == 60
    assert zone == "Europe/Zurich"
    assert timestamps.from_storage(micros, offset, zone) == moment


def test_offset_only_still_round_trips_the_instant() -> None:
    moment = datetime(2026, 7, 1, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    micros = timestamps.to_utc_micros(moment)
    restored = timestamps.from_storage(micros, timestamps.offset_minutes(moment), None)
    assert restored == moment
    assert restored.utcoffset() == timedelta(hours=5, minutes=30)


def test_dst_repeated_hour_needs_the_zone_name() -> None:
    """Two distinct moments share a wall clock inside a DST fall-back hour.

    Only the zone name distinguishes them, which is why FR-007 stores it rather than
    just an offset.
    """
    first = datetime(2026, 10, 25, 2, 30, tzinfo=ZURICH, fold=0)
    second = datetime(2026, 10, 25, 2, 30, tzinfo=ZURICH, fold=1)

    first_micros = timestamps.to_utc_micros(first)
    second_micros = timestamps.to_utc_micros(second)
    assert first_micros != second_micros

    assert timestamps.offset_minutes(first) == 120
    assert timestamps.offset_minutes(second) == 60


def test_future_dated_is_two_distinct_questions() -> None:
    """FR-036 vs FR-037: one is fixed at ingestion, the other is evaluated now."""
    run_started = 1_000_000
    occurred = 2_000_000

    assert timestamps.was_future_at_ingestion(occurred, run_started) is True
    # Immutable — it never stops being true, because it describes the source's clock.
    assert timestamps.was_future_at_ingestion(occurred, run_started) is True

    # ... while "not yet elapsed" flips the moment its time arrives, with nothing
    # re-ingested. A stored flag could not do both.
    assert timestamps.not_yet_elapsed(occurred, at=1_500_000) is True
    assert timestamps.not_yet_elapsed(occurred, at=3_000_000) is False


def test_negative_duration_rejected() -> None:
    with pytest.raises(BatchError):
        timestamps.duration_micros(timedelta(seconds=-1))


def test_derived_id_is_stable_across_key_order() -> None:
    a = identity.derive_source_id("s", 1, "t", {"x": 1, "y": 2})
    b = identity.derive_source_id("s", 1, "t", {"y": 2, "x": 1})
    assert a == b
    assert identity.is_derived(a)


@pytest.mark.parametrize(
    "changed",
    [
        {"source": "other"},
        {"occurred_utc": 2},
        {"title": "different"},
        {"payload": {"x": 2}},
    ],
)
def test_derived_id_changes_with_content(changed: dict[str, object]) -> None:
    base = {"source": "s", "occurred_utc": 1, "title": "t", "payload": {"x": 1}}
    original = identity.derive_source_id(**base)  # type: ignore[arg-type]
    assert identity.derive_source_id(**{**base, **changed}) != original  # type: ignore[arg-type]


def test_derived_ids_are_prefixed() -> None:
    """The prefix keeps FR-014's 'same record, new revision' honest.

    A source-issued id survives a content change; a content-derived one cannot. The two
    cases must stay distinguishable rather than silently conflated.
    """
    assert identity.derive_source_id("s", 1, "t", {}).startswith(identity.DERIVED_PREFIX)
    assert not identity.is_derived("AAMkAGI2")


def test_now_is_timezone_aware_utc() -> None:
    assert abs(timestamps.now_micros() - int(datetime.now(UTC).timestamp() * 1e6)) < 5e6
