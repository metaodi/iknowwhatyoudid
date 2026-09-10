"""The source-kind boundary (FR-026 to FR-032).

Written as though it were public — complete enough that a kind supplied from outside
this project would need nothing further — while the registry loads only kinds from
inside it. See contracts/source-kind.md.

The declaration is *data*, not behaviour, because FR-028 and FR-032 both need it
enumerable and printable: `sources kinds` renders it, `--json` serialises it, and
validation walks it. A validation library would enforce the same constraints while
making them hard to describe.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from ..config.findings import Finding
    from ..config.model import ConfiguredSource
    from ..records.model import NormalizedRecord, RunMode


class SettingType(StrEnum):
    STRING = "string"
    BOOL = "bool"
    INTEGER = "integer"
    DATETIME = "datetime"
    STRING_LIST = "string_list"
    PATH_LIST = "path_list"
    IDENTITY_LIST = "identity_list"


#: Which Python types each setting type accepts once TOML has parsed the file.
_ACCEPTS: Mapping[SettingType, tuple[type, ...]] = {
    SettingType.STRING: (str,),
    SettingType.BOOL: (bool,),
    SettingType.INTEGER: (int,),
    SettingType.DATETIME: (datetime,),
    SettingType.STRING_LIST: (list,),
    SettingType.PATH_LIST: (list,),
    SettingType.IDENTITY_LIST: (list,),
}


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    type: SettingType
    required: bool = False
    default: object | None = None
    help: str = ""

    @property
    def is_list(self) -> bool:
        return self.type in {
            SettingType.STRING_LIST,
            SettingType.PATH_LIST,
            SettingType.IDENTITY_LIST,
        }

    def accepts(self, value: object) -> bool:
        # bool is a subclass of int in Python, so an INTEGER setting must not silently
        # accept `true`.
        if self.type is SettingType.INTEGER and isinstance(value, bool):
            return False
        if self.is_list:
            return isinstance(value, list) and all(
                isinstance(item, str) for item in value
            )
        return isinstance(value, _ACCEPTS[self.type])


class ReadingAvailability(StrEnum):
    AVAILABLE = "available"
    NOT_YET_IMPLEMENTED = "not_yet_implemented"


class CredentialHandle(Protocol):
    """Opaque: it authenticates a request and never yields the secret.

    A reader therefore cannot log or store a credential even by accident (FR-022).
    """

    @property
    def name(self) -> str: ...


@dataclass(frozen=True, slots=True)
class LiveCheckResult:
    reachable: bool
    detail: str


class SourceReader(Protocol):
    """What a kind must supply to actually read.

    There is deliberately **no write operation** — not "must not write" as a rule a
    connector could break, but no method through which a connector could express one.
    Principle II holds at the type level rather than by review.
    """

    def validate(self, source: ConfiguredSource) -> Sequence[Finding]:
        """Kind-specific checks beyond the declaration. Offline: contacts nothing."""

    def check_live(
        self, source: ConfiguredSource, credential: CredentialHandle | None
    ) -> LiveCheckResult:
        """Confirm the source is reachable and the credential accepted. Read-only."""

    def read(
        self,
        source: ConfiguredSource,
        credential: CredentialHandle | None,
        since: datetime | None,
        mode: RunMode,
    ) -> Iterator[NormalizedRecord]:
        """Yield records at or after *since*. Read-only; streams rather than accumulates.

        ``mode`` states whether this read is exhaustive over its window. The store
        cannot infer it — an incremental read that returns nothing looks identical to a
        source that has lost everything — so the connector must say. Only a sweep may
        cause a record to be marked withdrawn.
        """


@dataclass(frozen=True, slots=True)
class SourceKind:
    name: str
    summary: str
    settings: tuple[SettingSpec, ...] = ()
    credential_required: bool = False
    required_access: tuple[str, ...] = ()
    destinations: tuple[str, ...] = ()
    reading: ReadingAvailability = ReadingAvailability.NOT_YET_IMPLEMENTED
    reader: SourceReader | None = None
    arrives_in: str | None = None  # e.g. "0003", for the honest "not yet" message

    @property
    def is_readable(self) -> bool:
        return self.reading is ReadingAvailability.AVAILABLE and self.reader is not None

    def setting(self, key: str) -> SettingSpec | None:
        for spec in self.settings:
            if spec.key == key:
                return spec
        return None

    def as_dict(self) -> dict[str, Any]:
        """The declaration, serialised for `sources kinds --json` (FR-028, FR-032).

        The same data validation walks, so the documented contract and the enforced one
        cannot drift.
        """
        return {
            "name": self.name,
            "summary": self.summary,
            "credential_required": self.credential_required,
            "required_access": list(self.required_access),
            "destinations": list(self.destinations),
            "reading": self.reading.value,
            "arrives_in": self.arrives_in,
            "settings": [
                {
                    "key": s.key,
                    "type": s.type.value,
                    "required": s.required,
                    "default": s.default,
                    "help": s.help,
                }
                for s in self.settings
            ],
        }


@dataclass(frozen=True, slots=True)
class KindSettings:
    """A source's settings resolved against its kind's declaration."""

    values: Mapping[str, object] = field(default_factory=dict)

    def get(self, key: str, default: object | None = None) -> object | None:
        return self.values.get(key, default)
