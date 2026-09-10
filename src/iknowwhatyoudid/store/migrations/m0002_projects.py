"""v1 → v2: projects and repositories.

`0001` created `derived_attribution.project` as free text — an honest placeholder for
this feature. A text key cannot satisfy FR-024: renaming a project would be a delete plus
an insert, and the history attributed to it would silently go elsewhere. This migration
gives a project a stable identity and points attributions at it.

Every statement runs with `execute()` inside the runner's single transaction. Never
`executescript()`: Python's sqlite3 issues an implicit COMMIT before a script, which
would close the transaction and defeat the rollback guarantee `0001` FR-021 rests on.
"""

from __future__ import annotations

import sqlite3

from ...records import timestamps
from .. import schema

VERSION = 2


def upgrade(connection: sqlite3.Connection) -> None:
    now = timestamps.now_micros()

    for statement in schema.statements(schema.PROJECT_DDL, schema.REPOSITORY_DDL):
        connection.execute(statement)

    # Every project name already in use becomes a *declared* project. Marking them
    # ad-hoc would invent a provenance: they were written by something before this
    # feature existed, and the conservative assumption is that the user meant them.
    connection.execute(
        """
        INSERT INTO user_project (name, normalised_name, ad_hoc, first_seen_utc)
        SELECT project, lower(trim(project)), 0, ?
        FROM (
            SELECT project, min(rowid) AS first_row
            FROM derived_attribution
            WHERE trim(project) <> ''
            GROUP BY lower(trim(project))
        )
        ORDER BY first_row
        """,
        (now,),
    )

    # Rebuild onto project_id. SQLite cannot drop a column from a STRICT table with a
    # constraint on it, so the table is recreated and refilled — which is also what makes
    # the whole change atomic with the version bump.
    # RENAME carries the table's indexes along, keeping their original names, so the
    # v2 CREATE INDEX would collide with them. Drop them first; the table they belong to
    # is about to go anyway.
    connection.execute("DROP INDEX IF EXISTS derived_attribution_record")
    connection.execute("ALTER TABLE derived_attribution RENAME TO derived_attribution_v1")
    for statement in schema.statements(schema.DERIVED_V2_DDL):
        connection.execute(statement)

    connection.execute(
        """
        INSERT INTO derived_attribution
            (id, record_id, project_id, rule, evidence, derived_at_utc)
        SELECT d.id, d.record_id, p.id, d.rule, d.evidence, d.derived_at_utc
        FROM derived_attribution_v1 d
        JOIN user_project p ON p.normalised_name = lower(trim(d.project))
        """
    )
    connection.execute("DROP TABLE derived_attribution_v1")

    # `user_correction.project` is deliberately left as text. A correction is the user
    # naming a project in their own words — their statement, and the only irreplaceable
    # data in the store. Resolving it to an id would mean either rejecting a correction
    # that names a project not yet declared, or inventing a project on their behalf.
    # It also keeps `0001`'s correction export format unchanged, so exports written
    # before this migration still import afterwards.
