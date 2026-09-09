# Implementation Plan: Configurable Sources

**Branch**: `0002-configurable-sources` | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/0002-configurable-sources/spec.md`

## Summary

This feature delivers the configuration contract that every source connector will be built against: one
hand-edited file declaring named sources, a per-kind declaration of the settings each kind accepts,
offline validation that reports every fault at once, credential resolution by reference without ever
touching a secret value, and a multi-source run that survives one source failing. It ships no real
connector — the git, mail, and calendar kinds appear as *declarations only*, and the contract is proven
end to end against a fixture kind that reads recorded data.

The technical approach is stdlib-only. The configuration file is TOML read through `tomllib`, which is in
the standard library, is read-only by construction (matching FR-002's "never rewrite the user's file"),
and reports parse failures with a line and column. Source kinds declare their settings as explicit
`SettingSpec` values rather than through a validation library, because FR-028 and FR-032 both require
those declarations to be *enumerable and printable*, not merely enforceable. The store from
`0001-local-store-foundation` is reached through a narrow four-operation `SourceStateStore` port, which
`0001` now implements against SQLite. This feature makes no storage decision of its own.

## Technical Context

**Language/Version**: Python 3.12 (per `pyproject.toml` `requires-python = ">=3.12"` and `.python-version`).
Note: the ambient interpreter on the development machine is 3.11.5; `uv` provisions 3.12.

**Primary Dependencies**: None at runtime. Standard library only — `tomllib`, `argparse`, `dataclasses`,
`pathlib`, `datetime`, `json`, `re`, `glob`, `ctypes` (Windows ACL read), `logging`.
Development-only: `pytest`, `mypy`.

**Storage**: SQLite, decided in `0001-local-store-foundation`'s plan per the constitution. This feature
opens no database directly; it reads and writes source state (resumption points, ingestion history,
records-of-unconfigured-sources) exclusively through the `SourceStateStore` port defined in
[contracts/source-state.md](./contracts/source-state.md).

**Testing**: `pytest`, against recorded fixtures only. No test touches a real git repository, mail
account, or calendar (SC-012). `mypy` in strict mode over `src/` and `tests/`.

**Target Platform**: Cross-platform desktop CLI. Windows 11 is the primary development and use target;
macOS and Linux are supported. Platform divergence is confined to the file-permission check (FR-006),
which needs entirely different mechanisms on POSIX and Windows.

**Project Type**: Single-project CLI application with a library core.

**Performance Goals**: Validating a 20-source configuration completes in under 5 seconds and opens zero
network connections (SC-002). In practice this is dominated by filesystem checks on git path patterns;
the budget is generous by roughly two orders of magnitude.

**Constraints**: Zero network traffic during validation (FR-014, SC-002). No credential value in output,
logs, or storage (FR-022, SC-007). No source kind loaded from outside the project's own distribution
(FR-031). No write to the user's configuration file, ever (FR-002). Every data-emitting command offers
`--json` and exits non-zero on failure (FR-019, constitution VI).

**Scale/Scope**: One person, one machine, one configuration file. Expected 3–20 configured sources;
the design should not degrade at 100. Six CLI commands, five source kinds declared (three real
declarations, one fixture, and the registry itself), roughly 1,200–1,600 lines of implementation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How this feature satisfies it | Verdict |
|-----------|-------------------------------|---------|
| **I. Local-First and Private by Default** | Validation is entirely offline (FR-014). The only command that opens a connection is `sources check --live`, and only to a destination the user configured. `sources destinations` lists every destination *before* anything is contacted (FR-045, SC-010). No telemetry, no analytics, no hosted service. | PASS (initial) / PASS (post-design) |
| **II. Read-Only at the Source** | This feature contacts a source only to answer "can I reach and authenticate to this?" The `SourceKind` contract exposes no write operation at all — there is nothing in the boundary a connector could use to mutate a source. Credential scope requirements are declared per kind (FR-025) and surfaced before the user grants anything. | PASS / PASS |
| **III. Spec-Driven Development** | `spec.md` complete, all clarifications resolved, `checklists/requirements.md` fully passing. This plan precedes any code. The three connectors are deferred to their own specs (FR-033), which is this principle applied rather than an exception to it. | PASS / PASS |
| **IV. Rebuildable Local Store** | This feature stores nothing derived. It reads and writes only source-scoped state through the port. Disabling and re-enabling a source preserves its resumption point (FR-010); removing a source never deletes its records (FR-012). No schema is defined here, so no migration is owed. | PASS / PASS |
| **V. Transparent, Correctable Attribution** | Not touched. This feature explicitly refuses to carry project attribution (FR-041) and rejects a configuration attempting to declare it. | N/A — deliberately out of scope |
| **VI. CLI-First with a Local Dashboard** | Every capability is a CLI command; there is no dashboard surface in this feature. All six commands read arguments, write results to stdout and diagnostics to stderr, offer `--json`, and exit non-zero on failure. See [contracts/cli-commands.md](./contracts/cli-commands.md). | PASS / PASS |

### Technology and Data Constraints

| Constraint | Compliance |
|------------|------------|
| Python ≥ 3.12 | Yes — `tomllib` (3.11+) and modern generics are the only version-sensitive uses. |
| `uv` as the single toolchain | Yes. `uv run`, `uv sync`; `pyproject.toml` gains a `[build-system]` and a console script entry point. |
| Full type annotations, clean `mypy` | Yes, strict mode. The `SettingSpec`/`SourceKind` design is deliberately explicit rather than dynamic so that it types cleanly without plugins. |
| Single embedded file-based database, chosen once in the first storage feature's plan | **SQLite**, chosen in `0001`'s plan. This feature does not open a database directly. |
| Common connector interface covering configuration, authentication, incremental read, normalization | This feature *defines* that interface — [contracts/source-kind.md](./contracts/source-kind.md) — and implements only the configuration and authentication-presence halves. Incremental read and normalization are declared and left unimplemented, surfaced honestly as `reading: unavailable`. |
| Credentials never committed, never logged, never in the database; templates hold placeholders only | Yes — FR-020 to FR-024. The shipped example configuration contains placeholders only. Redaction is applied at the output boundary, not per call site. |
| Standard library is the default; every third-party dependency justified | **No runtime dependency added by this feature.** The project carries one, `tzdata` on Windows, justified in [0001 research.md](../0001-local-store-foundation/research.md) R13. Dev-only `pytest` and `mypy`. |
| Simplest approach first; no abstraction for a single anticipated caller | The `SourceStateStore` port now has two implementations — SQLite in `0001`, in-memory in tests — so the abstraction is discharged rather than merely tolerated. |

**Gate result: PASS.** One justified deviation, recorded below. No unjustified violations.

## Project Structure

### Documentation (this feature)

```text
specs/0002-configurable-sources/
├── plan.md                     # This file
├── research.md                 # Phase 0 — decisions and alternatives
├── data-model.md               # Phase 1 — entities, fields, validation rules, states
├── quickstart.md               # Phase 1 — runnable validation walkthrough
├── contracts/
│   ├── cli-commands.md         # The six commands, arguments, exit codes
│   ├── config-file.md          # The configuration file format and its grammar
│   ├── source-kind.md          # The extension boundary (FR-026 to FR-032)
│   ├── source-state.md         # The port into 0001's store
│   └── json-output.md          # --json envelope and per-command payloads
├── checklists/
│   └── requirements.md         # Spec quality checklist (complete)
└── tasks.md                    # Created by /speckit-tasks, not by this command
```

### Source Code (repository root)

```text
src/iknowwhatyoudid/
├── __init__.py
├── __main__.py                 # python -m iknowwhatyoudid
├── errors.py                   # Exception hierarchy; maps to exit codes
├── cli/
│   ├── __init__.py
│   ├── main.py                 # argparse wiring, exit-code mapping, stdout/stderr split
│   ├── commands.py             # One function per command; returns a payload, prints nothing
│   └── render.py               # Human and --json rendering; the single redaction chokepoint
├── config/
│   ├── __init__.py
│   ├── location.py             # Default path resolution, --config override (FR-002, FR-003)
│   ├── loader.py               # tomllib parse; TOMLDecodeError -> located finding (FR-004)
│   ├── model.py                # SourceConfiguration, ConfiguredSource (frozen dataclasses)
│   ├── validate.py             # Structural + per-kind validation; collects all findings (FR-016)
│   ├── findings.py             # Finding, Severity, KeyPath; ordering and grouping
│   ├── locate.py               # Best-effort key-path -> line number over the raw text
│   ├── secret_scan.py          # Inline-secret heuristic (FR-023)
│   └── (permissions live in ../protection/permissions.py, owned by 0001)
├── kinds/
│   ├── __init__.py
│   ├── spec.py                 # SettingSpec, SettingType, SourceKind — the public boundary
│   ├── registry.py             # In-project registry only; refuses external kinds (FR-031)
│   ├── fixture.py              # Fixture kind reading recorded data (FR-034)
│   ├── git_local.py            # Declaration only; reading deferred to 0003
│   ├── mail.py                 # Declarations for outlook/gmail/hey; reading deferred to 0004
│   └── calendar.py             # Declarations for outlook/google; reading deferred to 0005
├── credentials/
│   ├── __init__.py
│   ├── reference.py            # CredentialReference — a name, never a value
│   ├── store.py                # Presence-only resolution from a user-only-readable file
│   └── redaction.py            # Registered secret values; redaction applied at output
└── sources/
    ├── __init__.py
    ├── state.py                # SourceStateStore protocol + InMemorySourceStateStore
    ├── identity.py             # Rename/removal detection (FR-012, FR-013)
    └── run.py                  # Multi-source orchestration, per-source outcomes (FR-042 to FR-044)

tests/
├── conftest.py
├── unit/                       # Per-module: loader, validate, permissions, secret_scan, registry
├── integration/                # Per user story: US1 declare, US2 lifecycle, US3 secrets, US4 new kind
└── fixtures/
    ├── configs/                # Valid, malformed, duplicate-name, unknown-kind, inline-secret
    └── recorded/               # Recorded data the fixture source kind reads
```

**Structure Decision**: Single project, `src/` layout, library core with a thin CLI shell. The five
packages under `src/iknowwhatyoudid/` map one-to-one onto the spec's requirement groups — `config/` to
FR-001 to FR-019, `credentials/` to FR-020 to FR-024, `kinds/` to FR-026 to FR-039, `sources/` to FR-008
to FR-013 and FR-042 to FR-045 — so a reviewer can check a requirement group against a single package.
The `cli/` layer contains no logic beyond argument parsing and rendering, which is what keeps the
constitution's "the CLI is the complete interface" honest: every command is a thin call onto a library
function that is directly testable without a subprocess.

`pyproject.toml` needs three additions this feature must make: a `[build-system]` (hatchling), a
`[project.scripts]` console entry point, and a `[dependency-groups] dev` holding `pytest` and `mypy`.
The runtime `dependencies` list stays empty.

## Complexity Tracking

No outstanding violations.

The `SourceStateStore` port was introduced here when `0001-local-store-foundation` had a spec but no
plan, and was recorded as an abstraction with a single caller. `0001` has since implemented it against
SQLite, so the port has two implementations and the justification is discharged. It stays deliberately
narrow — four operations, no query language, no transaction surface — so it cannot become a
general-purpose data-access layer. See [contracts/source-state.md](./contracts/source-state.md).

## Ownership correction after 0001 was built

`0002` was planned before `0001-local-store-foundation`. It assumed it would create four things that
`0001` has since built and now owns. **`0002` extends these; it does not create them.**

| Module | Owner | What `0002` does |
|--------|-------|------------------|
| `errors.py` | `0001` | Add config-specific exception types |
| `cli/main.py` | `0001` | Register the `sources` command group |
| `cli/render.py` | `0001` | Add the `sources.*` payload shapes |
| `protection/permissions.py` | `0001` | Call it for the configuration and credentials files |
| `sources/state.py` | `0001` | Use `SqliteSourceStateStore`; the in-memory one becomes a test double |

The affected tasks are listed in `tasks.md` under "Ownership correction". The redaction chokepoint
described in research D7 still belongs to `0002` — `0001` has no credentials to redact — and attaches to
the existing `cli/render.py` rather than creating it.

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1. No new violations. Two things the design tightened rather than loosened:

- **Redaction moved to a single chokepoint.** The initial sketch had each command redact its own output,
  which makes FR-022 a property that every future command must remember to uphold. `cli/render.py` is now
  the only place a payload becomes text, so redaction is structural rather than a convention. This
  strengthens Principle I.
- **The `SourceKind` boundary carries no write operation of any kind.** Not "must not write" as a rule a
  connector could break, but no method through which a connector could express a write. Principle II
  becomes unbreakable at the type level rather than enforced by review.

One honest limitation recorded rather than papered over: on Windows the permission check (FR-006) reads
the file's DACL as SDDL through `ctypes`, and where that call fails the tool emits a *"could not verify
permissions"* warning rather than reporting the file as safe. Per the spec's stated bias, a gap is
reported rather than assumed away.
