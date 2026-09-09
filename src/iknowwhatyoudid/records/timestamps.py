"""Storing time so instant *and* zone are both recoverable (FR-007).

Three columns rather than one: an integer instant that sorts and ranges correctly, the
offset the source actually expressed, and the IANA zone name where the source gives one
— which is the only thing that resolves a moment inside a daylight-saving repeated hour.

Also home to the two *derived* future-dated properties. Neither is stored: a stored flag
computed at ingestion would go stale, and FR-037 requires a record to become countable
once its time passes with no re-ingestion. See research.md R7.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..errors import BatchError

MICROSECONDS = 1_000_000


def to_utc_micros(moment: datetime) -> int:
    """Microseconds since the Unix epoch. Rejects a naive datetime rather than guessing."""
    if moment.tzinfo is None:
        raise BatchError(
            f"{moment.isoformat()} has no time zone",
            remedy=(
                "Connectors must supply timezone-aware times. A naive datetime is not "
                "assumed to be local, because that guess is invisible once stored."
            ),
        )
    return int(moment.timestamp() * MICROSECONDS)


def offset_minutes(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise BatchError(f"{moment.isoformat()} has no time zone")
    delta = moment.utcoffset() or timedelta(0)
    return int(delta.total_seconds() // 60)


def zone_name(moment: datetime) -> str | None:
    """The IANA zone name, when the source expressed one."""
    info = moment.tzinfo
    key = getattr(info, "key", None)
    return str(key) if key else None


def from_storage(
    occurred_utc: int, offset: int, zone: str | None
) -> datetime:
    """Rebuild the moment as the source expressed it."""
    instant = datetime.fromtimestamp(occurred_utc / MICROSECONDS, tz=UTC)
    if zone:
        try:
            return instant.astimezone(ZoneInfo(zone))
        except (ZoneInfoNotFoundError, ValueError):
            pass  # fall through to the raw offset
    return instant.astimezone(timezone(timedelta(minutes=offset)))


def duration_micros(duration: timedelta | None) -> int | None:
    if duration is None:
        return None
    micros = int(duration.total_seconds() * MICROSECONDS)
    if micros < 0:
        raise BatchError("a record's duration cannot be negative")
    return micros


def now_micros() -> int:
    return int(datetime.now(tz=UTC).timestamp() * MICROSECONDS)


def was_future_at_ingestion(occurred_utc: int, run_started_at_utc: int) -> bool:
    """A permanent data-quality signal about a possibly-wrong source clock (FR-038).

    Immutable: it compares against the ingestion run, not against now.
    """
    return occurred_utc > run_started_at_utc


def not_yet_elapsed(occurred_utc: int, at: int | None = None) -> bool:
    """Whether the moment is still ahead of us (FR-036, FR-037).

    Evaluated per query, which is what lets a record start counting the instant its time
    passes without anything being re-ingested.
    """
    return occurred_utc > (now_micros() if at is None else at)
