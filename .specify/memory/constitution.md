<!--
Sync Impact Report
==================
Version change: 1.0.0 -> 2.0.0

MAJOR rationale: three v1.0.0 rules are redefined in ways that invalidate work that
would have been compliant under them.
  1. Principle I forbade any account, API key, or internet connection. Remote sources
     (mail, calendar, SharePoint) require authenticated network reads, so the privacy
     boundary is redrawn around data egress rather than around network access itself.
  2. Principle IV required every capability to be reachable without a GUI and implied
     no GUI at all. A local dashboard is now a first-class, bounded surface.
  3. Principle V mandated a zero-dependency default. Source APIs, an embedded
     database, and a dashboard make that unachievable; it is relaxed into a
     justification requirement under Technology and Data Constraints.

Modified principles:
  - I. Local-First and Private by Default -> I. Local-First and Private by Default
    (redefined: egress-based boundary, network reads from configured sources allowed)
  - II. Non-Destructive Collection -> II. Read-Only at the Source
    (expanded from local files to remote APIs, credential scopes, and locked files)
  - III. Spec-Driven Development -> unchanged
  - IV. CLI Interface -> VI. CLI-First with a Local Dashboard (redefined, renumbered)
  - V. Simplicity and YAGNI -> removed as a principle; relocated into Technology and
    Data Constraints as a dependency-justification rule

Added principles:
  - IV. Rebuildable Local Store
  - V. Transparent, Correctable Attribution

Added sections:
  - Purpose paragraph preceding Core Principles

Removed sections: none

Deferred TODOs: none
-->

# iknowwhatyoudid Constitution

iknowwhatyoudid reconstructs how time was actually spent by reading the traces a working
day leaves behind - mail, calendar, git history, browser history, SharePoint - and turning
them into a reviewable daily record. Its purpose is to make filling in a timesheet at the
end of a day, week, or month a matter of confirming evidence rather than reconstructing
from memory.

## Core Principles

### I. Local-First and Private by Default (NON-NEGOTIABLE)

All ingested data, the database, and all analysis MUST remain on the user's machine. The
only network traffic the tool may generate is to source systems the user has explicitly
configured, and solely to read from them. The tool MUST NOT send activity data, derived
summaries, attributions, or telemetry to any destination that is not one of those
configured sources - this includes analytics, crash reporting, and hosted LLM services.
Data already ingested MUST remain queryable with no network connection. Any feature that
would send data elsewhere MUST be opt-in, off by default, and introduced only via a
constitution amendment.

Rationale: this tool assembles a detailed record of a person's working life across every
system they touch. Connecting to a source the user chose is not the same as leaking to a
third party, and the privacy guarantee that matters is the second one.

### II. Read-Only at the Source (NON-NEGOTIABLE)

Connectors MUST only read. No connector may create, modify, delete, send, move, label,
archive, or mark-as-read anything in a connected system, and none may write to, truncate,
or reorder a local source file. Where a source file may be locked or concurrently written
(for example a browser history database), the connector MUST operate on a copy. Credentials
MUST be provisioned with the narrowest read-only scope the source offers; where a source
grants only broader scopes, the connector's `plan.md` MUST state this explicitly.

Rationale: these are the user's live mail, calendar, and document systems. An observation
tool that can alter what it observes is a liability no amount of usefulness offsets.

### III. Spec-Driven Development (NON-NEGOTIABLE)

Every feature MUST begin as a numbered spec under `specs/` and pass through the
specify -> clarify -> plan -> tasks sequence before implementation starts. Specs describe
what and why; plans describe how. Code that has no corresponding spec MUST NOT be merged.
When the desired behavior and the code disagree, the spec is the source of truth and the
code is the defect.

Rationale: the specs are the durable artifact; they keep intent reviewable and prevent
implementation detail from silently becoming the requirement.

### IV. Rebuildable Local Store

The database is a derived cache; the connected sources are the system of record. Ingested
records MUST be stored in normalized raw form, separately from derived attributions and
summaries, so that analysis can be re-run without re-fetching. Deleting the database and
re-running ingestion MUST reproduce equivalent state, except for data the source no longer
exposes and user corrections; both exceptions MUST be documented per connector, and user
corrections MUST be preserved across a rebuild. Every schema change MUST ship with a
versioned migration.

Rationale: heuristics for attributing activity to projects will change often. That must
cost a re-analysis, not a re-download of a year of mail.

### V. Transparent, Correctable Attribution

Any mapping of an activity to a project MUST record both the evidence it rests on and the
rule that produced it. Inferred attributions MUST be distinguishable from user-confirmed
ones in storage and in every display. The user MUST be able to correct any attribution, and
a correction MUST survive re-ingestion and re-analysis. The tool MUST NOT present an
inference as an established fact.

Rationale: the output feeds timesheets, which are billing and contractual records. A
confident wrong guess is worse than an acknowledged gap, because only the gap gets checked.

### VI. CLI-First with a Local Dashboard

Every capability - configuring a source, ingesting, querying, correcting an attribution,
exporting - MUST be usable from the command line. The CLI is the complete interface; no
feature may exist only in the dashboard. Commands MUST read arguments and stdin, write
results to stdout and diagnostics to stderr, offer `--json` wherever they emit data, and
exit non-zero on failure. The dashboard MUST bind to a loopback address only, MUST NOT
depend on any remote service to render, and MUST NOT write to any connected source; it may
write user corrections to the local database.

Rationale: a complete CLI keeps the tool scriptable and testable without a browser harness,
and keeps the dashboard as a view over the data rather than a place where state hides.

## Technology and Data Constraints

- Language: Python, minimum version 3.12, as declared in `pyproject.toml`.
- Environment and packaging: `uv` is the single supported toolchain for dependency
  resolution, virtual environments, and running the project.
- Typing: all modules MUST carry type annotations and MUST pass `mypy` cleanly.
- Storage: a single embedded, file-based database - SQLite or DuckDB. The choice MUST be
  made once, in the first storage feature's `plan.md`, and MUST NOT vary per connector.
  The database file MUST live in the tool's own data directory.
- Connectors: each source MUST be implemented behind a common connector interface covering
  configuration, authentication, incremental read, and normalization. Each connector's
  `plan.md` MUST document the exact endpoints or paths it reads, the fields it extracts,
  the credential scopes it needs, and how long it retains raw data.
- Intended sources: e-mail, calendar, git history, browser history, SharePoint. Adding a
  source is a new spec, never ad-hoc code.
- Credentials: MUST NOT be committed to the repository. They MUST be stored in the OS
  keyring or a local configuration file outside version control with user-only permissions,
  and MUST NOT be logged, printed, or written into the database. Committed configuration
  templates MUST contain placeholders only.
- Dependencies: the standard library is the default. Each third-party dependency MUST be
  justified in the feature's `plan.md` under Alternatives Considered. Implementations MUST
  start with the simplest approach that satisfies the spec; abstractions and configuration
  surfaces MUST NOT be introduced for a single anticipated caller.

## Development Workflow and Quality Gates

- Feature folders under `specs/` are zero-padded and sequential (`0001`, `0002`), followed
  by a descriptive slug.
- Before implementation, the feature MUST have `spec.md`, `plan.md`, and `tasks.md`.
  `checklist.md` is optional and used for acceptance criteria.
- Automated tests MUST accompany every behavioral change. Connector and attribution logic
  MUST be tested against recorded fixture data, never against the developer's own live mail,
  calendar, or browser profile.
- Schema migrations MUST be tested against both an empty and a populated database.
- The following MUST pass before a change is merged: the test suite, `mypy`, and a review
  confirming compliance with these principles.
- A pull request MUST explicitly call out any of the following: a new network destination,
  a new credential or a widened scope, a new runtime dependency, a schema migration, or a
  write outside the tool's own data directory.

## Governance

This constitution supersedes all other development practices in this repository. Where a
plan, task list, or habit conflicts with it, this document wins.

Amendments MUST be made by editing this file in a dedicated change that states the
motivation, the version bump, and the migration impact on existing specs and code.
Amendments to principles marked NON-NEGOTIABLE additionally require that the affected specs
be re-reviewed for compliance before the amendment is merged.

Versioning follows semantic versioning:

- MAJOR: a principle is removed, or redefined in a way that invalidates existing compliant
  work.
- MINOR: a principle or section is added, or existing guidance is materially expanded.
- PATCH: clarification, wording, or typo fixes that do not change obligations.

Compliance is reviewed at two points: during `/speckit-plan`, where the plan MUST state how
the feature satisfies each principle it touches, and at review time, where the reviewer MUST
verify the quality gates above. Complexity that cannot be justified against the dependency
and simplicity rules above MUST be removed. Runtime development guidance lives in
`specs/README.md` and the Spec Kit commands under `.claude/skills/`.

**Version**: 2.0.0 | **Ratified**: 2026-09-01 | **Last Amended**: 2026-09-01
