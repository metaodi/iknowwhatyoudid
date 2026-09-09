# Contract: What a connector hands over

The normalized shape every source maps into (FR-006). This is the boundary a connector feature — `0003`
git, `0004` mail, `0005` calendar — writes against. Nothing here contacts a source; the connector reads,
this contract receives.

```python
@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    source_id: str | None        # the source's own id; None if it has none (FR-009)
    occurred: datetime           # MUST be timezone-aware
    duration: timedelta | None   # None for a point in time (a commit)
    title: str                   # may be empty, never None
    payload: Mapping[str, object]  # the unmodified source payload, JSON-serialisable (FR-006)
```

```python
class RunMode(StrEnum):
    INCREMENTAL = "incremental"  # "I asked only for what is new"
    SWEEP       = "sweep"        # "I asked for everything in this window and saw exactly these ids"
```

```python
@dataclass(frozen=True, slots=True)
class Batch:
    source: str
    mode: RunMode
    range_from: datetime | None
    range_to: datetime | None
    records: Sequence[NormalizedRecord]
    seen_source_ids: frozenset[str] | None  # required for SWEEP, must be None for INCREMENTAL
```

## Why `RunMode` exists

It is the finding that most shaped this feature (research [R6](../research.md)).

FR-027 says a record no longer present at the source must be marked withdrawn. But an incremental run
asks the source only for what is *new* — it sees nothing of the old records, so "absent from this run"
and "deleted at the source" are indistinguishable from the store's side. Withdrawing on any run would
mark **every record outside the incremental window as withdrawn, on every run**, turning a safety
requirement into a data-destruction bug.

The connector is the only party that knows whether its read was exhaustive, so it must say. Only a
`SWEEP` may withdraw, only within `range_from`–`range_to`, and only for the source it read.

## Obligations on the caller

| Obligation | Requirement |
|------------|-------------|
| `occurred` is timezone-aware — a naive datetime is rejected, not assumed local | FR-007 |
| `payload` is the source's data unmodified — no cleaning, no enrichment | FR-006 |
| `SWEEP` supplies `seen_source_ids` and both range bounds | FR-027 |
| `INCREMENTAL` supplies no `seen_source_ids` | FR-027 |
| A future-dated `occurred` is passed through unchanged, never clamped | FR-035 |
| No credential or secret appears anywhere in `payload` | FR-024 |

## What the store does with a batch

One transaction per batch (FR-013). Either all of it lands or none of it does, and the source's
resumption point advances **inside the same transaction**, so an interrupted run resumes from the last
completed batch without duplicating or skipping.

| Case | Behaviour | Requirement |
|------|-----------|-------------|
| `source_id` is `None` | A stable id is derived as `derived:<blake2b-160>` over a canonical serialisation of `(source, occurred_utc, title, payload)`, and flagged as derived | FR-009 |
| `(source, source_id)` already stored, content identical | No-op | FR-011 |
| `(source, source_id)` already stored, content changed | Same row updated, `revision` incremented — still the same record | FR-014 |
| Record was withdrawn and now reappears | `withdrawn_on_utc` cleared; no second row | FR-029 |
| `SWEEP`: stored record in range, id not in `seen_source_ids` | Marked withdrawn with the sweep's date. **Never deleted** | FR-027 |
| `occurred` lies after the run's start | Stored unmodified; counted in the per-source future-dated total | FR-035, FR-038 |

## The derived-identifier caveat

A source supplying no id of its own gets one computed from its content. It follows that **if such a
record's content changes, its identifier changes, and it presents as a new record** — FR-014's
"same record, new revision" cannot apply, because there is nothing stable to recognise it by.

This is unavoidable rather than a defect, but it is the kind of thing that is discovered as a duplicate
months later, so: `source_id_is_derived` is stored per record, and a connector that *can* supply a stable
id should always do so, even a weak one, in preference to letting the store derive one.
