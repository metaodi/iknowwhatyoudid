# Contract: The source-state port

**This is the boundary onto `0001-local-store-foundation`.** This feature depends on it through the
four operations below and nothing else.

**Status: implemented.** `0001` ships `SqliteSourceStateStore` in
`src/iknowwhatyoudid/sources/state.py`. The in-memory implementation is now a test double, and
`ingest` no longer needs to warn that state is not durable.

## Why a port exists here at all

The constitution reserves the storage-engine choice (SQLite or DuckDB) for "the first storage feature's
`plan.md`" — that is `0001`'s plan, not this one. This feature nonetheless needs a source's resumption
point (FR-010), its ingestion history, and the set of sources holding records but absent from the
configuration (FR-012).

Three options existed. Opening a database here would make the engine choice in the wrong feature's plan.
Waiting for `0001` would block this feature on unscheduled work. A side file would create a second store,
which Principle IV forbids. The port is the fourth: it lets this feature be built and fully tested now,
against an in-memory implementation, while leaving the decision exactly where the constitution puts it.

This is the one abstraction in this feature with a single current caller, and it is recorded as such in
[plan.md](../plan.md) Complexity Tracking.

## The interface

```python
class SourceStateStore(Protocol):
    def resumption_point(self, source_name: str) -> datetime | None:
        """Where the last completed ingestion of this source stopped, or None if never read."""

    def record_ingestion(self, outcome: SourceRunOutcome, through: datetime | None) -> None:
        """Persist the outcome of one source's ingestion, advancing its resumption point
        only when the run completed."""

    def known_source_names(self) -> frozenset[str]:
        """Every source name holding records in the store — including ones no longer configured."""

    def record_count(self, source_name: str) -> int:
        """How many records this source has contributed. Used to report FR-012 honestly."""
```

Four operations, no query language, no transaction surface, no record access. The narrowness is
deliberate: this port must not become a general-purpose data-access layer, and it should be obvious at a
glance that it has not.

## What this feature builds against it

| Requirement | Operation |
|-------------|-----------|
| FR-010 — re-enabling resumes rather than re-reading | `resumption_point` |
| FR-011 — one source's changes never touch another's state | keyed by `source_name` throughout |
| FR-012 — a removed source's records are reported, not deleted | `known_source_names` minus configured names, then `record_count` |
| FR-013 — a rename is announced as a new source | a configured name absent from `known_source_names` while a known name is absent from the configuration |
| FR-043, FR-044 — per-source outcomes | `record_ingestion` |

**Note on FR-013**: rename detection is a heuristic over set differences and cannot distinguish a rename
from one source removed and another added. It therefore *warns* — "'work-mail' is not in the store; if you
renamed it, it will be read from the beginning" — which is exactly what FR-013 asks for, and never
silently re-associates records with a different name.

## Implementations

| Implementation | Where | Status |
|----------------|-------|--------|
| `SqliteSourceStateStore` | `src/iknowwhatyoudid/sources/state.py` | **Built.** The default |
| `InMemorySourceStateStore` | `0002` | A test double |

## Resolved

Resumption points are durable. `ingest` no longer reports `persistence: in_memory_only`, and the
"resumption points do not survive process exit" limitation this contract used to carry is gone.

One addition `0002` has not yet absorbed: `0001` introduced `RunMode` (`INCREMENTAL` / `SWEEP`), because
withdrawal detection is impossible from a purely incremental read. `0002`'s `SourceReader.read()` does not
express it. Until a connector supplies it every ingestion is `INCREMENTAL`, which is the safe default —
nothing is ever withdrawn, so the failure mode is a withdrawn record left marked present rather than a
present record wrongly marked withdrawn.
