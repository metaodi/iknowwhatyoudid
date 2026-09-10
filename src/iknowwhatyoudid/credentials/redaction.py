"""Redaction registry (FR-022, research D7).

One chokepoint. `cli/render.py` is the only place a payload becomes text, and it applies
`redact()` there — so the property holds for every command written from now on,
including ones nobody has thought of yet. Enforced per call site it would be a
convention that decays.
"""

from __future__ import annotations

import logging
import re

MASK = "***"

#: Values known to be secret. Populated when a credential is resolved.
_SECRETS: set[str] = set()

#: Below this length a "secret" is too short to redact without mangling ordinary text.
_MIN_LENGTH = 6


def register(value: str) -> None:
    if value and len(value) >= _MIN_LENGTH:
        _SECRETS.add(value)


def clear() -> None:
    _SECRETS.clear()


def known_count() -> int:
    return len(_SECRETS)


def redact(text: str) -> str:
    """Replace every registered secret with the mask."""
    if not _SECRETS or not text:
        return text
    for secret in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return text


class RedactingFilter(logging.Filter):
    """Applies the same registry to the diagnostics path."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a for a in record.args
                )
        return True


def install_log_filter(logger: logging.Logger) -> None:
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())
