"""Validation findings (FR-015 to FR-017).

A finding's ``code`` is the stable contract — tests and ``--json`` consumers key on it,
never on ``message``, so wording stays free to improve.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class Readiness(StrEnum):
    """Why a source can or cannot be read. See data-model.md for the state diagram."""

    READY = "ready"
    DISABLED = "disabled"
    INVALID = "invalid"
    UNKNOWN_KIND = "unknown_kind"
    CREDENTIAL_MISSING = "credential_missing"
    NOT_READABLE = "not_readable"


# Every code this feature can emit. Kept in one place so `--json` consumers have a
# closed set to switch on, and so a typo becomes an import error rather than a
# finding nobody matches.
PARSE_ERROR = "parse-error"
UNKNOWN_TOP_LEVEL_KEY = "unknown-top-level-key"
ATTRIBUTION_NOT_ALLOWED = "attribution-not-allowed"
DUPLICATE_SOURCE_NAME = "duplicate-source-name"
INVALID_SOURCE_NAME = "invalid-source-name"
UNKNOWN_KIND = "unknown-kind"
MISSING_REQUIRED_SETTING = "missing-required-setting"
UNKNOWN_SETTING = "unknown-setting"
SETTING_TYPE_MISMATCH = "setting-type-mismatch"
NAIVE_DATETIME = "naive-datetime"
FUTURE_DATETIME = "future-datetime"
CREDENTIAL_MISSING = "credential-missing"
CREDENTIAL_UNREADABLE = "credential-unreadable"
CREDENTIAL_NOT_REQUIRED = "credential-not-required"
INLINE_SECRET = "inline-secret"
FILE_PERMISSIONS = "file-permissions"
FILE_PERMISSIONS_UNVERIFIED = "file-permissions-unverified"
UNCONFIGURED_SOURCE_HAS_RECORDS = "unconfigured-source-has-records"
SOURCE_RENAMED = "source-renamed"
READING_NOT_IMPLEMENTED = "reading-not-implemented"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: str
    message: str
    source_name: str | None = None
    key_path: str | None = None
    line: int | None = None
    remedy: str | None = None

    @property
    def blocks(self) -> bool:
        return self.severity is Severity.BLOCKING


def blocking(
    code: str,
    message: str,
    *,
    source_name: str | None = None,
    key_path: str | None = None,
    line: int | None = None,
    remedy: str | None = None,
) -> Finding:
    return Finding(
        Severity.BLOCKING, code, message, source_name, key_path, line, remedy
    )


def warning(
    code: str,
    message: str,
    *,
    source_name: str | None = None,
    key_path: str | None = None,
    line: int | None = None,
    remedy: str | None = None,
) -> Finding:
    return Finding(Severity.WARNING, code, message, source_name, key_path, line, remedy)


def order(findings: list[Finding]) -> list[Finding]:
    """File-level first, then per source in file order, blocking before warning.

    Deterministic so that two runs over the same file produce byte-identical output and
    a user can diff them.
    """

    def key(finding: Finding) -> tuple[int, str, int]:
        scope = 0 if finding.source_name is None else 1
        return (scope, finding.source_name or "", 0 if finding.blocks else 1)

    return sorted(findings, key=key)
