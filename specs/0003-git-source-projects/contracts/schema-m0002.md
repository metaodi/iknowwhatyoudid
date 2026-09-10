# Contract: Migration m0002 — projects and repositories

**Version**: `PRAGMA user_version` 1 → 2

Executed statement by statement inside one `BEGIN IMMEDIATE`, never with `executescript()` — Python's
sqlite3 issues an implicit COMMIT before a script, which would close the transaction and silently defeat
the rollback guarantee FR-021 of `0001` rests on.

## New tables

```sql
-- The unit a timesheet reports against. In the USER region: a declared project is the
-- user's statement, not something derivable from any source.
CREATE TABLE user_project (
    id               INTEGER PRIMARY KEY,
    name             TEXT    NOT NULL,
    normalised_name  TEXT    NOT NULL UNIQUE,
    ad_hoc           INTEGER NOT NULL DEFAULT 0 CHECK (ad_hoc IN (0,1)),
    first_seen_utc   INTEGER NOT NULL
) STRICT;

-- A discovered repository. In the RAW region: a fact about the world, rediscoverable.
CREATE TABLE raw_repository (
    id              INTEGER PRIMARY KEY,
    identity        TEXT    NOT NULL UNIQUE,
    identity_kind   TEXT    NOT NULL CHECK (identity_kind IN ('root_commit','path')),
    name            TEXT    NOT NULL,
    first_seen_utc  INTEGER NOT NULL,
    last_seen_utc   INTEGER NOT NULL
) STRICT;

-- One identity, many paths: a bare clone, a linked worktree and the original share a
-- root commit (verified, research R3). Collapsing them is right for a timesheet; the
-- paths are kept so "where is it" is still answerable.
CREATE TABLE raw_repository_path (
    repository_id  INTEGER NOT NULL REFERENCES raw_repository(id) ON DELETE CASCADE,
    path           TEXT    NOT NULL,
    is_bare        INTEGER NOT NULL DEFAULT 0 CHECK (is_bare IN (0,1)),
    is_worktree    INTEGER NOT NULL DEFAULT 0 CHECK (is_worktree IN (0,1)),
    last_seen_utc  INTEGER NOT NULL,
    PRIMARY KEY (repository_id, path)
) STRICT;

CREATE INDEX raw_repository_path_by_path ON raw_repository_path (path);
```

`normalised_name` carries the uniqueness (case-folded, whitespace-trimmed) while `name` preserves what the
user typed — FR-027 forbids two projects differing only in case, and the user should still see their own
capitalisation.

## Changing `derived_attribution`

`0001` created it with `project TEXT NOT NULL`, an honest placeholder for this feature. A text key cannot
satisfy FR-024: renaming a project would be a delete plus an insert, and the history would silently go
elsewhere.

```sql
-- 1. Every distinct project name that already exists becomes a declared project.
INSERT INTO user_project (name, normalised_name, ad_hoc, first_seen_utc)
SELECT DISTINCT project, lower(trim(project)), 0, :now
FROM derived_attribution
WHERE trim(project) <> ''
ON CONFLICT(normalised_name) DO NOTHING;

-- 2. Rebuild the table with project_id in place of project.
CREATE TABLE derived_attribution_new (
    id              INTEGER PRIMARY KEY,
    record_id       INTEGER NOT NULL REFERENCES raw_record(id) ON DELETE CASCADE,
    project_id      INTEGER NOT NULL REFERENCES user_project(id),
    rule            TEXT    NOT NULL,
    evidence        TEXT    NOT NULL CHECK (json_valid(evidence)),
    derived_at_utc  INTEGER NOT NULL
) STRICT;

INSERT INTO derived_attribution_new (id, record_id, project_id, rule, evidence, derived_at_utc)
SELECT d.id, d.record_id, p.id, d.rule, d.evidence, d.derived_at_utc
FROM derived_attribution d
JOIN user_project p ON p.normalised_name = lower(trim(d.project));

DROP TABLE derived_attribution;
ALTER TABLE derived_attribution_new RENAME TO derived_attribution;
CREATE INDEX derived_attribution_record  ON derived_attribution (record_id);
CREATE INDEX derived_attribution_project ON derived_attribution (project_id);
```

Step 1 marks migrated projects **declared, not ad-hoc**: they were written by something before this feature
existed, and inventing a provenance for them would be worse than assuming the conservative one.

## `user_correction` is left alone

Its `project` stays free text. A correction is the user naming a project in their own words — their
statement, and the only irreplaceable data in the store. Resolving it to an id would mean either rejecting
a correction that names a project not yet declared, or inventing a project on the user's behalf. Both are
worse than leaving the text as written; a later feature can reconcile it if it needs to.

This also keeps `0001`'s correction export format unchanged, so exports written before this migration still
import afterwards.

## Testing

Per the constitution, against **both an empty and a populated store**:

| Case | Assertion |
|---|---|
| Empty store at v1 | Migrates to v2; the new tables exist and are empty |
| Populated with attributions over three project names | Three declared projects exist; every attribution keeps its project; counts are identical |
| Populated where two names differ only in case | One project; both attributions point at it — the case FR-027 exists for |
| Populated with corrections | Correction count and text unchanged |
| A deliberately failing m0002 | Store left at v1, fully usable, counts unchanged — the guarantee that rests on DDL and `user_version` rolling back together |
| Store already at v2 | No-op |
