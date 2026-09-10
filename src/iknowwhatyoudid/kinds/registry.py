"""The in-project kind registry (FR-031).

An explicit mapping, populated by direct import. There is deliberately **no** code path
that scans the filesystem, reads entry points, or dynamically imports anything, so
loading a kind from outside this project cannot be enabled by accident or by a stray
file. Relaxing FR-031 later means adding a discovery function that populates this same
mapping — no change to the contract, and no change to any user's configuration file.
"""

from __future__ import annotations

from collections.abc import Mapping

from . import calendar, fixture, git_local, mail
from .spec import SourceKind

_BUILT_IN: tuple[SourceKind, ...] = (
    fixture.KIND,
    git_local.KIND,
    mail.OUTLOOK,
    mail.GMAIL,
    mail.HEY,
    calendar.OUTLOOK,
    calendar.GOOGLE,
)

_KINDS: dict[str, SourceKind] = {kind.name: kind for kind in _BUILT_IN}


def all_kinds() -> tuple[SourceKind, ...]:
    return tuple(sorted(_KINDS.values(), key=lambda k: k.name))


def names() -> tuple[str, ...]:
    return tuple(kind.name for kind in all_kinds())


def get(name: str) -> SourceKind | None:
    return _KINDS.get(name)


def is_registered(name: str) -> bool:
    return name in _KINDS


def register_for_test(kind: SourceKind) -> None:
    """Add a kind, for tests only.

    User Story 4 proves that a new kind needs no change to any existing kind and no
    change to any user's configuration file. Exercising that through the same mapping
    the product uses demonstrates the property without opening a loading path that
    FR-031 forbids — this function is called from tests, never from `src/`.
    """
    _KINDS[kind.name] = kind


def unregister_for_test(name: str) -> None:
    """Undo `register_for_test`, so tests do not leak into one another."""
    if name in _KINDS and all(kind.name != name for kind in _BUILT_IN):
        del _KINDS[name]


def reset_for_test() -> None:
    _KINDS.clear()
    _KINDS.update({kind.name: kind for kind in _BUILT_IN})


def built_in_names() -> frozenset[str]:
    return frozenset(kind.name for kind in _BUILT_IN)


def as_mapping() -> Mapping[str, SourceKind]:
    return dict(_KINDS)
