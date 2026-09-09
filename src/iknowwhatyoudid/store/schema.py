"""The v1 schema: three separately discardable regions (FR-010).

See specs/0001-local-store-foundation/contracts/schema.md.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

#: STRICT tables need SQLite 3.37.
MINIMUM_SQLITE = (3, 37, 0)

RAW_DDL = """
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
    occurred_offset_minutes  INTEGER NOT NULL
        CHECK (occurred_offset_minutes BETWEEN -1080 AND 1080),
    occurred_zone            TEXT,
    duration_us              INTEGER CHECK (duration_us IS NULL OR duration_us >= 0),
    title                    TEXT    NOT NULL,
    payload                  TEXT    NOT NULL CHECK (json_valid(payload)),
    ingestion_run            INTEGER NOT NULL REFERENCES raw_ingestion_run(id),
    revision                 INTEGER NOT NULL DEFAULT 1,
    withdrawn_on_utc         INTEGER,
    UNIQUE (source, source_id)
) STRICT;

CREATE INDEX raw_record_time      ON raw_record (occurred_utc);
CREATE INDEX raw_record_by_source ON raw_record (source, occurred_utc);
CREATE INDEX raw_record_live      ON raw_record (source, occurred_utc)
    WHERE withdrawn_on_utc IS NULL;
"""

DERIVED_DDL = """
CREATE TABLE derived_attribution (
    id              INTEGER PRIMARY KEY,
    record_id       INTEGER NOT NULL REFERENCES raw_record(id) ON DELETE CASCADE,
    project         TEXT    NOT NULL,
    rule            TEXT    NOT NULL,
    evidence        TEXT    NOT NULL CHECK (json_valid(evidence)),
    derived_at_utc  INTEGER NOT NULL
) STRICT;

CREATE INDEX derived_attribution_record ON derived_attribution (record_id);
"""

# No foreign key into raw_record, deliberately: a correction must outlive the record row
# it refers to, because a delete-and-rebuild changes every internal id (FR-017). It is
# also what lets an imported correction for an absent record sit as pending (FR-018).
USER_DDL = """
CREATE TABLE user_correction (
    id           INTEGER PRIMARY KEY,
    source       TEXT    NOT NULL,
    source_id    TEXT    NOT NULL,
    project      TEXT,
    note         TEXT,
    made_at_utc  INTEGER NOT NULL,
    pending      INTEGER NOT NULL DEFAULT 0 CHECK (pending IN (0,1)),
    UNIQUE (source, source_id)
) STRICT;
"""

ALL_DDL = (RAW_DDL, DERIVED_DDL, USER_DDL)


def statements(*blocks: str) -> tuple[str, ...]:
    """Split DDL blocks into individual statements.

    Migrations must run each statement with ``execute()``, never ``executescript()``:
    Python's sqlite3 issues an implicit COMMIT before running a script, which would
    close the migration's transaction and silently defeat the rollback guarantee that
    FR-021 rests on.
    """
    found: list[str] = []
    for block in blocks:
        for raw in block.split(";"):
            statement = raw.strip()
            if statement:
                found.append(statement)
    return tuple(found)
