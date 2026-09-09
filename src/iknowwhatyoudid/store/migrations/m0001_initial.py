"""Initial schema: the three regions at v1."""

from __future__ import annotations

import sqlite3

from .. import schema

VERSION = 1


def upgrade(connection: sqlite3.Connection) -> None:
    # execute(), never executescript() — see schema.statements().
    for statement in schema.statements(*schema.ALL_DDL):
        connection.execute(statement)
