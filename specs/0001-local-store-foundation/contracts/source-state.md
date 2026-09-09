# Contract: Implementing 0002's source-state port

Feature `0002-configurable-sources` was planned before this one and depends on the store through a narrow
four-operation port, defined in
[`specs/0002-configurable-sources/contracts/source-state.md`](../../0002-configurable-sources/contracts/source-state.md).
**This feature supplies the durable implementation.** The port is unchanged; only the backing changed.

```python
class SourceStateStore(Protocol):
    def resumption_point(self, source_name: str) -> datetime | None: ...
    def record_ingestion(self, outcome: SourceRunOutcome, through: datetime | None) -> None: ...
    def known_source_names(self) -> frozenset[str]: ...
    def record_count(self, source_name: str) -> int: ...
```

## Mapping onto the schema

| Operation | Implementation |
|-----------|----------------|
| `resumption_point` | `SELECT resumption_point_utc FROM raw_source WHERE name = ?` |
| `record_ingestion` | Insert a `raw_ingestion_run` row and advance `raw_source.resumption_point_utc` — **only when the run completed**, and in the same transaction as the batch it describes (FR-013) |
| `known_source_names` | `SELECT DISTINCT source FROM raw_record` — includes sources no longer configured, which is what makes `0002`'s FR-012 reporting possible |
| `record_count` | `SELECT count(*) FROM raw_record WHERE source = ?` |

`known_source_names` reads from `raw_record` rather than `raw_source` deliberately: `0002` needs the set of
sources that **hold records**, so that a source removed from the configuration is reported rather than
silently orphaned. A source row with no records is not a source whose data would be lost.

## What changed in 0002 — done

| In `0002` | Change | Status |
|-----------|--------|--------|
| `sources/state.py` | `SqliteSourceStateStore` is the default; the in-memory one is a test double | applied (T044) |
| `persistence: in_memory_only` | Removed from the payload, the contract and the stderr notice | applied |
| `contracts/source-state.md` | The "does not exist yet" caveat and the durability limitation are gone | applied |
| `plan.md` Complexity Tracking | Reads as a port with two implementations — the abstraction is discharged, not merely tolerated | applied |

## `RunMode` is an addition 0002 does not yet carry

This feature introduces `RunMode` (research [R6](../research.md)) because withdrawal detection is
impossible from a purely incremental read. `0002`'s `SourceReader.read()` signature does not express it.

Whichever feature builds the first real connector must extend that protocol so a reader states whether
its read was exhaustive. Until then every ingestion is `INCREMENTAL`, which is the safe default: no
record is ever withdrawn, so the failure mode is a withdrawn record left marked present — visible and
correctable — rather than a present record marked withdrawn.
