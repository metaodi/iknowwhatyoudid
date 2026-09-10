"""Initial schema: the three regions at v1."""

from __future__ import annotations

import sqlite3

from .. import schema

VERSION = 1


def upgrade(connection: sqlite3.Connection) -> None:
    """Create the schema exactly as v1 had it.

    Pinned to `V1_DDL`, not to whatever the current schema is: a migration describes a
    step between two fixed versions. If this followed `ALL_DDL` it would create today's
    tables and then `m0002` would try to migrate a store that never had a v1 shape —
    and the upgrade path from a real v1 store would stop being tested.
    """
    # execute(), never executescript() — see schema.statements().
    for statement in schema.statements(*schema.V1_DDL):
        connection.execute(statement)
