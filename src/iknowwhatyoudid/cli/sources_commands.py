"""The `sources` command group and `ingest` (FR-014 to FR-019, FR-028, FR-042 to FR-045).

Each function returns a payload; printing and exit codes are `main`'s job, which is what
lets the integration tests call these directly and assert on structures.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import findings as f
from ..config import loader
from ..config.location import (
    credentials_path_for,
    resolve_config_path,
    resolve_projects_path,
)
from ..config.validate import SourceStatus, ValidationReport, validate
from ..credentials.store import CredentialPresence, CredentialStore
from ..errors import IkwydError, UsageError
from ..kinds import registry
from ..records.model import RunMode
from ..sources import identity, run
from ..sources.state import InMemorySourceStateStore, SourceStateStore
from .commands import Result
from .render import finding_payload, table


@dataclass(frozen=True, slots=True)
class ConfigSession:
    path: Path
    report: ValidationReport
    credentials: CredentialStore


def open_config(config: str | None) -> ConfigSession:
    path = resolve_config_path(config)
    configuration, problems = loader.load(path)
    credentials = CredentialStore(credentials_path_for(path))

    permission = credentials.permissions()
    if permission.status.name == "OTHERS_CAN_READ" and credentials.path.exists():
        problems.append(
            f.warning(
                f.FILE_PERMISSIONS,
                f"{credentials.path.name} is readable by other accounts "
                f"({permission.detail})",
                key_path=credentials.path.name,
                remedy="Restrict it to your own account.",
            )
        )

    report = validate(configuration, problems, credentials)
    return ConfigSession(path, report, credentials)


def _readiness_text(status: SourceStatus) -> str:
    readiness = status.readiness
    if readiness is f.Readiness.READY:
        return "ready"
    if readiness is f.Readiness.DISABLED:
        return "disabled"
    if readiness is f.Readiness.UNKNOWN_KIND:
        return f"unknown kind {status.source.kind!r}"
    if readiness is f.Readiness.INVALID:
        return "invalid"
    if readiness is f.Readiness.CREDENTIAL_MISSING:
        name = status.source.credential.name if status.source.credential else "?"
        return f"credential missing: {name!r}"
    arrives = status.kind.arrives_in if status.kind else None
    suffix = f" ({arrives} adds it)" if arrives else ""
    return f"not readable{suffix}"


def _source_payload(status: SourceStatus) -> dict[str, Any]:
    credential: dict[str, Any] | None = None
    if status.source.credential is not None:
        presence = (
            status.credential.presence.value
            if status.credential
            else CredentialPresence.ABSENT.value
        )
        credential = {"name": status.source.credential.name, "presence": presence}
    return {
        "name": status.name,
        "kind": status.source.kind,
        "enabled": status.source.enabled,
        "readiness": status.readiness.value,
        "credential": credential,
        "destinations": list(status.destinations),
    }


def _summary(report: ValidationReport) -> dict[str, int]:
    counts = {
        "total": len(report.statuses),
        "ready": 0,
        "disabled": 0,
        "not_readable": 0,
        "credential_missing": 0,
        "invalid": 0,
        "unknown_kind": 0,
    }
    for status in report.statuses:
        counts[status.readiness.value] = counts.get(status.readiness.value, 0) + 1
    return counts


def _orphans(
    report: ValidationReport, store: SourceStateStore | None
) -> list[dict[str, Any]]:
    if store is None:
        return []
    return [
        {"name": orphan.name, "record_count": orphan.record_count}
        for orphan in identity.unconfigured_with_records(
            store, report.configuration.names
        )
    ]


def sources_list(
    session: ConfigSession, store: SourceStateStore | None = None
) -> Result:
    report = session.report
    rows = [
        [
            status.name,
            status.source.kind,
            "yes" if status.source.enabled else "no",
            _readiness_text(status),
        ]
        for status in report.statuses
    ]
    body = table(["NAME", "KIND", "ENABLED", "STATUS"], rows) or "No sources configured."
    counts = _summary(report)
    tail = (
        f"{counts['total']} sources · {counts['ready']} ready · "
        f"{counts['credential_missing']} need a credential · "
        f"{counts['not_readable']} not yet readable · {counts['disabled']} disabled"
    )
    orphans = _orphans(report, store)
    lines = [f"Configuration: {session.path}", "", body, "", tail]
    for orphan in orphans:
        lines.append(
            f"  note: the store still holds {orphan['record_count']:,} records for "
            f"{orphan['name']!r}, which is no longer configured"
        )

    invalid = any(s.readiness is f.Readiness.INVALID for s in report.statuses)
    return Result(
        "sources.list",
        not invalid,
        session.path,
        {
            "sources": [_source_payload(s) for s in report.statuses],
            "summary": counts,
            "unconfigured_with_records": orphans,
        },
        "\n".join(lines),
    )


def sources_validate(
    session: ConfigSession, store: SourceStateStore | None = None
) -> Result:
    report = session.report
    problems = list(report.findings)
    if store is not None:
        problems.extend(identity.detect(store, report.configuration.names))
    problems = f.order(problems)

    lines = [f"Configuration: {session.path}", ""]
    for finding in problems:
        label = "ERROR " if finding.blocks else "WARN  "
        where = finding.key_path or ""
        name = f" {finding.source_name!r}" if finding.source_name else ""
        line = f" (line {finding.line})" if finding.line else ""
        lines.append(f"{label}{where}{name}{line}  {finding.message}")
        if finding.remedy:
            lines.append(f"       → {finding.remedy}")

    blocking = [p for p in problems if p.blocks]
    warnings = [p for p in problems if not p.blocks]
    if not problems:
        lines.append("No problems found.")
    lines += [
        "",
        f"{len(blocking)} errors, {len(warnings)} warnings · "
        + ("not ready" if blocking else "ready"),
    ]

    return Result(
        "sources.validate",
        not blocking,
        session.path,
        {
            "sources": [_source_payload(s) for s in report.statuses],
            "summary": _summary(report),
            "unconfigured_with_records": _orphans(report, store),
        },
        "\n".join(lines),
        findings=[finding_payload(p) for p in problems],
    )


#: FR-010 requires these to be distinguishable, because each needs a different action.
#: Conflating them is the failure this table exists to prevent: "authentication failed"
#: tells the user none of them, and sending someone to re-authorise when an administrator
#: has to act is a loop that cannot terminate.
AUTHORISATION_STATES = (
    "ready",
    "credential absent",
    "credential expired",
    "administrator approval required",
    "unreachable",
    "archive not found",
)


def _authorisation_state(
    session: ConfigSession, status: SourceStatus
) -> tuple[str, str, str] | None:
    """Which of the states this account is in, offline.

    Contacts nothing. A stored token cannot be *validated* without a round trip, so this
    reports whether one exists; `--live` is what asks the provider.
    """
    kind = status.source.kind
    if not kind.startswith("mail."):
        return None

    if kind in {"mail.mbox", "mail.hey"}:
        from ..mail.reader import archive_paths, expand

        missing = [p for p in expand(archive_paths(status.source)) if not p.is_file()]
        if missing:
            return (
                "archive not found",
                f"{missing[0]} does not exist",
                "Export again, or correct `paths`.",
            )
        return ("ready", "the export is readable", "")

    from ..auth import tokens as token_store

    path = token_store.path_for(session.path)
    try:
        stored = token_store.load(path)
    except IkwydError as exc:
        return ("credential absent", exc.message, exc.remedy or "")

    if status.name not in stored:
        return (
            "credential absent",
            f"no authorisation stored in {path.name}",
            f"Run `ikwyd sources authorise {status.name}`.",
        )
    return (
        "ready",
        f"an authorisation is stored in {path.name}",
        "",
    )


def sources_check(session: ConfigSession, *, name: str, live: bool) -> Result:
    status = session.report.status_for(name)
    if status is None:
        raise UsageError(
            f"no source called {name!r} in {session.path}",
            remedy="Run `ikwyd sources list` to see the configured names.",
        )

    lines = [f"{status.name} — {status.source.kind}", f"  {_readiness_text(status)}"]
    payload: dict[str, Any] = {"source": _source_payload(status), "live": None}

    authorisation = _authorisation_state(session, status)
    if authorisation is not None:
        state, explanation, remedy = authorisation
        lines += ["", f"  {state}: {explanation}"]
        if remedy:
            lines.append(f"    → {remedy}")
        payload["authorisation"] = {"state": state, "detail": explanation}

    if live:
        destinations = status.destinations or ("none (local only)",)
        # FR-045: say where we are about to go, before going there.
        lines += ["", "  about to contact: " + ", ".join(destinations)]
        if status.kind is None or status.kind.reader is None:
            lines.append("  cannot check: this kind has no reader yet")
            payload["live"] = {"attempted": False, "reason": "reading not implemented"}
        else:
            outcome = status.kind.reader.check_live(status.source, None)
            lines.append(
                f"  {'reachable' if outcome.reachable else 'NOT reachable'}: "
                f"{outcome.detail}"
            )
            payload["live"] = {
                "attempted": True,
                "reachable": outcome.reachable,
                "detail": outcome.detail,
            }

    ok = status.readiness not in {f.Readiness.INVALID, f.Readiness.UNKNOWN_KIND}
    return Result(
        "sources.check",
        ok,
        session.path,
        payload,
        "\n".join(lines),
        findings=[finding_payload(p) for p in status.findings],
    )


def sources_kinds(session: ConfigSession | None, *, name: str | None) -> Result:
    path = session.path if session else Path("-")
    kinds = registry.all_kinds()
    if name is not None:
        found = registry.get(name)
        if found is None:
            raise UsageError(
                f"no kind called {name!r}",
                remedy="Available kinds: " + ", ".join(registry.names()),
            )
        kinds = (found,)

    lines: list[str] = []
    for kind in kinds:
        lines.append(f"{kind.name} — {kind.summary}")
        reading = (
            "available"
            if kind.is_readable
            else f"not yet implemented"
            + (f" (arrives with feature {kind.arrives_in})" if kind.arrives_in else "")
        )
        lines.append(f"  reading:      {reading}")
        lines.append(
            f"  credential:   {'required' if kind.credential_required else 'not required'}"
        )
        lines.append(
            "  destinations: " + (", ".join(kind.destinations) or "none (local only)")
        )
        if kind.required_access:
            lines.append("  access:       " + "; ".join(kind.required_access))
        if kind.settings:
            lines.append("")
            rows = [
                [
                    spec.key,
                    spec.type.value,
                    "required" if spec.required else "optional",
                    spec.help,
                ]
                for spec in kind.settings
            ]
            lines.append(
                "  " + table(["SETTING", "TYPE", "", "HELP"], rows).replace("\n", "\n  ")
            )
        lines.append("")

    return Result(
        "sources.kinds",
        True,
        path,
        {"kinds": [kind.as_dict() for kind in kinds]},
        "\n".join(lines).rstrip(),
    )


def sources_destinations(session: ConfigSession) -> Result:
    rows = run.destinations(session.report)
    body = table(["SOURCE", "KIND", "DESTINATION"], [list(r) for r in rows])
    return Result(
        "sources.destinations",
        True,
        session.path,
        {
            "destinations": [
                {"source": s, "kind": k, "destination": d} for s, k, d in rows
            ]
        },
        body or "No sources configured.",
    )


def ingest(
    session: ConfigSession,
    store: SourceStateStore | None = None,
    *,
    connection: sqlite3.Connection | None = None,
    projects: str | None = None,
    config: str | None = None,
    only: str | None = None,
    dry_run: bool = False,
    sweep: bool = False,
) -> Result:
    state = store if store is not None else InMemorySourceStateStore()
    mode = RunMode.SWEEP if sweep else RunMode.INCREMENTAL
    report = run.ingest(
        session.report,
        state,
        connection=connection,
        only=only,
        mode=mode,
        dry_run=dry_run,
    )

    # Every recorded activity must land on a project (FR-025). Attribution runs here
    # rather than inside the run so that `sources/` stays source-agnostic and
    # `projects/` keeps its inability to read a repository.
    attributed = 0
    if connection is not None and not dry_run and report.records_ingested:
        from ..projects import attribution, mapping as project_mapping

        mapping_path = resolve_projects_path(projects, session.path)
        loaded, _problems = project_mapping.load(mapping_path)
        attributed = attribution.attribute(connection, loaded).total

    rows = [
        [
            outcome.source_name,
            outcome.kind,
            outcome.result.value,
            (
                f"{outcome.records_ingested} records"
                if outcome.succeeded
                else (outcome.detail or "")
            ),
        ]
        for outcome in report.outcomes
    ]
    body = table(["SOURCE", "KIND", "RESULT", ""], rows) or "No sources configured."

    # A part of a source that could not be read is named, every time. The run still
    # succeeded on everything else, and that is exactly why this must not be quiet.
    notes = [
        f"  {outcome.source_name}: skipped {part}"
        for outcome in report.outcomes
        for part in outcome.skipped_parts
    ]
    if notes:
        heading = "Skipped, and not recorded:"
        body += "\n\n" + heading + "\n" + "\n".join(notes)

    tail = (
        f"{report.succeeded} succeeded, {report.failed} failed, "
        f"{report.skipped} skipped"
    )
    if report.skipped_parts:
        tail += f" · {report.skipped_parts} part(s) skipped"

    return Result(
        "ingest",
        report.ok,
        session.path,
        {
            "outcomes": [
                {
                    "source": o.source_name,
                    "kind": o.kind,
                    "result": o.result.value,
                    "failure": o.failure.value if o.failure else None,
                    "detail": o.detail,
                    "records_ingested": o.records_ingested,
                    "skipped_parts": list(o.skipped_parts),
                }
                for o in report.outcomes
            ],
            "summary": {
                "succeeded": report.succeeded,
                "failed": report.failed,
                "skipped": report.skipped,
            },
            "mode": mode.value,
            "attributed": attributed,
        },
        f"{body}\n\n{tail}",
    )
