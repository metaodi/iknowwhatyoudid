"""The single place a payload becomes text.

Both the human and the ``--json`` form go through here, so anything that must hold for
all output — ordering, and later redaction — is structural rather than a convention every
future command has to remember.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from ..credentials.redaction import redact

SCHEMA = "iknowwhatyoudid/v1"

MICROSECONDS = 1_000_000


def envelope(
    command: str,
    *,
    ok: bool,
    store_path: str,
    data: Mapping[str, Any] | None = None,
    findings: Sequence[Mapping[str, Any]] = (),
) -> str:
    """The one place a payload becomes JSON — so redaction is structural (FR-022).

    A `--json` path that skipped redaction would be the obvious leak, which is why both
    forms go through this module rather than each command formatting its own output.
    """
    return redact(
        json.dumps(
            {
                "schema": SCHEMA,
                "command": command,
                "ok": ok,
                "store_path": store_path,
                "data": dict(data or {}),
                "findings": list(findings),
            },
            ensure_ascii=False,
            default=str,
        )
    )


def human(text: str) -> str:
    """The same chokepoint for human output."""
    return redact(text)


def finding_payload(finding: Any) -> dict[str, Any]:
    """One finding, as `--json` consumers see it.

    `code` is the stable contract; `message` wording stays free to improve, and `line`
    may be null because it is best-effort (research D2).
    """
    return {
        "severity": finding.severity.value,
        "code": finding.code,
        "source_name": finding.source_name,
        "key_path": finding.key_path,
        "line": finding.line,
        "message": finding.message,
        "remedy": finding.remedy,
    }


def when(micros: int | None, *, date_only: bool = False) -> str:
    if micros is None:
        return "-"
    moment = datetime.fromtimestamp(micros / MICROSECONDS, tz=UTC)
    return moment.strftime("%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M")


def size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """A fixed-width table whose column widths are stable for a given set of rows."""
    if not rows:
        return ""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()

    return "\n".join([line(headers), *(line(row) for row in rows)])
