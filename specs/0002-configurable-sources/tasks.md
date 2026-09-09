---
description: "Task list for 0002-configurable-sources"
---

# Tasks: Configurable Sources

**Input**: Design documents from `/specs/0002-configurable-sources/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **Included and mandatory.** Not an optional choice here — the constitution requires that
"automated tests MUST accompany every behavioral change" and that connector logic be tested "against
recorded fixture data, never against the developer's own live mail, calendar, or browser profile".

**Organization**: Grouped by user story so each can be implemented, tested, and demonstrated
independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1–US4)

## Path Conventions

Single project, `src/` layout, per [plan.md](./plan.md): `src/iknowwhatyoudid/`, `tests/` at repository
root.

**Run everything through `uv run`** — the ambient interpreter on this machine is 3.11.5 and the project
requires 3.12.

---

## Built on 0001

`0001-local-store-foundation` shipped first and owns `errors.py`, `cli/main.py`, `cli/render.py`,
`protection/permissions.py`, and `sources/state.py`. This feature **extends** them. The task lines below
already say so — there is no separate correction to apply.

`0001` also added `RunMode` to the record contract; see T078–T079.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make the project installable, typed, and testable. Nothing here is feature behaviour.

- [ ] T001 Verify `pyproject.toml` already carries the build system, the `ikwyd` entry point and the dev group (all added by `0001`); add nothing unless something is missing
- [ ] T002 Add the subpackages this feature owns — `config/`, `kinds/`, `credentials/` — under the existing `src/iknowwhatyoudid/`. The package, `__main__.py`, `py.typed`, `cli/` and `sources/` already exist
- [ ] T003 [P] Configure `mypy` strict mode over `src` and `tests` in `pyproject.toml`
- [ ] T004 [P] Configure `pytest` in `pyproject.toml` and create `tests/conftest.py`, `tests/unit/`, `tests/integration/`, `tests/fixtures/`
- [ ] T005 [P] Extend `src/iknowwhatyoudid/errors.py` with configuration-specific exceptions (unparseable config, unknown kind, credential unreadable), reusing the existing `IkwydError` base and its 0/1/2 exit-code mapping
- [ ] T006 Verify the skeleton is green against `pyproject.toml` and `src/iknowwhatyoudid/`: `uv sync`, `uv run mypy src tests`, `uv run pytest`, and `uv run ikwyd --help` all succeed

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The configuration reading, kind declaration, and output machinery every user story sits on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T007 [P] Define `Finding`, `Severity`, `Readiness`, and deterministic finding ordering in `src/iknowwhatyoudid/config/findings.py` per [data-model.md](./data-model.md)
- [ ] T008 [P] Define `SettingSpec`, `SettingType`, `ReadingAvailability`, `SourceKind`, the `SourceReader` protocol, and the opaque `CredentialHandle` in `src/iknowwhatyoudid/kinds/spec.py` per [contracts/source-kind.md](./contracts/source-kind.md) — the protocol MUST expose no write operation
- [ ] T009 [P] Define `SourceConfiguration`, `ConfiguredSource`, `CredentialReference` (name-only, no value field), and `PermissionStatus` as frozen dataclasses in `src/iknowwhatyoudid/config/model.py`
- [ ] T010 Implement default configuration-path resolution per platform and the `--config` override in `src/iknowwhatyoudid/config/location.py` per [research.md](./research.md) D10
- [ ] T011 Implement TOML loading with `tomllib` in `src/iknowwhatyoudid/config/loader.py`, mapping `TOMLDecodeError` to a `parse-error` finding carrying line and column (FR-004)
- [ ] T012 Implement the best-effort key-path→line locator over raw file text in `src/iknowwhatyoudid/config/locate.py` per [research.md](./research.md) D2 — returns `None` rather than guessing
- [ ] T013 [P] Write loader unit tests in `tests/unit/test_loader.py` covering valid, empty, absent, and syntactically broken files
- [ ] T014 [P] Write path-resolution unit tests in `tests/unit/test_location.py` covering the Windows, macOS, and Linux branches and the `XDG_CONFIG_HOME`-unset fallback
- [ ] T015 Implement the explicit in-project kind registry in `src/iknowwhatyoudid/kinds/registry.py` — an explicit mapping with no filesystem scan, entry-point lookup, or dynamic import (FR-031)
- [ ] T016 Implement the `fixture` source kind and its working reader over recorded data in `src/iknowwhatyoudid/kinds/fixture.py` (FR-034)
- [ ] T017 [P] Create fixture data under `tests/fixtures/recorded/` and the configuration fixtures `valid.toml`, `broken.toml`, `empty.toml` under `tests/fixtures/configs/`
- [ ] T018 [P] Implement the redaction registry and `redact()` in `src/iknowwhatyoudid/credentials/redaction.py` (values registered later by US3)
- [ ] T019 Extend the existing `src/iknowwhatyoudid/cli/render.py` with the `sources.*` payload shapes per [contracts/json-output.md](./contracts/json-output.md), and route every rendered payload through `redact()` — the envelope and `table()` helper already exist
- [ ] T020 Register the `sources` command group in the existing `src/iknowwhatyoudid/cli/main.py`. Global options, exit codes and the stdout/stderr split already exist — attach `--store`/`--json`/`--verbose` to each new leaf with `argparse.SUPPRESS` defaults, or they will silently overwrite the top-level values
- [ ] T021 [P] Write render unit tests in `tests/unit/test_render.py` asserting envelope shape, deterministic ordering, and that redaction is applied to the `--json` path as well as the human one
- [ ] T022 [P] Write CLI contract tests in `tests/integration/test_cli_contract.py` asserting exit codes 0/1/2, that stdout under `--json` parses standalone, and that diagnostics never reach stdout
- [ ] T078 Add `RunMode` to `SourceReader.read()` in `src/iknowwhatyoudid/kinds/spec.py` and to [contracts/source-kind.md](./contracts/source-kind.md), so a connector states whether its read was exhaustive. `0001` requires this: withdrawal detection is impossible from a purely incremental read ([0001 research.md](../0001-local-store-foundation/research.md) R6). Default `INCREMENTAL`

**Checkpoint**: A configuration file can be found, parsed, and rendered. No validation yet.

---

## Phase 3: User Story 1 — Declare where my traces live (Priority: P1) 🎯 MVP

**Goal**: A user writes one file naming their sources and is told, per source, whether the tool
understood — with every fault reported at once and nothing contacted.

**Independent Test**: Write a configuration naming several sources of different kinds, run validation,
confirm each is listed with a correct ready/not-ready verdict; then introduce one fault at a time (missing
path, duplicate name, unknown kind) and confirm each is reported by name with its location.

### Tests for User Story 1

> Write these first; confirm they fail before implementing.

- [ ] T023 [P] [US1] Write US1 acceptance-scenario tests in `tests/integration/test_us1_declare.py` covering all five scenarios, including that an absent file reports its expected path and creates nothing
- [ ] T024 [P] [US1] Write the offline guarantee test in `tests/integration/test_offline.py` asserting **no socket is created** during validation — assert on socket creation, not on output
- [ ] T025 [P] [US1] Write validation-rule unit tests in `tests/unit/test_validate.py`, asserting on finding `code` values only, never on message text
- [ ] T026 [P] [US1] Add fault fixtures `many-faults.toml`, `duplicate-names.toml`, `unknown-kind.toml`, `with-attribution.toml` to `tests/fixtures/configs/`

### Implementation for User Story 1

- [ ] T027 [P] [US1] Declare the `git.local` kind (settings `paths`, `identities`; no credential; no destinations; `reading = NOT_YET_IMPLEMENTED`) in `src/iknowwhatyoudid/kinds/git_local.py` (FR-035)
- [ ] T028 [P] [US1] Declare the `mail.outlook`, `mail.gmail`, and `mail.hey` kinds with their settings, required access, and destinations in `src/iknowwhatyoudid/kinds/mail.py` (FR-036)
- [ ] T029 [P] [US1] Declare the `calendar.outlook` and `calendar.google` kinds in `src/iknowwhatyoudid/kinds/calendar.py` (FR-037)
- [ ] T030 [US1] Register all seven kinds in `src/iknowwhatyoudid/kinds/registry.py`
- [ ] T031 [US1] Implement file-level validation in `src/iknowwhatyoudid/config/validate.py` — unknown top-level keys blocking, and a `projects`/`attribution`/`mapping` table rejected with `attribution-not-allowed` (FR-041)
- [ ] T032 [US1] Implement per-source validation in `src/iknowwhatyoudid/config/validate.py` — name shape and uniqueness, kind resolution, `since` timezone-awareness, and settings checked against the kind's `SettingSpec` sequence (FR-007, FR-027, FR-038)
- [ ] T033 [US1] Ensure `src/iknowwhatyoudid/config/validate.py` collects **every** finding in one pass and never stops at the first (FR-016, SC-004), and that an unknown kind does not prevent other sources from validating (FR-029)
- [ ] T034 [US1] Implement `Readiness` computation producing `SourceStatus` in `src/iknowwhatyoudid/config/validate.py`, following the state diagram in [data-model.md](./data-model.md) — `DISABLED` evaluated after validity
- [ ] T035 [US1] Implement the `sources list` command in `src/iknowwhatyoudid/cli/commands.py` (FR-015)
- [ ] T036 [US1] Implement the `sources validate` command in `src/iknowwhatyoudid/cli/commands.py`, separating blocking findings from warnings in output (FR-014, FR-017)
- [ ] T037 [US1] Implement the `sources check NAME` command in `src/iknowwhatyoudid/cli/commands.py`, with `--live` printing the destination before contacting it (FR-018)
- [ ] T038 [US1] Implement the `sources destinations` command in `src/iknowwhatyoudid/cli/commands.py` (FR-045, SC-010)
- [ ] T039 [US1] Wire the `sources.list`, `sources.validate`, and `sources.destinations` `--json` payloads in `src/iknowwhatyoudid/cli/render.py` per [contracts/json-output.md](./contracts/json-output.md)

**Checkpoint**: US1 is fully functional. A user can declare sources and be told what was understood. This
is the MVP.

---

## Phase 4: User Story 2 — Add, disable, and retire a source without disturbing the rest (Priority: P1)

**Goal**: Each configuration change affects only the source it names; disabling stops reading without
deleting; re-enabling resumes rather than restarting.

**Independent Test**: From a configuration with several sources and a populated in-memory store, add one
source, disable another, rename a third, remove a fourth; confirm untouched sources' record counts and
resumption points are unchanged and each change produced exactly its intended effect.

### Tests for User Story 2

- [ ] T040 [P] [US2] Write the lifecycle test in `tests/integration/test_us2_lifecycle.py` implementing quickstart Scenario 5 — snapshot state, mutate one source at a time, assert every other source is byte-identical (SC-005, SC-006)
- [ ] T041 [P] [US2] Write rename and removal detection unit tests in `tests/unit/test_identity.py` (FR-012, FR-013)
- [ ] T042 [P] [US2] Write the partial-failure test in `tests/integration/test_run_failures.py` — one source fails, the rest complete, exit code is 1, every source appears in the report (SC-009)
- [ ] T043 [P] [US2] Add `one-failing.toml` and `renamed-source.toml` fixtures to `tests/fixtures/configs/`

### Implementation for User Story 2

- [ ] T044 [US2] Use the existing `SqliteSourceStateStore` from `src/iknowwhatyoudid/sources/state.py` as the default backing, and keep `InMemorySourceStateStore` as a test double only. Do not add operations to the port — it stays at four
- [ ] T045 [US2] Implement rename and removal detection in `src/iknowwhatyoudid/sources/identity.py` — a configured name absent from the store warns `source-renamed`; a stored name absent from the configuration reports `unconfigured-source-has-records` and never deletes (FR-012, FR-013)
- [ ] T046 [US2] Implement enable/disable handling in `src/iknowwhatyoudid/sources/run.py` and `src/iknowwhatyoudid/config/validate.py` — disabled sources skipped by ingestion, their records still queryable, their resumption point preserved (FR-009, FR-010)
- [ ] T047 [US2] Implement multi-source orchestration in `src/iknowwhatyoudid/sources/run.py` — one outcome per configured source including skipped ones, one source's failure never aborting the others (FR-043)
- [ ] T048 [US2] Implement resumption-point read and advance in `src/iknowwhatyoudid/sources/run.py`, advancing only on a completed run (FR-010)
- [ ] T049 [US2] Implement the `ingest` command with `--source NAME` and `--dry-run` in `src/iknowwhatyoudid/cli/commands.py`, exiting non-zero when any source failed (FR-042, FR-044)
- [ ] T050 [US2] Report `unconfigured_with_records` in the `sources list` and `sources validate` payloads in `src/iknowwhatyoudid/cli/render.py` (FR-012)
- [ ] T051 [US2] Write a durability test in `tests/integration/test_us2_lifecycle.py` asserting a resumption point survives closing and reopening the store — the property that replaced the `persistence: in_memory_only` notice once `0001` landed (FR-010)
- [ ] T079 [US2] Pass each source's `RunMode` and, for a sweep, its covered window and seen source ids through `src/iknowwhatyoudid/sources/run.py` into the store's `Batch`. Assert in `tests/integration/test_run_failures.py` that an `INCREMENTAL` run withdraws nothing

**Checkpoint**: US1 and US2 both work independently. The configuration file is safe to edit.

---

## Phase 5: User Story 3 — Secrets are named, never pasted (Priority: P1)

**Goal**: The configuration file is safe to read over someone's shoulder. Missing credentials are named;
credential values never appear anywhere.

**Independent Test**: Configure sources needing credentials, confirm validation names exactly which are
missing; supply them; confirm the sources become ready; then search the configuration file, all output,
all logs, and the store for the secret values and confirm none appears.

### Tests for User Story 3

- [ ] T052 [P] [US3] Write the whole-surface secrets test in `tests/integration/test_secrets.py` — plant sentinel values, run **every** command in both human and `--json` form, then search stdout, stderr, the log file, and the store for each sentinel (SC-007)
- [ ] T053 [P] [US3] Write permission-check unit tests in `tests/unit/test_permissions.py` — POSIX `chmod` cases, Windows cases against captured SDDL strings, and the `UNVERIFIED` path asserting it is **never** silently `OWNER_ONLY`
- [ ] T054 [P] [US3] Write inline-secret detection unit tests in `tests/unit/test_secret_scan.py`, including false-positive cases (commit hashes, long paths, calendar IDs) that must **not** warn
- [ ] T055 [P] [US3] Add `inline-secret.toml` and `missing-credential.toml` fixtures to `tests/fixtures/configs/`

### Implementation for User Story 3

- [ ] T056 [US3] Implement presence-only credential resolution in `src/iknowwhatyoudid/credentials/store.py` returning `PRESENT`/`ABSENT`/`UNREADABLE` — the store MUST have no method returning a value (FR-021, D6)
- [ ] T057 [US3] Add the `CREDENTIAL_MISSING` readiness state and the `credential-missing`, `credential-unreadable`, and `credential-not-required` findings in `src/iknowwhatyoudid/config/validate.py`, each naming the credential and how to supply it (FR-021)
- [ ] T058 [P] [US3] Call `iknowwhatyoudid.protection.permissions.check()` for the configuration and credentials files. Do not write a second permission checker — the shipped one already handles POSIX mode bits, Windows SDDL, numeric rights masks and the `OW`/`CO` owner trustees
- [ ] T059 [US3] Map `PermissionStatus` onto findings in `src/iknowwhatyoudid/config/validate.py` — `OTHERS_CAN_READ` becomes `file-permissions`, `UNVERIFIED` becomes `file-permissions-unverified`, both warnings (FR-006, FR-017)
- [ ] T060 [US3] Assert in `tests/unit/test_permissions.py` that a config or credentials file whose check could not run is reported `UNVERIFIED` and never silently treated as safe — the assertion must hold at this feature's boundary, not only inside `protection/`
- [ ] T061 [US3] Wire `file-permissions` and `file-permissions-unverified` findings into the loader for both the configuration and credentials files in `src/iknowwhatyoudid/config/loader.py` (FR-006)
- [ ] T062 [US3] Implement inline-secret detection in `src/iknowwhatyoudid/config/secret_scan.py` — key-name patterns plus credential-shape matching, emitted as **warnings** only (FR-023, D8)
- [ ] T063 [US3] Register resolved credential values with the redaction registry in `src/iknowwhatyoudid/credentials/store.py`, and add a `logging` filter applying the same registry (FR-022, D7)
- [ ] T064 [US3] Add the `CREDENTIAL` failure category to run outcomes in `src/iknowwhatyoudid/sources/run.py`, reported distinctly from `UNREACHABLE` and `SOURCE_ERROR` and never aborting other sources (FR-024)

**Checkpoint**: US1–US3 work independently. The tool is safe to point at a real mail account's credential.

---

## Phase 6: User Story 4 — A kind of source that does not exist yet (Priority: P2)

**Goal**: A new source kind is configured, validated, listed, enabled, and ingested through the same file
and commands as a shipped one, with no existing kind and no existing configuration file changed.

**Independent Test**: Add a fixture kind no other module knows about, configure an instance, and drive it
through validate, list, kinds, enable/disable, and ingest — then assert no existing kind module and no
existing configuration fixture was modified to make that work.

### Tests for User Story 4

- [ ] T065 [P] [US4] Write the new-kind test in `tests/integration/test_us4_new_kind.py` covering all five US4 scenarios (SC-008)
- [ ] T066 [P] [US4] Add a second fixture kind, defined only within `tests/`, that no `src/` module references
- [ ] T067 [P] [US4] Write a test in `tests/unit/test_registry.py` asserting a `SourceKind` offered from outside `iknowwhatyoudid.kinds` is neither loaded nor listed (FR-031)

### Implementation for User Story 4

- [ ] T068 [US4] Implement the `sources kinds [NAME]` command in `src/iknowwhatyoudid/cli/commands.py`, rendering each kind's settings, required access, destinations, and reading availability (FR-028)
- [ ] T069 [US4] Serialise the `SourceKind` declaration directly for the `sources.kinds` `--json` payload in `src/iknowwhatyoudid/cli/render.py`, so documented and enforced contracts cannot drift (FR-032)
- [ ] T070 [US4] Ensure the `unknown-kind` finding lists the available kinds as its remedy in `src/iknowwhatyoudid/config/validate.py` (FR-029)
- [ ] T071 [US4] Confirm no special-casing of `git.local`, `mail.*`, or `calendar.*` exists anywhere in `src/iknowwhatyoudid/config/validate.py` or `cli/` — all kinds go through the same declaration path (FR-039)

**Checkpoint**: All four user stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T072 [P] Write the committed example configuration `examples/config.toml` containing **placeholders only**, per the constitution's rule on configuration templates
- [ ] T073 [P] Update `README.md` with installation, the configuration file location, and the six commands
- [ ] T074 Run every scenario in [quickstart.md](./quickstart.md) by hand and correct any that do not behave as written
- [ ] T075 Verify each of SC-001 to SC-012 has a test asserting it, and record the test name against each in [quickstart.md](./quickstart.md)
- [ ] T076 Measure SC-002 in `tests/integration/test_performance.py` — validate a 20-source configuration, confirm under 5 seconds and zero sockets
- [ ] T077 Confirm the merge gate: `uv run pytest` green, `uv run mypy src tests` clean, and a review pass against each constitution principle in [plan.md](./plan.md)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — **blocks all user stories**
- **US1 (Phase 3)**: Depends on Foundational only
- **US2 (Phase 4)**: Depends on Foundational. Its tests read `SourceStatus`, so in practice it is easiest after US1, but it does not require it
- **US3 (Phase 5)**: Depends on Foundational. Adds `CREDENTIAL_MISSING` to the readiness computation from T034, so T057 touches a US1 file
- **US4 (Phase 6)**: Depends on Foundational and on the kinds registered in T030
- **Polish (Phase 7)**: Depends on all desired stories

### Within Each User Story

- **T078 and T079 carry IDs out of phase order.** They were added after `0001` introduced `RunMode`;
  inserting them in sequence would renumber every task after T022. T078 belongs with Foundational,
  T079 with US2, and both are listed in their phases above.

- Tests written and failing before implementation
- Declarations (kinds) before validation
- Validation before commands
- Commands before their `--json` payloads

### Known cross-story file contention

Three files are touched by more than one story. Sequence these, do not parallelise them:

| File | Touched by | Order |
|------|-----------|-------|
| `config/validate.py` | T031–T034 (US1), T057 (US3), T070 (US4) | US1 → US3 → US4 |
| `cli/render.py` | T019 (Found.), T039 (US1), T050 (US2), T069 (US4) | Foundational → US1 → US2 → US4 |
| `cli/commands.py` | T035–T038 (US1), T049 (US2), T068 (US4) | US1 → US2 → US4 |

### Parallel Opportunities

- T003, T004, T005 in Setup
- T007, T008, T009 in Foundational (three independent model modules), then T013, T014, T017, T018, T021, T022
- All test-writing tasks within a story (T023–T026, T040–T043, T052–T055, T065–T067)
- The three kind declarations T027, T028, T029 — separate files, no shared state
- T058 (POSIX permissions) alongside the US3 test tasks; T059 must follow it

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together, before any implementation:
Task: "US1 acceptance scenarios in tests/integration/test_us1_declare.py"
Task: "Offline guarantee (no socket created) in tests/integration/test_offline.py"
Task: "Validation rules in tests/unit/test_validate.py"
Task: "Fault fixtures in tests/fixtures/configs/"

# Then the three kind declarations together:
Task: "Declare git.local in src/iknowwhatyoudid/kinds/git_local.py"
Task: "Declare mail.outlook/gmail/hey in src/iknowwhatyoudid/kinds/mail.py"
Task: "Declare calendar.outlook/google in src/iknowwhatyoudid/kinds/calendar.py"
```

---

## Implementation Strategy

### MVP: Setup + Foundational + US1 (T001–T039)

Stop after T039 and validate. At that point a user can write a configuration file naming their git
repositories, mail accounts, and calendars, and be told exactly what the tool understood — offline, with
every fault reported at once. That is a genuinely useful deliverable on its own, and it is the thing every
later connector is built against.

### Incremental Delivery

1. Setup + Foundational → the file can be found, parsed, rendered
2. **+ US1 → MVP.** Declare sources, get a verdict
3. + US2 → the file is safe to edit; ingestion runs across sources
4. + US3 → safe to point at a real credential
5. + US4 → the extension point is proven
6. Polish

### Parallel Team Strategy

After Foundational, US1 and US2 can proceed together if the contention table above is respected; US3 is
best started once T034 exists. US4 is the most independent and can be picked up at any point after T030.

---

## What this feature deliberately does not deliver

One gap, intended and reported by the tool rather than left to be discovered:

- **Nothing real is read.** `git.local`, `mail.*`, and `calendar.*` are declarations without readers
  (T027–T029); only `fixture` reads anything. This is FR-033 — the connectors are features `0003`, `0004`,
  and `0005`.

Source state is durable: `0001` ships `SqliteSourceStateStore`, wired in by T044.

---

## Notes

- `[P]` = different files, no dependencies on incomplete tasks
- Assert on finding `code` values, never on message text — wording must stay free to improve
- Never assert on `Finding.line`; it is best-effort by design ([research.md](./research.md) D2)
- No test may touch a real git repository, mail account, or calendar (SC-012, constitution)
- Commit after each task or logical group
