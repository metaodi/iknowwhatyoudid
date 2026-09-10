"""Best-effort key-path to line-number resolution (research D2).

`tomllib` discards position information for values it parses successfully, so a semantic
finding has no line from the parser. Rather than re-implement TOML or add a dependency
to improve an error message, this searches the raw text for the key inside the relevant
``[[source]]`` block.

It succeeds for the ordinary case — a key written once on its own line — and returns
``None`` for the awkward ones rather than reporting a wrong line. Tests assert on key
paths, never on line numbers, so this can never break the suite.
"""

from __future__ import annotations

import re

_SOURCE_HEADER = re.compile(r"^\s*\[\[\s*source\s*\]\]", re.M)


def source_block_bounds(text: str, index: int) -> tuple[int, int] | None:
    """Character offsets of the ``index``-th ``[[source]]`` block (0-based)."""
    headers = list(_SOURCE_HEADER.finditer(text))
    if index < 0 or index >= len(headers):
        return None
    start = headers[index].start()
    end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
    return start, end


def line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def find_source_line(text: str, index: int) -> int | None:
    """The line the ``index``-th ``[[source]]`` header sits on."""
    bounds = source_block_bounds(text, index)
    return None if bounds is None else line_of_offset(text, bounds[0])


def find_key_line(text: str, index: int, key: str) -> int | None:
    """The line where *key* is assigned inside source *index*, if unambiguous."""
    bounds = source_block_bounds(text, index)
    if bounds is None:
        return None
    start, end = bounds
    block = text[start:end]

    # Dotted keys may be written either as `folders.include = ...` or under a
    # `[source.folders]` table; only the flat form is located.
    pattern = re.compile(
        r"^\s*" + re.escape(key) + r"\s*=", re.M
    )
    matches = list(pattern.finditer(block))
    if len(matches) != 1:
        return None  # absent, or repeated — do not guess
    return line_of_offset(text, start + matches[0].start())


def find_top_level_key_line(text: str, key: str) -> int | None:
    """The line of a top-level assignment or table header, if unambiguous."""
    first_source = _SOURCE_HEADER.search(text)
    head = text[: first_source.start()] if first_source else text
    pattern = re.compile(
        r"^\s*(?:\[\s*" + re.escape(key) + r"\s*\]|" + re.escape(key) + r"\s*=)", re.M
    )
    matches = list(pattern.finditer(head))
    if len(matches) != 1:
        # A table like [projects] may appear after the sources; search the whole text.
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            return None
        return line_of_offset(text, matches[0].start())
    return line_of_offset(text, matches[0].start())
