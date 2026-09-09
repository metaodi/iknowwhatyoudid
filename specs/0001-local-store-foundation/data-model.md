# Phase 1 Data Model: Local Store Foundation

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

Engine: SQLite, one file, `STRICT` tables throughout. Full DDL in [contracts/schema.md](./contracts/schema.md).

## The three regions (FR-010)

| Region | Prefix | Regenerable? | Discarding it means |
|--------|--------|--------------|---------------------|
| Raw | `raw_` | From the source, except once withdrawn | Re-ingest from every source |
| Derived | `derived_` | Yes, from raw alone, with no network | Re-run analysis |
| User | `user_` | **Never** | Unrecoverable loss |

No foreign key points from `raw_` into `derived_` or `user_`. Dependencies run one way only, which is what
makes each region independently discardable.

---

## Source (`raw_source`)

| Field | Type | Notes |
|-------|------|-------|
| `name` | TEXT PK | The user-assigned name from `0002`'s configuration; the identity across runs |
| `first_seen_utc` | INTEGER | |
| `resumption_point_utc` | INTEGER NULL | Where the last completed ingestion stopped (FR-012) |

Advanced only inside the same transaction that commits the batch (FR-013), so an interrupted run resumes
from the last *completed* batch and never skips.

---

## Activity Record (`raw_record`)

The normalized shape every source maps into (FR-006).

| Field | Type | Notes |
|-------|------|-------|
| `id` | INTEGER PK | Internal only. **Never leaves the store** — exports use `(source, source_id)` |
| `source` | TEXT FK → `raw_source` | |
| `source_id` | TEXT | The source's own identifier, or a `derived:` digest (FR-009) |
| `source_id_is_derived` | INTEGER | Distinguishes the two, because FR-014 treats them differently |
| `occurred_utc` | INTEGER | Microseconds since epoch (FR-007) |
| `occurred_offset_minutes` | INTEGER | The offset as the source expressed it (FR-007) |
| `occurred_zone` | TEXT NULL | IANA zone name where known — the only thing that resolves a DST-repeated hour |
| `duration_us` | INTEGER NULL | Present for spans (a meeting), absent for points (a commit) |
| `title` | TEXT | Human-readable |
| `payload` | TEXT | The unmodified source payload, as JSON (FR-006) |
| `ingestion_run` | INTEGER FK → `raw_ingestion_run` | Which run produced it (FR-008) |
| `revision` | INTEGER | Incremented when re-presented with changed content (FR-014) |
| `withdrawn_on_utc` | INTEGER NULL | Set by a sweep; NULL means present (FR-027) |

**Uniqueness**: `UNIQUE (source, source_id)`. This is what makes FR-011 hold — re-ingesting the same data,
whole or overlapping, upserts rather than duplicates.

**Validation rules**

| Rule | Requirement |
|------|-------------|
| `payload` is valid JSON | FR-006 |
| `occurred_offset_minutes` within ±1080 | sanity |
| `occurred_zone` NULL or a resolvable IANA name | FR-007 |
| `title` may be empty but not NULL | FR-006 |
| Re-presented with changed content → `revision + 1`, same row | FR-014 |
| Re-presented while withdrawn → `withdrawn_on_utc = NULL` | FR-029 |
| `occurred_utc` in the future is accepted and stored unmodified | FR-035 |

### Derived properties — stored nowhere (research R7)

| Property | Computed as | Serves |
|----------|-------------|--------|
| `was_future_at_ingestion` | `occurred_utc > run.started_at_utc` | FR-038's per-source count of a possibly-wrong clock. Immutable |
| `not_yet_elapsed` | `occurred_utc > now()` | FR-036's exclusion from elapsed-time summaries, and FR-037's automatic return to ordinary once the moment passes |

Storing either as a column would make FR-037 require a periodic sweep to clear stale flags. Deriving both
means the record simply becomes countable when its time arrives.

### Withdrawal state

```text
                    ingested
                       │
                       ▼
                 ┌───────────┐
                 │  PRESENT  │ ◄──────────────┐
                 └─────┬─────┘                │
                       │                      │
     a SWEEP covering this record's           │  the source presents it
     window does not report its id            │  again in any later run
                       │                      │  (FR-029)
                       ▼                      │
                 ┌───────────┐                │
                 │ WITHDRAWN │ ───────────────┘
                 │ + date    │
                 └───────────┘
```

An `INCREMENTAL` run can never cause this transition (research R6). A withdrawn record stays queryable,
keeps its attributions and corrections, and is excluded from new summaries by default (FR-028).

---

## Ingestion Run (`raw_ingestion_run`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | INTEGER PK | |
| `source` | TEXT FK → `raw_source` | |
| `mode` | TEXT | `incremental` or `sweep` — **only a sweep may withdraw** (FR-027, research R6) |
| `range_from_utc`, `range_to_utc` | INTEGER NULL | The window the run covered; bounds any withdrawal |
| `started_at_utc`, `finished_at_utc` | INTEGER / NULL | NULL finish means interrupted |
| `record_count` | INTEGER | |
| `completed` | INTEGER | Only a completed run advances the resumption point (FR-013) |

---

## Derived Attribution (`derived_attribution`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | INTEGER PK | |
| `record_id` | INTEGER FK → `raw_record` ON DELETE CASCADE | |
| `project` | TEXT | |
| `rule` | TEXT | Which rule produced it (FR-019) |
| `evidence` | TEXT | JSON — what it rests on (FR-019) |
| `derived_at_utc` | INTEGER | |

Always inferred, never user-confirmed — a user's statement is a `user_correction`, and keeping them in
different tables is what makes FR-019's "distinguishable" true by construction rather than by a flag
someone could set wrongly. Wholly regenerable; this feature stores it, later features produce it.

---

## User Correction (`user_correction`)

The only irreplaceable data in the store.

| Field | Type | Notes |
|-------|------|-------|
| `id` | INTEGER PK | |
| `source` | TEXT | **Identity by source-side keys, not `record_id`** |
| `source_id` | TEXT | — which is what lets FR-017 survive a full rebuild, where every internal id differs |
| `project` | TEXT NULL | NULL means "explicitly not attributable" |
| `note` | TEXT NULL | |
| `made_at_utc` | INTEGER | Decides newest-wins on import (FR-032, FR-033) |
| `pending` | INTEGER | 1 when no matching record is present in this store (FR-018) |

**Uniqueness**: `UNIQUE (source, source_id)` — one standing correction per record.

**Validation rules**

| Rule | Requirement |
|------|-------------|
| Takes precedence over any `derived_attribution` for the same record, everywhere | FR-019, Principle V |
| Survives discarding the derived region, a migration, and a delete-and-rebuild | FR-017 |
| Imported with no matching record → retained with `pending = 1`, never dropped | FR-018 |
| A pending correction stops being pending when its record is later ingested | FR-018 |
| On import conflict: higher `made_at_utc` wins; equal keeps the local row | FR-033 |
| Every replacement and every declined replacement is reported | FR-034 |

---

## Store Version

`PRAGMA user_version` — a single integer in the file header that participates in transaction rollback
(verified). No table needed.

| Situation | Behaviour | Requirement |
|-----------|-----------|-------------|
| `user_version` < highest known migration | Migrate in place, automatically | FR-020 |
| Migration raises | Transaction rolls back; version and schema unchanged; failure reported | FR-021 |
| `user_version` > highest known | Refuse every command, say so plainly, change nothing | FR-022 |

---

## Protection status (not persisted)

Reported by `store protection`, computed per invocation (FR-031).

| Field | Values |
|-------|--------|
| `permissions` | `OWNER_ONLY` / `OTHERS_CAN_READ` / `UNVERIFIED` |
| `disk_encryption` | `ON` / `OFF` / `UNVERIFIED` |

Both are three-valued on purpose. On Windows, `disk_encryption` is `UNVERIFIED` for any unelevated run —
verified, every available probe requires administrator rights (research R10) — and the report says so
along with the command the user can run themselves. Neither field ever collapses unknown into safe.

---

## Entity coverage against the spec

| Spec entity | Tables |
|-------------|--------|
| Source | `raw_source` |
| Activity Record | `raw_record` |
| Ingestion Run | `raw_ingestion_run` |
| Derived Attribution | `derived_attribution` |
| User Correction | `user_correction` |
| Store Version | `PRAGMA user_version` |
