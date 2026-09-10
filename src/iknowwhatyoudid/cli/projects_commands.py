"""The `projects` and `repos` command groups (FR-024 to FR-026, FR-041, FR-045)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import findings as f
from ..config.location import resolve_config_path, resolve_projects_path
from ..errors import UsageError
from ..git import reader as git_reader
from ..projects import attribution, mapping
from ..projects import repository as projects_repo
from ..projects.model import Mapping
from .commands import Result
from .render import finding_payload, table


@dataclass(frozen=True, slots=True)
class MappingSession:
    path: Path
    mapping: Mapping
    findings: tuple[f.Finding, ...]


def open_mapping(config: str | None, projects: str | None) -> MappingSession:
    config_path = resolve_config_path(config)
    path = resolve_projects_path(projects, config_path)
    loaded, problems = mapping.load(path)
    return MappingSession(path, loaded, tuple(problems))


# --- repos ---------------------------------------------------------------------------


def _discovered_repositories(config: str | None) -> tuple[list[Any], list[f.Finding]]:
    """Discover repositories from every configured git source, reading no history."""
    from . import sources_commands

    session = sources_commands.open_config(config)
    repositories: list[Any] = []
    problems: list[f.Finding] = []
    for status in session.report.statuses:
        if status.source.kind != "git.local":
            continue
        found = git_reader.discover_for(status.source)
        repositories.extend(found.repositories)
        problems.extend(found.findings)
    return repositories, problems


def repos_list(
    connection: sqlite3.Connection,
    config: str | None,
    projects: str | None,
    store_path: Path,
) -> Result:
    """Every repository the configuration matches — **reading no history** (FR-003)."""
    facts, problems = _discovered_repositories(config)
    session = open_mapping(config, projects)
    stored = {r.identity: r for r in projects_repo.list_repositories(connection)}

    rows: list[list[str]] = []
    payload: list[dict[str, Any]] = []
    for fact in facts:
        known = stored.get(fact.identity)
        paths = (
            [str(p.path) for p in known.paths] if known else [str(fact.path)]
        )
        if known is not None:
            name, rule = attribution.project_for_repository(session.mapping, known)
        else:
            declared = session.mapping._by_key.get(fact.name.casefold())
            name = declared or fact.name
            rule = (
                attribution.Rule.DECLARED if declared else attribution.Rule.AD_HOC
            )
        label = name if rule is attribution.Rule.DECLARED else f"{name}  (ad hoc)"
        rows.append([fact.name, label, str(len(paths)), ", ".join(paths[:2])])
        payload.append(
            {
                "repository": fact.name,
                "identity": fact.identity,
                "identity_kind": fact.identity_kind.value,
                "project": name,
                "ad_hoc": rule is attribution.Rule.AD_HOC,
                "paths": paths,
                "is_bare": fact.is_bare,
                "is_worktree": fact.is_worktree,
                "has_commits": fact.has_commits,
            }
        )

    body = table(["REPOSITORY", "PROJECT", "PATHS", "WHERE"], rows) or "No repositories."
    mapped = sum(1 for p in payload if not p["ad_hoc"])
    tail = f"{len(payload)} repositories · {mapped} mapped · {len(payload) - mapped} ad hoc"

    return Result(
        "repos.list",
        True,
        store_path,
        {"repositories": payload},
        f"{body}\n\n{tail}",
        findings=[finding_payload(p) for p in problems],
    )


def repos_check(config: str | None, projects: str | None, store_path: Path) -> Result:
    """Discovery diagnostics without ingesting (FR-004, FR-006, FR-007, FR-009)."""
    facts, problems = _discovered_repositories(config)
    session = open_mapping(config, projects)
    problems = list(problems) + list(session.findings)

    lines: list[str] = []
    for finding in f.order(problems):
        label = "ERROR " if finding.blocks else "WARN  "
        where = finding.key_path or finding.source_name or ""
        lines.append(f"{label}{where}  {finding.message}")
        if finding.remedy:
            lines.append(f"       → {finding.remedy}")
    if not problems:
        lines.append(f"{len(facts)} repositories, no problems found.")

    blocking = [p for p in problems if p.blocks]
    lines += ["", f"{len(blocking)} errors, {len(problems) - len(blocking)} warnings"]

    return Result(
        "repos.check",
        not blocking,
        store_path,
        {"repositories": len(facts)},
        "\n".join(lines),
        findings=[finding_payload(p) for p in problems],
    )


# --- projects ------------------------------------------------------------------------


def projects_list(connection: sqlite3.Connection, store_path: Path) -> Result:
    summaries = projects_repo.list_projects(connection)
    rows = [
        [
            s.project.name,
            "ad hoc" if s.project.ad_hoc else "declared",
            str(s.repositories),
            f"{s.activity:,}",
        ]
        for s in summaries
    ]
    body = table(["PROJECT", "SOURCE", "REPOSITORIES", "ACTIVITY"], rows) or "No projects."
    declared = sum(1 for s in summaries if not s.project.ad_hoc)
    tail = (
        f"{len(summaries)} projects · {declared} declared · "
        f"{len(summaries) - declared} ad hoc"
    )
    return Result(
        "projects.list",
        True,
        store_path,
        {
            "projects": [
                {
                    "name": s.project.name,
                    "ad_hoc": s.project.ad_hoc,
                    "repositories": s.repositories,
                    "activity": s.activity,
                }
                for s in summaries
            ]
        },
        f"{body}\n\n{tail}",
    )


def projects_validate(
    connection: sqlite3.Connection,
    config: str | None,
    projects: str | None,
    store_path: Path,
) -> Result:
    session = open_mapping(config, projects)
    stored = projects_repo.list_repositories(connection)
    problems = list(session.findings) + mapping.unmatched(session.mapping, stored)
    problems = f.order(problems)

    lines = [f"Projects: {session.path}", ""]
    if not session.mapping.present:
        lines.append(
            "No mapping file — every repository gets a project of its own. That is "
            "valid; create the file to group them."
        )
    for finding in problems:
        label = "ERROR " if finding.blocks else "WARN  "
        where = finding.key_path or ""
        name = f" {finding.source_name!r}" if finding.source_name else ""
        lines.append(f"{label}{where}{name}  {finding.message}")
        if finding.remedy:
            lines.append(f"       → {finding.remedy}")

    blocking = [p for p in problems if p.blocks]
    lines += [
        "",
        f"{len(blocking)} errors, {len(problems) - len(blocking)} warnings · "
        + ("not ready" if blocking else "ready"),
    ]

    return Result(
        "projects.validate",
        not blocking,
        store_path,
        {"present": session.mapping.present, "projects": list(session.mapping.project_names)},
        "\n".join(lines),
        findings=[finding_payload(p) for p in problems],
    )


def projects_rederive(
    connection: sqlite3.Connection,
    config: str | None,
    projects: str | None,
    store_path: Path,
    *,
    dry_run: bool,
) -> Result:
    session = open_mapping(config, projects)
    if any(p.blocks for p in session.findings):
        raise UsageError(
            f"the mapping in {session.path} has problems",
            remedy="Run `ikwyd projects validate` and fix them first.",
        )

    report = attribution.rederive(connection, session.mapping, dry_run=dry_run)

    lines = [f"Re-deriving {report.total:,} attributions from {session.path}", ""]
    for (source, target), count in sorted(
        report.move_summary.items(), key=lambda item: -item[1]
    ):
        verb = "would move" if dry_run else "moved"
        lines.append(f"  {count:>6,} {verb}   {source}  →  {target}")
    if report.held_by_correction:
        lines.append(
            f"  {report.held_by_correction:>6,} unchanged by the mapping — "
            "a correction takes precedence"
        )
    lines.append(f"  {report.unchanged:>6,} unchanged")
    if report.pruned_ad_hoc:
        verb = "would stop holding" if dry_run else "no longer holds"
        lines += [
            "",
            f"{len(report.pruned_ad_hoc)} ad-hoc project(s) {verb} activity: "
            + ", ".join(report.pruned_ad_hoc),
        ]
    if dry_run:
        lines += ["", "Nothing has been changed (--dry-run)."]

    return Result(
        "projects.rederive",
        True,
        store_path,
        {
            "total": report.total,
            "moved": len(report.moved),
            "unchanged": report.unchanged,
            "held_by_correction": report.held_by_correction,
            "pruned_ad_hoc": list(report.pruned_ad_hoc),
            "moves": [
                {"from": m.from_project, "to": m.to_project, "source_id": m.source_id}
                for m in report.moved
            ],
            "dry_run": dry_run,
        },
        "\n".join(lines),
    )
