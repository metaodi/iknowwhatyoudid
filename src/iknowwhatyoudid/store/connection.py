"""Opening the store: pragmas, locking, and the version gate (FR-022, FR-025, FR-026)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..errors import (
    StoreCorruptError,
    StoreLockedError,
    UnsupportedSQLiteError,
)
from ..protection import permissions
from . import schema
from .location import ensure_parent_dir

DEFAULT_BUSY_TIMEOUT_MS = 5000


def sqlite_version() -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in sqlite3.sqlite_version.split(".")[:3])
    return major, minor, patch


def require_supported_sqlite() -> None:
    if sqlite_version() < schema.MINIMUM_SQLITE:
        wanted = ".".join(str(part) for part in schema.MINIMUM_SQLITE)
        raise UnsupportedSQLiteError(
            f"SQLite {sqlite3.sqlite_version} is too old; this store needs {wanted} or newer",
            remedy="Upgrade Python, or install a build with a newer bundled SQLite.",
        )


def connect(
    path: Path,
    *,
    create: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """Open the store with the pragmas the durability requirements rest on.

    ``isolation_level=None`` turns off the driver's implicit transaction handling so
    that transactions are opened explicitly with BEGIN IMMEDIATE — which is what makes
    contention surface before any work is done rather than at COMMIT (FR-025).
    """
    require_supported_sqlite()

    if not path.exists():
        if not create:
            raise StoreCorruptError(
                f"no store at {path}",
                remedy="Run any store command without --store to create the default store.",
            )
        ensure_parent_dir(path)

    fresh = not path.exists()
    connection = sqlite3.connect(
        path, isolation_level=None, timeout=busy_timeout_ms / 1000.0
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        connection.execute("PRAGMA synchronous = FULL")
    except sqlite3.DatabaseError as exc:
        connection.close()
        raise StoreCorruptError(
            f"{path} could not be opened as a store: {exc}",
            remedy=(
                "Check the path points at an iknowwhatyoudid store. "
                "The file has not been modified."
            ),
        ) from exc

    if fresh:
        permissions.restrict_to_owner(path)
    return connection


@contextmanager
def writing(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """A write transaction: all of it lands, or none of it does (FR-013).

    BEGIN IMMEDIATE takes the write lock up front, so a competing writer is detected
    now rather than after the work has been done.
    """
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc) or "busy" in str(exc):
            raise StoreLockedError(
                "another iknowwhatyoudid command is using the store",
                remedy="Wait for it to finish, then run this command again.",
            ) from exc
        raise
    try:
        yield connection
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def set_user_version(connection: sqlite3.Connection, version: int) -> None:
    # Not parameterisable: PRAGMA takes a literal. The value is an int by signature.
    connection.execute(f"PRAGMA user_version = {int(version)}")


def quick_check(connection: sqlite3.Connection) -> str:
    """The cheap integrity check run on open (FR-026).

    The full integrity_check is O(database) and would blow the five-second budget that
    `store info` has to meet, so it lives behind an explicit `store check`.
    """
    row = connection.execute("PRAGMA quick_check(1)").fetchone()
    return str(row[0])


def integrity_check(connection: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
