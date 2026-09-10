# Contract: migration `m0003_correspondents`

**v2 → v3.** Adds correspondents. Changes nothing that already exists.

## What it creates

```sql
CREATE TABLE raw_correspondent (
    id              INTEGER PRIMARY KEY,
    address         TEXT    NOT NULL UNIQUE,
    display_name    TEXT,
    domain          TEXT    NOT NULL,
    first_seen_utc  INTEGER NOT NULL
) STRICT;

CREATE INDEX raw_correspondent_domain ON raw_correspondent (domain);

CREATE TABLE raw_record_correspondent (
    record_id         INTEGER NOT NULL REFERENCES raw_record(id) ON DELETE CASCADE,
    correspondent_id  INTEGER NOT NULL REFERENCES raw_correspondent(id),
    role              TEXT    NOT NULL CHECK (role IN ('sender','to','cc')),
    PRIMARY KEY (record_id, correspondent_id, role)
) STRICT;

CREATE INDEX raw_record_correspondent_by_correspondent
    ON raw_record_correspondent (correspondent_id);
```

`address` is stored already normalised, so `UNIQUE` does the deduplication rather than a query having to.

`ON DELETE CASCADE` on `record_id` but **not** on `correspondent_id`: deleting a record forgets its links,
but a correspondent outlives any single message. There is no `bcc` role, deliberately — see
[data-model.md](../data-model.md).

## What it does not do

| Not done | Why |
|---|---|
| Backfill | No mail exists before this feature |
| Touch `derived_attribution` | The new rule values are data, not schema |
| Touch `user_correction` | The only irreplaceable data in the store; a migration has no business in it |
| Touch anything from `0003` | Repositories and projects are unchanged |

## How it runs

Per-statement `execute()` inside the runner's single transaction. **Never `executescript()`** — Python's
`sqlite3` issues an implicit COMMIT before a script, which would end the transaction and defeat the rollback
that `0001`'s FR-021 rests on. This is stated because it is the mistake `m0002` had to be corrected for, and
the next migration author will not have been there.

## Test cases

Against **both an empty and a populated store**, as the constitution requires.

| Case | Expected |
|---|---|
| Empty v2 store | Reaches v3; both tables exist and are empty |
| Populated v2 store (git records, projects, corrections) | Reaches v3; every record, project, attribution and correction count is unchanged |
| A deliberately failing migration | Store stays at **v2**, both new tables absent, all counts unchanged |
| Already at v3 | No-op |
| A store from v4 or later | Refused and untouched, as `0001` established |
| Two addresses differing only in case, inserted after migrating | One `raw_correspondent` row |
| A record deleted | Its `raw_record_correspondent` rows go; the `raw_correspondent` rows stay |
