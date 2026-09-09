"""Applying schema migrations in place (FR-020 to FR-022).

The whole of FR-021 — "a migration that cannot complete leaves the store at its previous
version, fully usable" — is one BEGIN IMMEDIATE, because SQLite's DDL is transactional
*and* PRAGMA user_version participates in the rollback. Both were verified against the
target SQLite; see research.md R1.

The pre-migration file snapshot is therefore the *second* safety net, for what a
transaction cannot cover (the process being killed mid-COMMIT, the disk filling), not
the primary rollback mechanism.
"""

from __future__ import annotations

import importlib
import pkgutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..errors import MigrationError, StoreTooNewError
from . import migrations
from .connection import set_user_version, user_version, writing


class Migration(Protocol):
    VERSION: int

    def upgrade(self, connection: sqlite3.Connection) -> None: ...


@dataclass(frozen=True, slots=True)
class MigrationStep:
    version: int
    name: str
    upgrade: object  # Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    current: int
    target: int
    steps: tuple[MigrationStep, ...]

    @property
    def is_noop(self) -> bool:
        return not self.steps


def discover() -> tuple[MigrationStep, ...]:
    """Every migration module in `store.migrations`, ordered by version."""
    steps: list[MigrationStep] = []
    for info in pkgutil.iter_modules(migrations.__path__):
        if not info.name.startswith("m"):
            continue
        module = importlib.import_module(f"{migrations.__name__}.{info.name}")
        version = getattr(module, "VERSION", None)
        upgrade = getattr(module, "upgrade", None)
        if version is None or upgrade is None:
            continue
        steps.append(MigrationStep(int(version), info.name, upgrade))
    steps.sort(key=lambda step: step.version)
    return tuple(steps)


def highest_known_version() -> int:
    steps = discover()
    return steps[-1].version if steps else 0


def plan(connection: sqlite3.Connection) -> MigrationPlan:
    current = user_version(connection)
    steps = discover()
    highest = steps[-1].version if steps else 0
    if current > highest:
        raise StoreTooNewError(
            f"this store is at schema v{current}, but this version of the tool only "
            f"knows up to v{highest}",
            remedy="Upgrade iknowwhatyoudid. Nothing has been changed.",
        )
    pending = tuple(step for step in steps if step.version > current)
    return MigrationPlan(current=current, target=highest, steps=pending)


def snapshot_path(store: Path, version: int) -> Path:
    return store.with_name(f"{store.name}.pre-v{version}")


def take_snapshot(connection: sqlite3.Connection, store: Path, version: int) -> Path | None:
    """Copy the store aside via the online backup API. Best effort."""
    destination = snapshot_path(store, version)
    try:
        with sqlite3.connect(destination) as backup:
            connection.backup(backup)
    except (sqlite3.Error, OSError):
        return None
    return destination


def migrate(connection: sqlite3.Connection, store: Path) -> MigrationPlan:
    """Bring the store up to the highest known version, or leave it entirely alone."""
    pending = plan(connection)
    if pending.is_noop:
        return pending

    snapshot = None
    if pending.current > 0:
        # Nothing worth snapshotting when creating a store from nothing.
        snapshot = take_snapshot(connection, store, pending.current)

    try:
        with writing(connection):
            for step in pending.steps:
                step.upgrade(connection)  # type: ignore[operator]
            set_user_version(connection, pending.target)
    except Exception as exc:
        detail = f"migration to v{pending.target} failed: {exc}"
        if snapshot is not None:
            detail += f"\nSnapshot retained: {snapshot}"
        raise MigrationError(
            detail,
            remedy=(
                f"The store is unchanged at schema v{pending.current} and fully usable. "
                "No records or corrections were lost."
            ),
        ) from exc

    return pending


def ensure_current(connection: sqlite3.Connection, store: Path) -> MigrationPlan:
    """Run pending migrations automatically when a command opens an older store."""
    return migrate(connection, store)
