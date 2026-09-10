"""Rename and removal detection (FR-012, FR-013).

Both are heuristics over set differences, and neither can distinguish a rename from one
source removed and another added. So both *warn* — which is what FR-013 asks for — and
neither ever re-associates records with a different name or deletes anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import findings as f
from .state import SourceStateStore


@dataclass(frozen=True, slots=True)
class UnconfiguredSource:
    name: str
    record_count: int


def unconfigured_with_records(
    store: SourceStateStore, configured: frozenset[str]
) -> tuple[UnconfiguredSource, ...]:
    """Sources holding records that the configuration no longer names (FR-012)."""
    orphaned = sorted(store.known_source_names() - configured)
    return tuple(
        UnconfiguredSource(name, store.record_count(name)) for name in orphaned
    )


def detect(
    store: SourceStateStore, configured: frozenset[str]
) -> list[f.Finding]:
    """Report orphaned records and possible renames. Never deletes, never re-links."""
    problems: list[f.Finding] = []
    known = store.known_source_names()

    for orphan in unconfigured_with_records(store, configured):
        problems.append(
            f.warning(
                f.UNCONFIGURED_SOURCE_HAS_RECORDS,
                f"the store holds {orphan.record_count:,} records for {orphan.name!r}, "
                "which the configuration no longer names",
                source_name=orphan.name,
                remedy=(
                    "Nothing has been deleted. Re-add the source to keep reading it, "
                    "or leave it — its records stay queryable either way."
                ),
            )
        )

    # A configured name the store has never seen, while some stored name is no longer
    # configured, is the shape a rename leaves behind. It is also the shape of a genuine
    # add-plus-remove, which is why this warns rather than acts.
    orphaned_names = known - configured
    if orphaned_names:
        for name in sorted(configured - known):
            problems.append(
                f.warning(
                    f.SOURCE_RENAMED,
                    f"{name!r} is not in the store; if you renamed it, it will be read "
                    "from the beginning",
                    source_name=name,
                    remedy=(
                        "A source's name is its identity in the store. Renaming one "
                        "starts it over rather than re-linking its records."
                    ),
                )
            )
    return problems
