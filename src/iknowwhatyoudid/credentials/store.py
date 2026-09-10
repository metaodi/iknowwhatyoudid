"""Presence-only credential resolution (FR-020, FR-021, research D6).

This feature never authenticates to anything — the three real kinds are declarations
only. What it must do is report which credential each source needs and whether it is
present, without revealing the value. Presence is the entire requirement, and a store
that cannot return a value cannot leak one.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..protection import permissions
from . import redaction


class CredentialPresence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    name: str
    presence: CredentialPresence
    detail: str = ""


class CredentialStore:
    """Answers one question: is this named credential present?

    There is deliberately no method returning a value. A future feature that must
    actually authenticate adds one behind this boundary; until then the type cannot leak
    what it does not expose.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._names: frozenset[str] | None = None
        self._error: str | None = None

    def _load(self) -> None:
        if self._names is not None or self._error is not None:
            return
        if not self.path.exists():
            self._names = frozenset()
            return
        try:
            document = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            self._error = str(exc)
            self._names = frozenset()
            return

        table = document.get("credential", {})
        if not isinstance(table, dict):
            self._error = "`credential` is not a table"
            self._names = frozenset()
            return

        self._names = frozenset(str(name) for name in table)
        # Register any values so the render chokepoint can mask them if they ever
        # reach output. The values are never returned to a caller.
        for entry in table.values():
            if isinstance(entry, dict):
                for value in entry.values():
                    if isinstance(value, str):
                        redaction.register(value)
            elif isinstance(entry, str):
                redaction.register(entry)

    def permissions(self) -> permissions.PermissionReport:
        return permissions.check(self.path)

    def status(self, name: str) -> CredentialStatus:
        self._load()
        if self._error is not None:
            return CredentialStatus(
                name, CredentialPresence.UNREADABLE, f"{self.path}: {self._error}"
            )
        assert self._names is not None
        if name in self._names:
            return CredentialStatus(name, CredentialPresence.PRESENT, str(self.path))
        return CredentialStatus(
            name, CredentialPresence.ABSENT, f"not found in {self.path}"
        )

    def known_names(self) -> frozenset[str]:
        self._load()
        return self._names or frozenset()
