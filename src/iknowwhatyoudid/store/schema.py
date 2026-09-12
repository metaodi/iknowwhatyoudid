"""The v1 schema: three separately discardable regions (FR-010).

See specs/0001-local-store-foundation/contracts/schema.md.
"""

from __future__ import annotations

SCHEMA_VERSION = 3

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

# --- v2: projects and repositories (feature 0003) ------------------------------------

PROJECT_DDL = """
-- The unit a timesheet reports against. In the USER region: a declared project is the
-- user's statement, not something derivable from any source.
CREATE TABLE user_project (
    id               INTEGER PRIMARY KEY,
    name             TEXT    NOT NULL,
    normalised_name  TEXT    NOT NULL UNIQUE,
    ad_hoc           INTEGER NOT NULL DEFAULT 0 CHECK (ad_hoc IN (0,1)),
    first_seen_utc   INTEGER NOT NULL
) STRICT;
"""

REPOSITORY_DDL = """
-- A discovered repository. In the RAW region: a fact about the world, rediscoverable.
CREATE TABLE raw_repository (
    id              INTEGER PRIMARY KEY,
    identity        TEXT    NOT NULL UNIQUE,
    identity_kind   TEXT    NOT NULL CHECK (identity_kind IN ('git_dir','root_commit')),
    -- Read but not used as the identity: two independent repositories can share a
    -- root commit, and collapsing them would silently mix two projects' work.
    root_commit     TEXT,
    name            TEXT    NOT NULL,
    first_seen_utc  INTEGER NOT NULL,
    last_seen_utc   INTEGER NOT NULL
) STRICT;

-- One identity, many paths: a linked worktree resolves to its origin's common
-- directory, so it is the same repository seen twice. An independent clone gets its
-- own identity and stays separate.
CREATE TABLE raw_repository_path (
    repository_id  INTEGER NOT NULL REFERENCES raw_repository(id) ON DELETE CASCADE,
    path           TEXT    NOT NULL,
    is_bare        INTEGER NOT NULL DEFAULT 0 CHECK (is_bare IN (0,1)),
    is_worktree    INTEGER NOT NULL DEFAULT 0 CHECK (is_worktree IN (0,1)),
    last_seen_utc  INTEGER NOT NULL,
    PRIMARY KEY (repository_id, path)
) STRICT;

CREATE INDEX raw_repository_path_by_path ON raw_repository_path (path);
"""

#: `derived_attribution` as of v2 — project_id in place of the free-text placeholder
#: `0001` left for this feature. A text key cannot satisfy FR-024: renaming a project
#: would be a delete plus an insert, and the history would silently go elsewhere.
DERIVED_V2_DDL = """
CREATE TABLE derived_attribution (
    id              INTEGER PRIMARY KEY,
    record_id       INTEGER NOT NULL REFERENCES raw_record(id) ON DELETE CASCADE,
    project_id      INTEGER NOT NULL REFERENCES user_project(id),
    rule            TEXT    NOT NULL,
    evidence        TEXT    NOT NULL CHECK (json_valid(evidence)),
    derived_at_utc  INTEGER NOT NULL
) STRICT;

CREATE INDEX derived_attribution_record  ON derived_attribution (record_id);
CREATE INDEX derived_attribution_project ON derived_attribution (project_id);
"""

# --- v3: correspondents (feature 0004) -----------------------------------------------

CORRESPONDENT_DDL = """
-- Everyone the user has sent mail to. In the RAW region: an address is what a source
-- said, not something the user declared.
--
-- A table rather than a field in a payload because FR-054 asks which correspondents
-- contribute most to a project, and that is a group-by. Answering it by parsing every
-- record's JSON would be slow, untypable, and impossible to index.
CREATE TABLE raw_correspondent (
    id              INTEGER PRIMARY KEY,
    address         TEXT    NOT NULL UNIQUE,
    display_name    TEXT,
    domain          TEXT    NOT NULL,
    first_seen_utc  INTEGER NOT NULL
) STRICT;

-- Domain rules match on it and the ad-hoc project fallback counts it, so it is stored
-- rather than re-split from the address on every row.
CREATE INDEX raw_correspondent_domain ON raw_correspondent (domain);

-- Which addresses appeared on which message, and how. A broadcast to fifty people is
-- fifty rows, deliberately: truncating would hide that it was a broadcast.
--
-- There is no 'bcc' role. It names people the other recipients were not told about, it
-- is the most sensitive field in a header, and attribution has no use for it.
CREATE TABLE raw_record_correspondent (
    record_id         INTEGER NOT NULL REFERENCES raw_record(id) ON DELETE CASCADE,
    correspondent_id  INTEGER NOT NULL REFERENCES raw_correspondent(id),
    role              TEXT    NOT NULL CHECK (role IN ('sender','to','cc')),
    PRIMARY KEY (record_id, correspondent_id, role)
) STRICT;

CREATE INDEX raw_record_correspondent_by_correspondent
    ON raw_record_correspondent (correspondent_id);
"""

#: A fresh store is created at the latest version directly, so `ALL_DDL` is v3.
ALL_DDL = (
    RAW_DDL,
    DERIVED_V2_DDL,
    USER_DDL,
    PROJECT_DDL,
    REPOSITORY_DDL,
    CORRESPONDENT_DDL,
)

#: What `m0001` created, kept so the migration path stays testable from a real v1 store.
V1_DDL = (RAW_DDL, DERIVED_DDL, USER_DDL)

#: What a store looked like after `m0002`, for the same reason.
V2_DDL = (RAW_DDL, DERIVED_V2_DDL, USER_DDL, PROJECT_DDL, REPOSITORY_DDL)


def statements(*blocks: str) -> tuple[str, ...]:
    """Split DDL blocks into individual statements.

    Migrations must run each statement with ``execute()``, never ``executescript()``:
    Python's sqlite3 issues an implicit COMMIT before running a script, which would
    close the migration's transaction and silently defeat the rollback guarantee that
    FR-021 rests on.

    Splitting must understand ``--`` comments and quoted strings. A naive
    ``split(";")`` cuts a comment containing a semicolon in half, and the tail — no
    longer preceded by its ``--`` — becomes bare tokens that fail with a syntax error
    pointing at an innocent word. The same applies inside a string literal.
    """
    found: list[str] = []
    for block in blocks:
        current: list[str] = []
        in_comment = False
        in_string = False
        for char in block:
            if in_comment:
                current.append(char)
                if char == "\n":
                    in_comment = False
                continue
            if in_string:
                current.append(char)
                if char == "'":
                    in_string = False
                continue
            if char == "'":
                in_string = True
                current.append(char)
                continue
            if char == "-" and current and current[-1] == "-":
                in_comment = True
                current.append(char)
                continue
            if char == ";":
                statement = "".join(current).strip()
                if statement:
                    found.append(statement)
                current = []
                continue
            current.append(char)
        tail = "".join(current).strip()
        if tail:
            found.append(tail)
    return tuple(found)
