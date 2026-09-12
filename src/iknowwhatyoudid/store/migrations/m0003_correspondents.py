"""v2 -> v3: correspondents.

`0004` records who the user sent mail to. An address is queried, not merely displayed --
FR-054 asks which correspondents contribute most to a project, and that is a group-by --
so it becomes a table rather than a field inside a payload.

Nothing that already exists is touched. There is no backfill because no mail exists
before this feature, and `derived_attribution` is unchanged in shape: the new rule values
this feature introduces are data, not schema.

Every statement runs with `execute()` inside the runner's single transaction. Never
`executescript()`: Python's sqlite3 issues an implicit COMMIT before a script, which
would close the transaction and defeat the rollback guarantee `0001` FR-021 rests on.
This is written down because it is the mistake `m0002` had to be corrected for, and the
next author will not have been there.
"""

from __future__ import annotations

import sqlite3

from .. import schema

VERSION = 3


def upgrade(connection: sqlite3.Connection) -> None:
    # execute(), never executescript() -- see the module docstring.
    for statement in schema.statements(schema.CORRESPONDENT_DDL):
        connection.execute(statement)
