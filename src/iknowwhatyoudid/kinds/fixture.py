"""The `fixture` kind — the one that actually reads (FR-034).

It reads recorded data from disk, which is what proves the whole contract end to end
before any real connector exists. Every integration test configures one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

from ..config.findings import Finding, blocking
from ..config.model import ConfiguredSource
from ..records.model import NormalizedRecord, RunMode
from .spec import (
    CredentialHandle,
    LiveCheckResult,
    ReadingAvailability,
    SettingSpec,
    SettingType,
    SourceKind,
)

MISSING_RECORDED_FILE = "recorded-file-missing"
BAD_RECORDED_FILE = "recorded-file-invalid"


def _paths(source: ConfiguredSource) -> list[Path]:
    raw = source.settings.get("recorded", [])
    if not isinstance(raw, list):
        return []
    return [Path(str(item)).expanduser() for item in raw]


class FixtureReader:
    """Reads normalized records from JSON Lines files. Read-only, and local."""

    def validate(self, source: ConfiguredSource) -> Sequence[Finding]:
        problems: list[Finding] = []
        for path in _paths(source):
            if not path.exists():
                problems.append(
                    blocking(
                        MISSING_RECORDED_FILE,
                        f"recorded file {path} does not exist",
                        source_name=source.name,
                        key_path=source.setting_path("recorded"),
                        remedy="Point `recorded` at a file that exists.",
                    )
                )
        return problems

    def check_live(
        self, source: ConfiguredSource, credential: CredentialHandle | None
    ) -> LiveCheckResult:
        missing = [path for path in _paths(source) if not path.exists()]
        if missing:
            return LiveCheckResult(False, f"{len(missing)} recorded file(s) missing")
        return LiveCheckResult(True, "all recorded files present")

    def read(
        self,
        source: ConfiguredSource,
        credential: CredentialHandle | None,
        since: datetime | None,
        mode: RunMode,
    ) -> Iterator[NormalizedRecord]:
        for path in _paths(source):
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text:
                    continue
                payload = json.loads(text)
                occurred = datetime.fromisoformat(str(payload["occurred"]))
                if since is not None and occurred < since:
                    continue
                yield NormalizedRecord(
                    source_id=payload.get("source_id"),
                    occurred=occurred,
                    title=str(payload.get("title", "")),
                    payload=payload.get("payload", {}),
                )


KIND = SourceKind(
    name="fixture",
    summary="recorded records read from disk; used to exercise the contract",
    settings=(
        SettingSpec(
            key="recorded",
            type=SettingType.PATH_LIST,
            required=True,
            help="JSON Lines files of recorded normalized records.",
        ),
    ),
    credential_required=False,
    destinations=(),
    reading=ReadingAvailability.AVAILABLE,
    reader=FixtureReader(),
)
