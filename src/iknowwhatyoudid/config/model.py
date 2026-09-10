"""The configuration as parsed (see data-model.md)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..protection.permissions import PermissionReport


@dataclass(frozen=True, slots=True)
class CredentialReference:
    """A name pointing at a secret held elsewhere.

    Has no field capable of holding a value, so a credential cannot leak through this
    type by mistake (FR-020).
    """

    name: str


@dataclass(frozen=True, slots=True)
class ConfiguredSource:
    name: str
    kind: str
    index: int
    enabled: bool = True
    since: datetime | None = None
    credential: CredentialReference | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key_path(self) -> str:
        return f"source[{self.index}]"

    def setting_path(self, key: str) -> str:
        return f"{self.key_path}.{key}"


@dataclass(frozen=True, slots=True)
class SourceConfiguration:
    path: Path
    raw_text: str
    sources: tuple[ConfiguredSource, ...] = ()
    version: int = 1
    permissions: PermissionReport | None = None

    def by_name(self, name: str) -> ConfiguredSource | None:
        for source in self.sources:
            if source.name == name:
                return source
        return None

    @property
    def names(self) -> frozenset[str]:
        return frozenset(source.name for source in self.sources)
