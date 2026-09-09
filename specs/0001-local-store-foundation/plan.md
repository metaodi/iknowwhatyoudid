# Implementation Plan: Local Store Foundation

**Branch**: `0001-local-store-foundation` | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/0001-local-store-foundation/spec.md`

## Summary

This feature builds the store every later feature writes to and reads from: a single embedded database in
the tool's own data directory, holding ingested records in one normalized shape, keeping raw records,
derived attributions, and user corrections separately discardable, and surviving interruption, migration,
and a full rebuild without losing the one thing that cannot be regenerated — the user's corrections.

**The engine is SQLite**, which the constitution requires this plan to decide once for the whole project.
It is in the standard library, so the feature ships with zero runtime dependencies; its file format has a
stability guarantee measured in decades, which matters for a store meant to accumulate years of records;
and every durability requirement in the spec maps onto a verified SQLite primitive rather than onto code
we would have to write. DuckDB's analytical advantage is real but arrives later, in the dashboard — and
DuckDB can read SQLite files directly, so choosing SQLite does not foreclose it.

Two design findings shaped the plan beyond the spec's literal text. First, **withdrawal detection
(FR-027) is impossible from a purely incremental read** — a run that only fetches what is new cannot know
that something old has vanished — so ingestion runs are typed as either *incremental* or *sweep*, and
only a sweep may withdraw. Second, **"future-dated" is two different questions**, one about data quality
and one about summary arithmetic; separating them is what lets FR-036, FR-037, and FR-038 all hold at once
without storing a flag that would go stale.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12"`, `.python-version` 3.12). The ambient
interpreter is 3.11.5; `uv` provisions 3.12.11.

**Primary Dependencies**: None at runtime. Standard library only — `sqlite3`, `hashlib`, `json`,
`logging` (with `RotatingFileHandler`), `datetime`, `pathlib`, `argparse`, `ctypes` (Windows ACL read),
`subprocess` (best-effort disk-encryption probe). Development-only: `pytest`, `mypy`.

**Storage**: **SQLite**, single file, in the tool's own data directory. Verified available features on
this machine (SQLite 3.42.0): WAL, `STRICT` tables, generated columns, JSON1, `RETURNING`, upsert,
transactional DDL, the online backup API, and `PRAGMA user_version` participating in transaction
rollback. Minimum required SQLite is **3.37** (for `STRICT`); the tool checks at startup and refuses
clearly below that.

**Testing**: `pytest`, against fixture batches of normalized records standing in for real sources — no
connector exists yet, and the constitution forbids testing against the developer's own accounts. `mypy`
strict over `src/` and `tests/`. Migrations tested against both an empty and a populated store, as the
constitution requires.

**Target Platform**: Cross-platform desktop CLI. Windows 11 primary; macOS and Linux supported. Platform
divergence is confined to the two at-rest protection probes (file permissions, disk encryption).

**Performance Goals**: Store info in under 5 seconds over a year of records (SC-008). A year is estimated
at 10⁵–10⁶ records across all sources — comfortably inside SQLite's range with the right indexes, and two
to three orders of magnitude below where a columnar engine would start to matter.

**Constraints**: No network access from any store operation (FR-023, SC-001). No secret written to the
store (FR-024) or the log (FR-041). No record content in the log (FR-041). Nothing written outside the
tool's own data directory (FR-001). The store is never deleted or overwritten on the tool's own
initiative (FR-026). No passphrase required to open the store (FR-030).

**Scale/Scope**: One person, one machine, one store, one writer at a time. Roughly 1,800–2,200 lines
across storage, records, corrections, protection probes, logging, and CLI.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How this feature satisfies it | Verdict |
|-----------|-------------------------------|---------|
| **I. Local-First and Private by Default** | No store operation opens a socket (FR-023); a test asserts no socket is created during a full ingest-and-query cycle. The log is bounded to identifiers and counts, never record content (FR-041), so the second on-disk copy of a working life that a verbose log would create does not exist. | PASS / PASS |
| **II. Read-Only at the Source** | No source is contacted at all in this feature. Ingestion here consumes normalized records handed in by a caller; the read side of the boundary is `0002`'s `SourceReader`. | N/A — no source contact |
| **III. Spec-Driven Development** | `spec.md` complete, five clarifications resolved, checklist 16/16. This plan precedes any code. | PASS / PASS |
| **IV. Rebuildable Local Store** | This is the principle the feature exists to implement. Raw, derived, and corrections live in three separately discardable table regions (FR-010); re-derivation reads nothing external (FR-015); corrections survive re-derivation, migration, and rebuild (FR-017); every schema change ships a versioned migration (FR-020). | PASS / PASS |
| **V. Transparent, Correctable Attribution** | Derived attributions store their evidence and their producing rule and are distinguishable from user-confirmed ones (FR-019). This feature stores them; later features produce them. Withdrawn and future-dated records are marked rather than hidden, so an inference is never presented as more solid than its evidence. | PASS / PASS |
| **VI. CLI-First with a Local Dashboard** | Every capability — inspect, check, migrate, export, import, query — is a CLI command with a `--json` form, stdout for results, stderr for diagnostics, non-zero exit on failure. No dashboard surface in this feature. See [contracts/cli-commands.md](./contracts/cli-commands.md). | PASS / PASS |

### Technology and Data Constraints

| Constraint | Compliance |
|------------|------------|
| Python ≥ 3.12, `uv` as the single toolchain | Yes |
| Full type annotations, clean `mypy` strict | Yes |
| **Single embedded file-based database, chosen once here** | **SQLite.** Decision and alternatives in [research.md](./research.md) R1. This is the project-wide choice; no later feature may vary it |
| Database file in the tool's own data directory | Yes (FR-001), with a documented user override (FR-004) |
| Common connector interface | Not this feature. `0002` owns it; this feature implements the `SourceStateStore` port `0002` defined |
| Credentials never in the repository, the store, or logs | Yes (FR-024, FR-041). No credential is handled at all here |
| Standard library default; every dependency justified | **Zero runtime dependencies.** Dev-only `pytest` and `mypy`, justified in [research.md](./research.md) R12 |
| Simplest approach first; no abstraction for a single caller | No new ports introduced. The one interface implemented — `SourceStateStore` — was defined by `0002`, so this feature is its second implementation, not a speculative one |

**Gate result: PASS.** No violations, so Complexity Tracking is empty and omitted.

## Project Structure

### Documentation (this feature)

```text
specs/0001-local-store-foundation/
├── plan.md                     # This file
├── research.md                 # Phase 0 — decisions and alternatives
├── data-model.md               # Phase 1 — schema, entities, states
├── quickstart.md               # Phase 1 — validation walkthrough
├── contracts/
│   ├── cli-commands.md         # Store commands, exit codes
│   ├── schema.md               # The v1 schema and its three regions
│   ├── record-shape.md         # What a connector must hand over
│   ├── corrections-file.md     # The portable correction export format
│   └── source-state.md         # Implementing 0002's port
├── checklists/
│   └── requirements.md         # 16/16
└── tasks.md                    # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/iknowwhatyoudid/
├── __init__.py
├── __main__.py
├── errors.py                   # Exception hierarchy → exit codes  ← owned here, used by 0002
├── cli/
│   ├── __init__.py
│   ├── main.py                 # argparse, exit codes, stdout/stderr  ← owned here
│   ├── commands.py             # store info/check/migrate/protection, corrections export/import
│   └── render.py               # human + --json chokepoint  ← owned here
├── store/
│   ├── __init__.py
│   ├── location.py             # data dir, store path, --store override (FR-001–FR-004)
│   ├── connection.py           # open, pragmas, BEGIN IMMEDIATE, busy_timeout (FR-025)
│   ├── schema.py               # v1 DDL, three regions
│   ├── migrate.py              # runner, snapshot, rollback (FR-020–FR-022)
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── m0001_initial.py
│   ├── integrity.py            # quick_check / integrity_check, corruption report (FR-026)
│   └── stats.py                # counts, span, last ingestion, future-dated counts (FR-003, FR-038)
├── records/
│   ├── __init__.py
│   ├── model.py                # ActivityRecord, IngestionRun, RunMode
│   ├── identity.py             # content-derived stable id (FR-009)
│   ├── timestamps.py           # instant + offset + zone; elapsed vs future (FR-007, FR-035–FR-038)
│   └── repository.py           # batch upsert, revisions, withdrawal sweep (FR-011–FR-014, FR-027–FR-029)
├── derived/
│   ├── __init__.py
│   └── repository.py           # attribution storage, region discard (FR-010, FR-019)
├── corrections/
│   ├── __init__.py
│   ├── model.py
│   ├── repository.py           # precedence over inferred, survives rebuild (FR-017)
│   └── portable.py             # JSONL export/import, newest-wins merge (FR-018, FR-032–FR-034)
├── protection/
│   ├── __init__.py
│   ├── permissions.py          # POSIX st_mode / Windows SDDL  ← owned here, reused by 0002
│   └── encryption.py           # best-effort FDE probe, three-valued (FR-031)
├── obs/
│   ├── __init__.py
│   └── logging.py              # rotating, owner-only, identifier-only API (FR-039–FR-043)
└── sources/
    ├── __init__.py
    └── state.py                # implements 0002's SourceStateStore against SQLite

tests/
├── conftest.py
├── unit/                       # identity, timestamps, permissions, migrate, portable
├── integration/                # one per user story, plus offline and durability suites
└── fixtures/
    ├── batches/                # normalized record batches standing in for sources
    └── stores/                 # stores at older schema versions, and a corrupt one
```

**Structure Decision**: Single project, `src/` layout. Packages map onto the spec's requirement groups —
`store/` to FR-001–FR-005 and FR-020–FR-026, `records/` to FR-006–FR-014 and FR-027–FR-038, `corrections/`
to FR-017, FR-018 and FR-032–FR-034, `protection/` to FR-005 and FR-031, `obs/` to FR-039–FR-043 — so a
reviewer can check a requirement group against one package.

`protection/` is deliberately its own package rather than living under `store/`: the same permission check
is needed by `0002` for the configuration and credentials files, and duplicating a security check is how
the two copies drift apart.

### Correction to feature 0002's plan

`0002` was planned before this feature and assumed it would create `errors.py`, `cli/main.py`,
`cli/render.py`, and its own `config/permissions.py`. Since `0001` is built first, **those move here**, and
`0002` extends them instead of creating them. Concretely, `0002`'s task list needs:

- T001–T005 reduced to extending an existing package rather than creating it
- T019, T020 (render chokepoint, CLI skeleton) become extensions of `cli/render.py` and `cli/main.py`
- T058, T059, T060 (permission checks) replaced by a call into `protection/permissions.py`
- `contracts/source-state.md`'s "does not exist yet" caveat and `0002`'s `persistence: in_memory_only`
  notice (T051) removed once this feature lands

This is recorded here rather than silently left for whoever hits the collision.

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1. No new violations. Three things the design tightened:

- **The log cannot carry record content by construction.** Rather than a filter that inspects strings and
  hopes, `obs/logging.py` exposes only functions taking identifiers and counts; record objects have no
  path into the logger. Principle I holds structurally instead of by reviewer vigilance.
- **Migration atomicity needs no bespoke machinery.** Verified that SQLite's DDL is transactional and that
  `PRAGMA user_version` rolls back with the transaction, so "migrate or leave the store exactly as it was"
  (FR-021) is one `BEGIN IMMEDIATE`. The pre-migration file snapshot remains as a belt-and-braces recovery
  path for corruption, not as the primary rollback mechanism.
- **Withdrawal cannot be inferred from an incremental run**, so `RunMode` is part of the record contract
  rather than an implementation detail. Without it, FR-027 would have silently marked every record outside
  an incremental window as withdrawn — turning a safety requirement into a data-destruction bug.

One limitation recorded rather than papered over: on Windows, **disk-encryption status is unreadable
without administrator rights** — verified, all three available probes return access-denied. FR-031 is
therefore usually answered `UNVERIFIED` on Windows for a normal user, with the elevated command the user
can run themselves. Reporting the gap is what the spec asks for; claiming protection we cannot see would
be the failure.
