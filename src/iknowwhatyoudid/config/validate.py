"""Validation and readiness (FR-014 to FR-019, FR-027, FR-029, FR-039).

Two properties matter more than the individual rules:

* **Every fault is reported in one run** (FR-016, SC-004). Nothing here stops at the
  first problem, and an unknown kind never prevents the remaining sources from being
  validated (FR-029).
* **Nothing is contacted.** Validation is entirely offline; the only command that opens
  a connection is `sources check --live`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..credentials.store import CredentialPresence, CredentialStatus, CredentialStore
from ..kinds import registry
from ..kinds.spec import SettingSpec, SourceKind
from . import findings as f
from . import secret_scan
from .locate import find_key_line
from .model import ConfiguredSource, SourceConfiguration


@dataclass(frozen=True, slots=True)
class SourceStatus:
    source: ConfiguredSource
    kind: SourceKind | None
    readiness: f.Readiness
    credential: CredentialStatus | None
    findings: tuple[f.Finding, ...]

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def destinations(self) -> tuple[str, ...]:
        return self.kind.destinations if self.kind else ()

    @property
    def is_ready(self) -> bool:
        return self.readiness is f.Readiness.READY


@dataclass(frozen=True, slots=True)
class ValidationReport:
    configuration: SourceConfiguration
    statuses: tuple[SourceStatus, ...]
    file_findings: tuple[f.Finding, ...]

    @property
    def findings(self) -> tuple[f.Finding, ...]:
        collected = list(self.file_findings)
        for status in self.statuses:
            collected.extend(status.findings)
        return tuple(f.order(collected))

    @property
    def blocking(self) -> tuple[f.Finding, ...]:
        return tuple(finding for finding in self.findings if finding.blocks)

    @property
    def warnings(self) -> tuple[f.Finding, ...]:
        return tuple(finding for finding in self.findings if not finding.blocks)

    @property
    def ok(self) -> bool:
        return not self.blocking

    def status_for(self, name: str) -> SourceStatus | None:
        for status in self.statuses:
            if status.name == name:
                return status
        return None


def _check_settings(
    source: ConfiguredSource, kind: SourceKind, raw_text: str
) -> list[f.Finding]:
    problems: list[f.Finding] = []
    declared = {spec.key: spec for spec in kind.settings}

    for spec in kind.settings:
        if spec.required and spec.key not in source.settings:
            problems.append(
                f.blocking(
                    f.MISSING_REQUIRED_SETTING,
                    f"required setting `{spec.key}` is missing",
                    source_name=source.name,
                    key_path=source.setting_path(spec.key),
                    line=find_key_line(raw_text, source.index, spec.key),
                    remedy=spec.help or None,
                )
            )

    for key, value in source.settings.items():
        accepted: SettingSpec | None = declared.get(key)
        if accepted is None:
            problems.append(
                f.blocking(
                    f.UNKNOWN_SETTING,
                    f"`{kind.name}` does not accept a setting called `{key}`",
                    source_name=source.name,
                    key_path=source.setting_path(key),
                    line=find_key_line(raw_text, source.index, key),
                    remedy=(
                        "Accepted settings: "
                        + (", ".join(s.key for s in kind.settings) or "none")
                    ),
                )
            )
            continue
        if not accepted.accepts(value):
            problems.append(
                f.blocking(
                    f.SETTING_TYPE_MISMATCH,
                    f"`{key}` must be {accepted.type.value}",
                    source_name=source.name,
                    key_path=source.setting_path(key),
                    line=find_key_line(raw_text, source.index, key),
                    remedy=accepted.help or None,
                )
            )

    for key in secret_scan.scan(source.settings):
        problems.append(
            f.warning(
                f.INLINE_SECRET,
                f"`{key}` looks like a secret",
                source_name=source.name,
                key_path=source.setting_path(key),
                line=find_key_line(raw_text, source.index, key),
                remedy=(
                    "Put it in credentials.toml and reference it here with "
                    'credential = "..."'
                ),
            )
        )

    return problems


def _check_since(source: ConfiguredSource, raw_text: str) -> list[f.Finding]:
    if source.since is None:
        return []
    problems: list[f.Finding] = []
    if source.since.tzinfo is None:
        problems.append(
            f.blocking(
                f.NAIVE_DATETIME,
                "`since` has no time zone",
                source_name=source.name,
                key_path=source.setting_path("since"),
                line=find_key_line(raw_text, source.index, "since"),
                remedy="Write it as e.g. 2026-01-01T00:00:00+01:00.",
            )
        )
    elif source.since > datetime.now(tz=UTC):
        problems.append(
            f.warning(
                f.FUTURE_DATETIME,
                "`since` is in the future, so this source will read nothing",
                source_name=source.name,
                key_path=source.setting_path("since"),
                line=find_key_line(raw_text, source.index, "since"),
            )
        )
    return problems


def _check_credential(
    source: ConfiguredSource, kind: SourceKind, store: CredentialStore | None
) -> tuple[CredentialStatus | None, list[f.Finding]]:
    problems: list[f.Finding] = []

    if source.credential is not None and not kind.credential_required:
        problems.append(
            f.warning(
                f.CREDENTIAL_NOT_REQUIRED,
                f"`{kind.name}` needs no credential, but one is named",
                source_name=source.name,
                key_path=source.setting_path("credential"),
                remedy="Remove the `credential` line.",
            )
        )

    if not kind.credential_required:
        return None, problems

    if not source.enabled:
        # A switched-off source will not be read, so its credential is not yet a
        # problem. Structural faults are still reported — those are wrong whatever the
        # source's state — but a missing credential would block the whole run over a
        # source the user has deliberately parked.
        return None, problems

    if source.credential is None:
        problems.append(
            f.blocking(
                f.CREDENTIAL_MISSING,
                f"`{kind.name}` needs a credential, but none is named",
                source_name=source.name,
                key_path=source.setting_path("credential"),
                remedy='Add credential = "<name>" and store the secret separately.',
            )
        )
        return None, problems

    if store is None:
        return None, problems

    status = store.status(source.credential.name)
    if status.presence is CredentialPresence.ABSENT:
        problems.append(
            f.blocking(
                f.CREDENTIAL_MISSING,
                f"credential {source.credential.name!r} is not present",
                source_name=source.name,
                key_path=source.setting_path("credential"),
                remedy=(
                    f"Add a [credential.{source.credential.name}] entry to "
                    f"{store.path}. The value never goes in the configuration file."
                ),
            )
        )
    elif status.presence is CredentialPresence.UNREADABLE:
        problems.append(
            f.blocking(
                f.CREDENTIAL_UNREADABLE,
                f"the credential store could not be read ({status.detail})",
                source_name=source.name,
                key_path=source.setting_path("credential"),
                remedy="Fix or remove the credentials file.",
            )
        )
    return status, problems


def _readiness(
    source: ConfiguredSource,
    kind: SourceKind | None,
    credential: CredentialStatus | None,
    problems: list[f.Finding],
) -> f.Readiness:
    """Follows the state diagram in data-model.md.

    DISABLED is evaluated *after* validity on purpose: a user re-enabling a source
    should not be ambushed by faults that were there all along.
    """
    if kind is None:
        return f.Readiness.UNKNOWN_KIND
    if any(
        finding.blocks and finding.code != f.CREDENTIAL_MISSING for finding in problems
    ):
        return f.Readiness.INVALID
    if not source.enabled:
        # Before the credential check: a source that is switched off will not be read,
        # so reporting a missing credential for it is noise the user cannot act on.
        return f.Readiness.DISABLED
    if credential is not None and credential.presence is not CredentialPresence.PRESENT:
        return f.Readiness.CREDENTIAL_MISSING
    if any(finding.code == f.CREDENTIAL_MISSING for finding in problems):
        return f.Readiness.CREDENTIAL_MISSING
    if not kind.is_readable:
        return f.Readiness.NOT_READABLE
    return f.Readiness.READY


def validate_source(
    source: ConfiguredSource,
    raw_text: str,
    store: CredentialStore | None,
    inherited: list[f.Finding] | None = None,
) -> SourceStatus:
    problems: list[f.Finding] = list(inherited or [])
    kind = registry.get(source.kind)

    if kind is None:
        problems.append(
            f.blocking(
                f.UNKNOWN_KIND,
                f"unknown kind {source.kind!r}",
                source_name=source.name,
                key_path=source.setting_path("kind"),
                line=find_key_line(raw_text, source.index, "kind"),
                remedy="Available kinds: " + ", ".join(registry.names()),
            )
        )
        return SourceStatus(source, None, f.Readiness.UNKNOWN_KIND, None, tuple(problems))

    problems.extend(_check_settings(source, kind, raw_text))
    problems.extend(_check_since(source, raw_text))
    credential, credential_problems = _check_credential(source, kind, store)
    problems.extend(credential_problems)

    if kind.reader is not None:
        problems.extend(kind.reader.validate(source))

    if not kind.is_readable and source.enabled:
        arrives = f" (arrives with feature {kind.arrives_in})" if kind.arrives_in else ""
        problems.append(
            f.warning(
                f.READING_NOT_IMPLEMENTED,
                f"`{kind.name}` cannot be read yet{arrives}",
                source_name=source.name,
                key_path=source.setting_path("kind"),
                remedy="The configuration is valid; only the reader is missing.",
            )
        )

    readiness = _readiness(source, kind, credential, problems)
    return SourceStatus(source, kind, readiness, credential, tuple(problems))


def validate(
    configuration: SourceConfiguration,
    file_findings: list[f.Finding],
    store: CredentialStore | None = None,
) -> ValidationReport:
    """Validate everything, collecting every fault rather than stopping at the first."""
    per_source: dict[str, list[f.Finding]] = {}
    for finding in file_findings:
        if finding.source_name is not None:
            per_source.setdefault(finding.source_name, []).append(finding)

    statuses = tuple(
        validate_source(
            source,
            configuration.raw_text,
            store,
            per_source.get(source.name),
        )
        for source in configuration.sources
    )
    remaining = tuple(
        finding for finding in file_findings if finding.source_name is None
    )
    return ValidationReport(configuration, statuses, remaining)
