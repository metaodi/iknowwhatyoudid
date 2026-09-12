"""Recorded provider responses, loaded from disk so no test embeds a payload inline.

A response recorded once and read from a file is reviewable: someone can look at what a
provider actually returns. A dict typed into a test is a guess about what it returns,
and drifts from reality without anyone noticing.

Nothing here contacts a provider. The files are recordings, edited only to replace real
addresses with fixture ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent


def load(name: str) -> Any:
    """Read one recorded response by file name, without the `.json`."""
    path = HERE / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no recorded response named {name!r} in {HERE}. "
            "Recordings are committed; they are never fetched at test time."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def graph_page(*messages: dict[str, Any], delta_link: str | None = None,
               next_link: str | None = None) -> dict[str, Any]:
    """One page of a Graph `/messages/delta` response, in its documented shape."""
    page: dict[str, Any] = {"value": list(messages)}
    if next_link:
        page["@odata.nextLink"] = next_link
    if delta_link:
        page["@odata.deltaLink"] = delta_link
    return page
