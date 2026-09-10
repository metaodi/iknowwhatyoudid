"""Noticing a secret pasted into the configuration file (FR-023, research D8).

Two signals used together: a key name that suggests a secret, or a value with a
recognisable credential shape. Findings are **warnings**, never blocking — a heuristic
that can stop a user working is not an acceptable heuristic.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

#: Key names that almost always mean a secret was written where a reference belongs.
_SUSPICIOUS_KEYS = re.compile(
    r"(password|passwd|secret|token|api[_.-]?key|apikey|access[_.-]?key"
    r"|private[_.-]?key|client[_.-]?secret|auth|bearer|credentials?)$",
    re.I,
)

#: Shapes that are unmistakably credentials whatever the key is called.
_SHAPES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
)

#: A long, high-entropy, base64-ish run with no structure that suggests it is a path,
#: an address, or an identifier.
_OPAQUE = re.compile(r"^[A-Za-z0-9+/=_-]{32,}$")
_ENTROPY_THRESHOLD = 3.6


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return -sum(
        (n / total) * math.log2(n / total) for n in counts.values()
    )


def looks_like_secret(key: str, value: object) -> bool:
    """Whether *value*, written under *key*, looks like a pasted credential."""
    if not isinstance(value, str) or not value:
        return False

    for shape in _SHAPES:
        if shape.search(value):
            return True

    leaf = key.rsplit(".", 1)[-1]
    if _SUSPICIOUS_KEYS.search(leaf) and len(value) >= 6:
        return True

    # An opaque high-entropy blob under an innocuous key name. Deliberately narrow:
    # entropy alone flags commit hashes, SIDs and long ids, so a candidate must also
    # have the *shape* of a generated token — mixed case and at least one digit. A
    # lowercase hex hash and a digits-and-hyphens SID both fail that, which is the
    # point: a false positive on ordinary configuration makes the whole check useless.
    if (
        _OPAQUE.match(value)
        and _mixed_alphabet(value)
        and _entropy(value) >= _ENTROPY_THRESHOLD
    ):
        return True

    return False


def _mixed_alphabet(value: str) -> bool:
    return (
        any(c.islower() for c in value)
        and any(c.isupper() for c in value)
        and any(c.isdigit() for c in value)
    )


def scan(settings: Mapping[str, Any]) -> list[str]:
    """Return the setting keys whose values look like secrets."""
    found: list[str] = []
    for key, value in settings.items():
        if looks_like_secret(key, value):
            found.append(key)
        elif isinstance(value, list):
            if any(looks_like_secret(key, item) for item in value):
                found.append(key)
    return found
