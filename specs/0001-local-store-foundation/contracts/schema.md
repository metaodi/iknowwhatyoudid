# Contract: The v1 schema

**Engine**: SQLite (research [R1](../research.md)) · **Minimum**: SQLite 3.37 (for `STRICT`); checked at
startup · **Version**: `PRAGMA user_version = 1`

Connection setup on every open:

```sql
PRAGMA journal_mode = WAL;      -- verified
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;     -- FR-025; verified to raise "database is locked" after the wait
PRAGMA synchronous = FULL;      -- FR-013: a batch survives a power loss, not just a process kill
```

Writers open with `BEGIN IMMEDIATE` so contention is detected before any work is done.

## Region: raw

```sql
CREATE TABLE raw_source (
    name                  TEXT    PRIMARY KEY,
    first_seen_utc        INTEGER NOT NULL,
    resumption_point_utc  INTEGER
) STRICT;

CREATE TABLE raw_ingestion_run (
    id               INTEGER PRIMARY KEY,
    source           TEXT    NOT NULL REFERENCES raw_source(name),
    mode             TEXT    NOT NULL CHECK (mode IN ('incremental','sweep')),
    range_from_utc   INTEGER,
    range_to_utc     INTEGER,
    started_at_utc   INTEGER NOT NULL,
    finished_at_utc  INTEGER,
    record_count     INTEGER NOT NULL DEFAULT 0,
    completed        INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0,1))
) STRICT;

CREATE TABLE raw_record (
    id                       INTEGER PRIMARY KEY,
    source                   TEXT    NOT NULL REFERENCES raw_source(name),
    source_id                TEXT    NOT NULL,
    source_id_is_derived     INTEGER NOT NULL DEFAULT 0 CHECK (source_id_is_derived IN (0,1)),
    occurred_utc             INTEGER NOT NULL,
    occurred_offset_minutes  INTEGER NOT NULL CHECK (occurred_offset_minutes BETWEEN -1080 AND 1080),
    occurred_zone            TEXT,
    duration_us              INTEGER CHECK (duration_us IS NULL OR duration_us >= 0),
    title                    TEXT    NOT NULL,
    payload                  TEXT    NOT NULL CHECK (json_valid(payload)),
    ingestion_run            INTEGER NOT NULL REFERENCES raw_ingestion_run(id),
    revision                 INTEGER NOT NULL DEFAULT 1,
    withdrawn_on_utc         INTEGER,
    UNIQUE (source, source_id)          -- FR-011: re-ingest upserts, never duplicates
) STRICT;

CREATE INDEX raw_record_time      ON raw_record (occurred_utc);
CREATE INDEX raw_record_by_source ON raw_record (source, occurred_utc);
CREATE INDEX raw_record_live      ON raw_record (source, occurred_utc) WHERE withdrawn_on_utc IS NULL;
```

The partial index is what keeps SC-008 comfortable: the common query excludes withdrawn records, and a
partial index keeps it off the withdrawn rows entirely.

## Region: derived

```sql
CREATE TABLE derived_attribution (
    id              INTEGER PRIMARY KEY,
    record_id       INTEGER NOT NULL REFERENCES raw_record(id) ON DELETE CASCADE,
    project         TEXT    NOT NULL,
    rule            TEXT    NOT NULL,            -- FR-019
    evidence        TEXT    NOT NULL CHECK (json_valid(evidence)),
    derived_at_utc  INTEGER NOT NULL
) STRICT;

CREATE INDEX derived_attribution_record ON derived_attribution (record_id);
```

## Region: user

```sql
CREATE TABLE user_correction (
    id           INTEGER PRIMARY KEY,
    source       TEXT    NOT NULL,      -- identity by SOURCE-SIDE keys, deliberately not record_id
    source_id    TEXT    NOT NULL,      -- so corrections survive a rebuild (FR-017)
    project      TEXT,                  -- NULL = explicitly not attributable
    note         TEXT,
    made_at_utc  INTEGER NOT NULL,      -- FR-032; decides newest-wins on import
    pending      INTEGER NOT NULL DEFAULT 0 CHECK (pending IN (0,1)),
    UNIQUE (source, source_id)
) STRICT;
```

**`user_correction` has no foreign key into `raw_record`, and that is the point.** A correction must
outlive the record row it refers to — across a delete-and-rebuild every internal id changes — so it is
keyed by what the source calls the record. It is also why an imported correction for an absent record can
simply sit with `pending = 1` (FR-018) rather than being rejected by a constraint.

## Discarding a region (FR-010)

```sql
-- Derived: fully regenerable, no network needed to rebuild (FR-015)
BEGIN IMMEDIATE; DELETE FROM derived_attribution; COMMIT;

-- Raw: forces re-ingestion. Corrections survive untouched.
BEGIN IMMEDIATE; DELETE FROM raw_record; DELETE FROM raw_ingestion_run; DELETE FROM raw_source; COMMIT;
```

Discarding raw cascades into `derived_attribution` and touches `user_correction` not at all. There is no
supported operation that discards `user_correction` other than an explicit, separately named command —
the region holding the only irreplaceable data does not share a code path with the two that are
regenerable.

## Migrations (FR-020 to FR-022)

Each migration is a module exposing `VERSION: int` and `upgrade(conn) -> None`. The runner:

1. Refuses if `user_version` exceeds the highest known version (FR-022) — reports, changes nothing.
2. Takes a file snapshot via the online backup API, as a recovery path for what transactions cannot cover.
3. Applies every pending migration inside **one** `BEGIN IMMEDIATE`, setting `user_version` in the same
   transaction.

Step 3 is the whole of FR-021: **verified** that SQLite's DDL is transactional and that `PRAGMA
user_version` rolls back with it (a rolled-back migration left no table and reverted the version 99 → 1).
A migration that raises leaves the store byte-equivalent to its previous state with no cleanup code, and
the snapshot from step 2 is the second safety net, not the first.

Migrations are forward-only. FR-022 already covers the case a downgrade would serve.
