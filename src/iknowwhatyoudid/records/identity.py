"""A stable identifier for sources that supply none of their own (FR-009).

FR-009 exists so that FR-011 (re-ingesting creates no duplicates) still holds for such
sources, which requires the identifier to be a deterministic function of content and
*nothing else* — not insertion order, not wall-clock time, not dict iteration order.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

DERIVED_PREFIX = "derived:"
_DIGEST_BYTES = 20  # BLAKE2b-160


def canonical_json(value: Any) -> str:
    """A serialisation that is identical for equal content, across runs and processes."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def derive_source_id(
    source: str, occurred_utc: int, title: str, payload: Mapping[str, Any]
) -> str:
    """Content-derived identifier, prefixed so it is never mistaken for a source's own.

    The prefix matters: FR-014 treats a changed-content record as the *same* record,
    which is right for a source-issued id but impossible for a content-derived one —
    changed content necessarily yields a different digest. The two cases must stay
    distinguishable rather than silently conflated.
    """
    material = canonical_json(
        {
            "source": source,
            "occurred_utc": occurred_utc,
            "title": title,
            "payload": payload,
        }
    )
    digest = hashlib.blake2b(material.encode("utf-8"), digest_size=_DIGEST_BYTES)
    return f"{DERIVED_PREFIX}{digest.hexdigest()}"


def is_derived(source_id: str) -> bool:
    return source_id.startswith(DERIVED_PREFIX)
