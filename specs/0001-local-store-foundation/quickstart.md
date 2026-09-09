# Quickstart: validating the Local Store Foundation

How to prove this feature works once implemented. Every scenario runs against fixture batches of
normalized records — no connector exists yet, and the constitution forbids testing against real accounts.

## Prerequisites

```bash
uv sync
uv run mypy src tests      # must be clean
uv run pytest              # must be green
```

**Run everything through `uv run`** — the ambient interpreter is 3.11.5 and the project needs 3.12.

## Scenario 1 — a store appears on first use (US1)

```bash
uv run ikwyd store info --store "$TMP/fresh/store.db"
```

Expected: the store is created with no setup step (FR-002), its location is reported (FR-003), and it is
created owner-only (FR-005). Verify permissions independently of the tool's own report — on POSIX with
`stat`, on Windows by reading the DACL.

## Scenario 2 — records go in and come back out, offline (US1)

Load a fixture batch spanning several notional sources, then query by day and by source.

```bash
uv run ikwyd records query --from 2026-03-01 --to 2026-03-31 --json | jq '.data.records | length'
```

Expected: every record returns with its source, the source's own id, its time, and its unmodified payload
(FR-006, SC-009).

**The load-bearing assertion is negative**: no socket is opened. Assert on socket creation, not on output
— a test that only checks results passes even if the tool phoned home (SC-001).

## Scenario 3 — re-ingesting changes nothing (SC-005)

Ingest the same batch twice, then a third time with an overlapping range.

Expected: the record count is identical after each (FR-011). Then re-present one record with changed
content: same row, `revision` incremented, still one record (FR-014).

## Scenario 4 — an interrupted ingestion is clean and resumable (SC-010)

Kill the process partway through a multi-batch ingestion, at several different points.

Expected each time: the store opens cleanly, the record count matches a **whole number of completed
batches**, and the resumption point corresponds to the last completed one — so resuming neither
duplicates nor skips (FR-013).

## Scenario 5 — re-derivation needs no source (US2, SC-002)

Populate raw records and derived attributions, discard the derived region, then re-derive with the
network down and every fixture file made unreadable.

Expected: raw records untouched and still queryable (FR-010); derivation completes with zero source reads
(FR-015); running it twice produces identical results.

## Scenario 6 — corrections survive everything (US3, SC-004)

The most important test in the feature. Corrections are the only data no source can supply again.

Record corrections against a fixture store, then put them through all three paths:

| Path | Assertion |
|------|-----------|
| Discard and re-derive | Every correction present, still taking precedence over inferred attributions (FR-017, FR-019) |
| Migrate to a newer schema | Every correction present, counts identical (FR-017) |
| Delete the store and re-ingest the same fixtures | Every correction re-applied to its record by `(source, source_id)` (FR-017) |

Then the round-trip: export, import into an empty store, and assert the correction set is identical
including `pending` entries and `made_at` values ([corrections-file.md](./contracts/corrections-file.md)).

## Scenario 7 — import conflicts are never silent (FR-033, FR-034, SC-014)

Build two stores with corrections for the same records at different `made_at` times, plus one pair with
identical times, plus one correction whose record is absent.

Expected: newer wins; equal times keep the local one; the absent-record correction is retained as pending
rather than dropped; and **every replacement and every declined replacement is named** in the report. Run
with `--dry-run` first and assert it reports the same without writing.

## Scenario 8 — migration is atomic (US4, SC-006, SC-007)

```bash
uv run pytest tests/integration/test_migration.py -v
```

Build a store at an older schema version holding records and corrections, then:

- **Successful migration**: runs without user intervention, record and correction counts identical
  afterwards, version advanced (FR-020).
- **Deliberately failing migration**: the store is left at its previous version, **fully usable**, counts
  unchanged, and the failure is reported (FR-021). Assert the schema is byte-equivalent — this is the
  behaviour that rests on transactional DDL and `user_version` rolling back with it.
- **Store from a newer version**: every command refuses with exit `2`, says so plainly, changes nothing
  (FR-022).

Per the constitution, run each against both an empty and a populated store.

## Scenario 9 — withdrawal, and the run mode that gates it (FR-027 to FR-029, SC-011)

The scenario most likely to be got wrong, so test the negative case first.

1. **`INCREMENTAL` never withdraws.** Ingest a batch, then a later incremental batch covering only new
   records. Assert **zero** records are marked withdrawn. Without `RunMode` this is where every record
   outside the window would be wrongly withdrawn.
2. **`SWEEP` withdraws only what it covered.** Sweep a window with one previously stored id absent from
   `seen_source_ids`. Assert exactly that record is withdrawn and dated, records outside the window are
   untouched, and the total record count **does not fall** (SC-011).
3. **Reappearance clears it.** Present the record again; assert the withdrawal is cleared and no second
   row exists (FR-029).
4. A withdrawn record stays queryable, keeps its corrections, and is excluded from summaries by default
   (FR-028).

## Scenario 10 — future-dated records (FR-035 to FR-038, SC-013)

Ingest a record dated ahead of the run — a calendar entry for next month, and an email dated 2027 by a
broken clock.

Expected: both stored with their times unmodified (FR-035); both excluded from elapsed-time summaries;
both counted in `store info`'s future-dated column for their source (FR-038).

Then **advance the clock past the calendar entry's time without re-ingesting** and assert it now counts
normally (FR-037). This is what fails if the "future-dated" flag is stored rather than derived.

## Scenario 11 — concurrency and corruption (FR-025, FR-026)

Hold a write transaction open and run a second command.

Expected: it waits for the busy timeout, then fails with a clear message naming the store — never
corruption, never partial results.

Then point the tool at a truncated file and at a file that is not a database at all. Expected: reported
with its path and a recovery step, and **not deleted or overwritten** (FR-026).

## Scenario 12 — the log holds no record content (FR-039 to FR-043, SC-015)

```bash
uv run pytest tests/integration/test_logging.py -v
```

Ingest fixtures whose titles and payloads contain sentinel strings, then search the log for each sentinel.

Expected: zero matches, while every failed record is still identifiable by source and source-side id
(FR-040, FR-041). Also assert: the log is owner-only, rotation bounds its size (FR-042), and making the
log path unwritable does not fail the ingestion (FR-043).

## Scenario 13 — at-rest protection reports honestly (FR-031, SC-012)

```bash
uv run ikwyd store protection
```

Expected on Windows, unelevated: `file permissions OWNER_ONLY` and `disk encryption UNVERIFIED`, with the
elevated command printed. **Assert it never reports encryption as `ON` when it could not read the status**
— that is the whole point of the requirement. On POSIX, `chmod 0644` the store and assert the report flips
to `OTHERS_CAN_READ`.

## Scenario 14 — performance (SC-008)

Generate a year of records (~10⁵–10⁶ rows across several sources) and time `store info`.

Expected: under 5 seconds. If it is not, the answer is an index, not a different engine — the query plan
should be using `raw_record_live`.

## Known gaps at the end of this feature

- **No connector exists.** Everything is exercised through fixture batches; `0003`, `0004`, and `0005`
  supply real readers.
- **`RunMode` is not yet in `0002`'s `SourceReader` protocol**, so until a connector supplies it every
  ingestion is `INCREMENTAL` and nothing is ever withdrawn. The failure mode is a withdrawn record left
  marked present — visible and correctable — rather than the reverse.
- **Derived attributions are stored but never produced.** The rules are a later feature.
