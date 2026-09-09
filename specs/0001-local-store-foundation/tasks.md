---
description: "Task list for 0001-local-store-foundation"
---

# Tasks: Local Store Foundation

**Input**: Design documents from `/specs/0001-local-store-foundation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **Included and mandatory.** The constitution requires that "automated tests MUST accompany
every behavioral change", that schema migrations "MUST be tested against both an empty and a populated
database", and that logic be tested "against recorded fixture data, never against the developer's own
live mail, calendar, or browser profile".

**Organization**: Grouped by user story so each is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1–US4)

## Path Conventions

Single project, `src/` layout: `src/iknowwhatyoudid/`, `tests/` at repository root.

**Run everything through `uv run`** — the ambient interpreter is 3.11.5 and the project requires 3.12.

---

## Phase 1: Setup

**Purpose**: Make the project installable, typed, and testable.

- [X] T001 Add `[build-system]` (hatchling), `[project.scripts] ikwyd = "iknowwhatyoudid.cli.main:main"`, and `[dependency-groups] dev = ["pytest", "mypy"]` to `pyproject.toml`; runtime `dependencies` stays empty
- [X] T002 Create the package skeleton in `src/iknowwhatyoudid/` (`__init__.py`, `__main__.py`, `py.typed`) with subpackages `cli/`, `store/`, `records/`, `derived/`, `corrections/`, `protection/`, `obs/`, `sources/`
- [X] T003 [P] Configure `mypy` strict mode over `src` and `tests` in `pyproject.toml`
- [X] T004 [P] Configure `pytest` in `pyproject.toml` and create `tests/conftest.py`, `tests/unit/`, `tests/integration/`, `tests/fixtures/`
- [X] T005 Verify the skeleton against `pyproject.toml` and `src/iknowwhatyoudid/`: `uv sync`, `uv run mypy src tests`, `uv run pytest`, and `uv run ikwyd --help` all succeed

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The connection, schema, record types, CLI shell, and logging that every user story sits on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 [P] Define the exception hierarchy and its exit-code mapping (0/1/2 per [contracts/cli-commands.md](./contracts/cli-commands.md)) in `src/iknowwhatyoudid/errors.py`
- [X] T007 [P] Implement store path resolution per platform and the `--store` override in `src/iknowwhatyoudid/store/location.py` — Windows uses `LOCALAPPDATA`, not roaming `APPDATA` (FR-001, FR-004)
- [X] T008 Implement connection setup in `src/iknowwhatyoudid/store/connection.py` — WAL, `foreign_keys=ON`, `busy_timeout`, `synchronous=FULL`, `BEGIN IMMEDIATE` for writers, and a startup refusal below SQLite 3.37 (FR-025)
- [X] T009 [P] Implement the POSIX `st_mode` branch of the permission check in `src/iknowwhatyoudid/protection/permissions.py`
- [X] T010 Implement the Windows branch of `src/iknowwhatyoudid/protection/permissions.py` via `ctypes` into `advapi32.GetNamedSecurityInfoW` and `ConvertSecurityDescriptorToStringSecurityDescriptorW`, parsing SDDL and accepting only the owner, `SY` and `BA` — **do not** use `st_mode` (meaningless on Windows) or parse `icacls` (locale-dependent), both verified broken in [research.md](./research.md) R10
- [X] T011 [P] Implement logging in `src/iknowwhatyoudid/obs/logging.py` — `RotatingFileHandler`, owner-only file, and an API whose functions accept **only** identifiers, counts and durations so record content has no path into the logger (FR-039 to FR-043)
- [X] T012 Implement the v1 DDL for all three regions in `src/iknowwhatyoudid/store/schema.py` per [contracts/schema.md](./contracts/schema.md), including `STRICT` tables and the `raw_record_live` partial index
- [X] T013 Implement the initial migration and create-at-v1 path in `src/iknowwhatyoudid/store/migrations/m0001_initial.py`
- [X] T014 [P] Define `ActivityRecord`, `IngestionRun`, `RunMode`, `NormalizedRecord` and `Batch` in `src/iknowwhatyoudid/records/model.py` per [contracts/record-shape.md](./contracts/record-shape.md)
- [X] T015 [P] Implement instant/offset/zone storage and the `was_future_at_ingestion` and `not_yet_elapsed` derived properties in `src/iknowwhatyoudid/records/timestamps.py` — **neither is stored**, per [research.md](./research.md) R7 (FR-007)
- [X] T016 [P] Implement the content-derived stable identifier (`derived:` + BLAKE2b-160 over canonical JSON) in `src/iknowwhatyoudid/records/identity.py` (FR-009)
- [X] T017 Implement the `argparse` command skeleton, global options, exit-code mapping and stdout/stderr split in `src/iknowwhatyoudid/cli/main.py`
- [X] T018 Implement the human and `--json` render chokepoint in `src/iknowwhatyoudid/cli/render.py`
- [X] T019 [P] Write store-path unit tests in `tests/unit/test_location.py` covering all three platforms and the `XDG_DATA_HOME`-unset fallback
- [X] T020 [P] Write connection unit tests in `tests/unit/test_connection.py` asserting the pragmas are set, a second writer blocks then raises, and an old SQLite is refused clearly
- [X] T021 [P] Write permission unit tests in `tests/unit/test_permissions.py` — POSIX `chmod` cases, Windows cases against captured SDDL strings, and the `UNVERIFIED` path asserting it is never silently `OWNER_ONLY`
- [X] T022 [P] Write timestamp unit tests in `tests/unit/test_timestamps.py` including a DST-repeated hour, which only the zone name resolves
- [X] T023 [P] Write identity unit tests in `tests/unit/test_identity.py` asserting the derived id is stable across runs, key order and process restarts
- [X] T024 [P] Create normalized record fixture batches under `tests/fixtures/batches/`, standing in for several notional sources
- [X] T025 [P] Write CLI contract tests in `tests/integration/test_cli_contract.py` asserting exit codes 0/1/2, that `--json` stdout parses standalone, and that diagnostics never reach stdout

**Checkpoint**: A store can be created and opened. No records yet.

---

## Phase 3: User Story 1 — A durable place for a day's traces (Priority: P1) 🎯 MVP

**Goal**: A private store appears on first use and accepts normalized records from any source, handing
them back filtered by time and source, with no network connection.

**Independent Test**: Load a fixture batch from several notional sources into a fresh store, disconnect
the network, then query by day and by source and confirm every record comes back with its evidence
intact.

### Tests for User Story 1

> Write these first; confirm they fail before implementing.

- [X] T026 [P] [US1] Write the US1 acceptance-scenario tests in `tests/integration/test_us1_store.py` covering all four scenarios from the spec
- [X] T027 [P] [US1] Write the offline guarantee test in `tests/integration/test_offline.py` asserting **no socket is created** during a full ingest-and-query cycle — assert on socket creation, not on output (SC-001)
- [X] T028 [P] [US1] Write repository unit tests in `tests/unit/test_repository.py` covering upsert, revision increment, and re-ingest producing no duplicates
- [X] T029 [P] [US1] Write withdrawal tests in `tests/integration/test_withdrawal.py` — **the negative case first**: an `INCREMENTAL` run must withdraw nothing, which is the bug `RunMode` exists to prevent ([research.md](./research.md) R6)
- [X] T030 [P] [US1] Write future-dated tests in `tests/integration/test_future_dated.py`, including advancing the clock past a record's time **without re-ingesting** and asserting it becomes countable (FR-037)
- [X] T031 [P] [US1] Write concurrency tests in `tests/integration/test_concurrency.py` — a second command waits, then fails clearly, never corrupting or returning partial results (FR-025)
- [X] T032 [P] [US1] Write corruption tests in `tests/integration/test_corruption.py` using a truncated file and a non-database file, asserting neither is deleted or overwritten (FR-026)

### Implementation for User Story 1

- [X] T033 [US1] Implement store creation on first use with owner-only permissions in `src/iknowwhatyoudid/store/location.py`, reporting the location (FR-002, FR-003, FR-005)
- [X] T034 [US1] Implement batch ingestion as one transaction per batch in `src/iknowwhatyoudid/records/repository.py` — all of it lands or none does (FR-013)
- [X] T035 [US1] Implement upsert on `(source, source_id)` in `src/iknowwhatyoudid/records/repository.py` so a re-run or overlapping range creates no duplicates (FR-011)
- [X] T036 [US1] Implement revision increment for a record re-presented with changed content in `src/iknowwhatyoudid/records/repository.py`, keeping it the same record (FR-014)
- [X] T037 [US1] Wire derived-identifier assignment for sources supplying no id into `src/iknowwhatyoudid/records/repository.py`, flagging `source_id_is_derived` (FR-009)
- [X] T038 [US1] Advance the source resumption point **inside the batch transaction** in `src/iknowwhatyoudid/records/repository.py`, and only for a completed run (FR-012, FR-013)
- [X] T039 [US1] Implement the withdrawal sweep in `src/iknowwhatyoudid/records/repository.py` — gated on `RunMode.SWEEP`, bounded to the covered range and source, marking rather than deleting (FR-027)
- [X] T040 [US1] Implement withdrawn-record semantics in `src/iknowwhatyoudid/records/repository.py` — still queryable, keeps attributions and corrections, excluded from summaries by default (FR-028)
- [X] T041 [US1] Clear a withdrawal when the record reappears, without inserting a second row, in `src/iknowwhatyoudid/records/repository.py` (FR-029)
- [X] T042 [US1] Wire the two derived future-dated properties into queries and summaries in `src/iknowwhatyoudid/records/repository.py` (FR-035 to FR-037)
- [X] T043 [US1] Implement store statistics — per-source counts, time span, last ingestion, withdrawn and future-dated counts — in `src/iknowwhatyoudid/store/stats.py` (FR-003, FR-038)
- [X] T044 [US1] Implement `quick_check` on open and a full `integrity_check` command in `src/iknowwhatyoudid/store/integrity.py`, reporting path and recovery step and never deleting the store (FR-026)
- [X] T045 [US1] Implement the best-effort disk-encryption probe in `src/iknowwhatyoudid/protection/encryption.py` — three-valued, defaulting to `UNVERIFIED`, printing the elevated command on Windows where the status is unreadable unelevated (FR-031)
- [X] T046 [US1] Implement the `store info`, `store check` and `store protection` commands in `src/iknowwhatyoudid/cli/commands.py` (FR-003, FR-026, FR-031)
- [X] T047 [US1] Implement `records query` with `--from`, `--to`, `--source` and `--include-withdrawn` in `src/iknowwhatyoudid/cli/commands.py`
- [X] T048 [US1] Implement the SQLite-backed `SourceStateStore` in `src/iknowwhatyoudid/sources/state.py` per [contracts/source-state.md](./contracts/source-state.md)

**Checkpoint**: US1 is fully functional. Records go in, come back out, offline. This is the MVP.

---

## Phase 4: User Story 2 — Change the guesses without re-downloading the year (Priority: P2)

**Goal**: Revising attribution rules re-derives everything from records already held, never returning to
any source and never touching the network.

**Independent Test**: Populate a store from fixtures, discard everything derived, re-derive with the
network disconnected and every source path made unreadable, and confirm the derived layer is rebuilt
identically.

### Tests for User Story 2

- [X] T049 [P] [US2] Write the US2 re-derivation test in `tests/integration/test_us2_rederive.py`, running with the network down and fixture paths unreadable (SC-002)
- [X] T050 [P] [US2] Write region-discard unit tests in `tests/unit/test_region_discard.py` asserting each region can be discarded without altering the other two (FR-010)

### Implementation for User Story 2

- [X] T051 [US2] Implement attribution storage carrying evidence and producing rule in `src/iknowwhatyoudid/derived/repository.py` (FR-019)
- [X] T052 [US2] Implement discard of the derived region in `src/iknowwhatyoudid/derived/repository.py`, leaving raw records and corrections untouched (FR-010)
- [X] T053 [US2] Implement discard of the raw region in `src/iknowwhatyoudid/records/repository.py` — cascades into derived attributions, touches corrections not at all (FR-010)
- [X] T054 [US2] Assert re-derivation opens no source and no socket, in `src/iknowwhatyoudid/derived/repository.py` (FR-015)
- [X] T055 [US2] Ensure re-derivation is deterministic — same raw records and same rules produce the same result twice — in `src/iknowwhatyoudid/derived/repository.py`
- [X] T056 [US2] Implement the `derived discard` command in `src/iknowwhatyoudid/cli/commands.py`
- [X] T057 [US2] Implement the rebuild report naming every record that could not be reproduced in `src/iknowwhatyoudid/store/stats.py` (FR-016)

**Checkpoint**: US1 and US2 both work independently. Iterating on attribution is affordable.

---

## Phase 5: User Story 3 — Corrections are never lost (Priority: P2)

**Goal**: A user's correction outlives a re-analysis, a schema upgrade, and deleting the whole store and
re-ingesting from scratch.

**Independent Test**: Record corrections against a fixture store, delete the store, re-ingest the same
fixtures, and confirm every correction is present and re-applied to the matching records.

### Tests for User Story 3

- [X] T058 [P] [US3] Write the survival test in `tests/integration/test_us3_corrections.py` covering all three paths — re-derivation, migration, and full delete-and-rebuild (SC-004)
- [X] T059 [P] [US3] Write the round-trip test in `tests/integration/test_corrections_roundtrip.py` — export, import into an empty store, assert an identical correction set including pending entries and `made_at`
- [X] T060 [P] [US3] Write import-conflict tests in `tests/integration/test_import_conflicts.py` covering newer, older, equal `made_at`, and an absent record (FR-033, SC-014)
- [X] T061 [P] [US3] Create correction fixtures under `tests/fixtures/corrections/`, including a conflicting pair and one for a record no store holds
- [X] T062 [US3] Define the correction model carrying `made_at` in `src/iknowwhatyoudid/corrections/model.py` (FR-032)
- [X] T063 [US3] Implement correction storage keyed by `(source, source_id)` — **not** by internal row id — in `src/iknowwhatyoudid/corrections/repository.py`, which is what lets FR-017 survive a rebuild
- [X] T064 [US3] Implement correction precedence over any derived attribution for the same record in `src/iknowwhatyoudid/corrections/repository.py` (FR-019)
- [X] T065 [US3] Verify corrections survive discarding the derived region in `src/iknowwhatyoudid/corrections/repository.py` (FR-017)
- [X] T066 [US3] Verify corrections survive a schema migration in `src/iknowwhatyoudid/corrections/repository.py` (FR-017)
- [X] T067 [US3] Implement re-application by source-side keys after a delete-and-rebuild in `src/iknowwhatyoudid/corrections/repository.py` (FR-017)
- [X] T068 [US3] Implement JSON Lines export in `src/iknowwhatyoudid/corrections/portable.py` per [contracts/corrections-file.md](./contracts/corrections-file.md), with `made_at` always in UTC (FR-018)
- [X] T069 [US3] Implement import, retaining a correction with no matching record as pending rather than dropping it, in `src/iknowwhatyoudid/corrections/portable.py` (FR-018)
- [X] T070 [US3] Implement newest-wins conflict resolution with equal `made_at` keeping the local correction, in `src/iknowwhatyoudid/corrections/portable.py` (FR-033)
- [X] T071 [US3] Report every replacement and every declined replacement with the record and both versions, in `src/iknowwhatyoudid/corrections/portable.py` — the mitigation for newest-wins being only as good as the clocks (FR-034)
- [X] T072 [US3] Make the whole import one transaction and add `--dry-run` in `src/iknowwhatyoudid/corrections/portable.py`
- [X] T073 [US3] Clear the pending flag when a pending correction's record is later ingested, in `src/iknowwhatyoudid/corrections/repository.py` (FR-018)
- [X] T074 [US3] Implement the `corrections export`, `corrections import` and `corrections list --pending` commands in `src/iknowwhatyoudid/cli/commands.py`

**Checkpoint**: US1–US3 work independently. The irreplaceable data is safe.

---

## Phase 6: User Story 4 — Upgrading does not cost the archive (Priority: P3)

**Goal**: A store holding months of records is migrated in place on upgrade, and a migration that cannot
finish leaves the store exactly as it was rather than half-converted.

**Independent Test**: Build a store at an older structure version with records and corrections, run the
current tool, confirm counts are unchanged and the version advanced; repeat with a deliberately failing
migration and confirm the store is unchanged and still usable.

### Tests for User Story 4

- [X] T075 [P] [US4] Write migration tests in `tests/integration/test_migration.py` covering success, deliberate failure, and a newer-version store — each against **both an empty and a populated store**, as the constitution requires
- [X] T076 [P] [US4] Create store fixtures under `tests/fixtures/stores/` at an older schema version, holding records and corrections

### Implementation for User Story 4

- [X] T077 [US4] Implement the migration runner with ordered discovery of migration modules in `src/iknowwhatyoudid/store/migrate.py` (FR-020)
- [X] T078 [US4] Apply all pending migrations inside **one** `BEGIN IMMEDIATE` that also sets `PRAGMA user_version`, in `src/iknowwhatyoudid/store/migrate.py` — verified that DDL is transactional and `user_version` rolls back with it, so this is the whole of FR-021
- [X] T079 [US4] Take a pre-migration file snapshot via the online backup API in `src/iknowwhatyoudid/store/migrate.py`, documented as the **second** safety net for what transactions cannot cover, not the primary rollback
- [X] T080 [US4] Implement the failure path in `src/iknowwhatyoudid/store/migrate.py` — report what failed, leave the store at its previous version and fully usable, retain the snapshot (FR-021)
- [X] T081 [US4] Refuse every command on a store written by a newer version in `src/iknowwhatyoudid/store/migrate.py`, exiting 2 and changing nothing (FR-022)
- [X] T082 [US4] Run pending migrations automatically when any command opens an older store, in `src/iknowwhatyoudid/store/connection.py` (FR-020)
- [X] T083 [US4] Implement the `store migrate` command with `--dry-run` in `src/iknowwhatyoudid/cli/commands.py`
- [X] T084 [US4] Add a second, test-only migration under `tests/fixtures/stores/` to exercise the upgrade path end to end without inventing a real schema change
- [X] T085 [US4] Assert record and correction counts are identical before and after a successful migration, and unchanged after a failed one, in `tests/integration/test_migration.py` (SC-006, SC-007)

**Checkpoint**: All four user stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Reconciling feature 0002**, which was planned before this one and assumed it would own files that
belong here ([plan.md](./plan.md), "Correction to feature 0002's plan"):

- [X] T086 [P] Update `specs/0002-configurable-sources/plan.md` to record that `errors.py`, `cli/main.py`, `cli/render.py` and the permission check are owned by `0001` and extended, not created, by `0002`
- [X] T087 [P] Update `specs/0002-configurable-sources/tasks.md` — T001–T005 become extensions rather than creations, T019/T020 extend the existing CLI and render modules, and T058–T060 are replaced by a call into `src/iknowwhatyoudid/protection/permissions.py`
- [X] T088 [P] Remove the "does not exist yet" caveat and the in-memory limitation from `specs/0002-configurable-sources/contracts/source-state.md`
- [X] T089 Replace `InMemorySourceStateStore` with the SQLite implementation as `0002`'s default and drop the `persistence: in_memory_only` field and its stderr notice from `src/iknowwhatyoudid/cli/render.py`

**Documentation and gates**:

- [X] T090 [P] Update `README.md` with installation, the store location, and the store and corrections commands
- [X] T091 Run all 14 scenarios in [quickstart.md](./quickstart.md) by hand and correct any that do not behave as written
- [X] T092 Verify each of SC-001 to SC-015 has a test asserting it, recording the test name against each in [quickstart.md](./quickstart.md)
- [X] T093 Measure SC-008 in `tests/integration/test_performance.py` — generate a year of records and confirm `store info` completes under 5 seconds using the `raw_record_live` index
- [X] T094 Review against the constitution's quality gates in [plan.md](./plan.md) — migrations tested empty and populated, no test touching a real account, no secret in store or log
- [X] T095 Confirm the merge gate over `src/iknowwhatyoudid/` and `tests/`: `uv run pytest` green and `uv run mypy src tests` clean

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — **blocks all user stories**
- **US1 (Phase 3)**: Depends on Foundational only
- **US2 (Phase 4)**: Depends on Foundational; needs raw records to derive from, so in practice after US1
- **US3 (Phase 5)**: Depends on Foundational. T065 needs US2's discard, T066 needs US4's migration — write those two assertions last
- **US4 (Phase 6)**: Depends on Foundational only. Genuinely independent and can be built early
- **Polish (Phase 7)**: Depends on all desired stories; T086–T089 additionally touch `0002`

### Within Each User Story

- Tests written and failing before implementation
- Models before repositories, repositories before commands
- For US1 specifically: **write T029 (incremental-never-withdraws) before T039**, so the sweep gate is driven by a failing test rather than added afterwards

### Known cross-story file contention

Sequence these; do not parallelise them:

| File | Touched by | Order |
|------|-----------|-------|
| `cli/commands.py` | T046, T047 (US1), T056 (US2), T074 (US3), T083 (US4) | US1 → US2 → US3 → US4 |
| `records/repository.py` | T034–T042 (US1), T053 (US2) | US1 → US2 |
| `corrections/repository.py` | T063–T067, T073 (US3) | in order |
| `store/migrate.py` | T077–T081 (US4) | in order |
| `store/stats.py` | T043 (US1), T057 (US2) | US1 → US2 |

### Parallel Opportunities

- T003, T004 in Setup
- Foundational splits cleanly: T006, T007, T009, T011, T014, T015, T016 are independent modules, then all seven unit-test tasks T019–T025
- Every test-writing task within a story (T026–T032, T049–T050, T058–T061, T075–T076)
- T009 (POSIX permissions) alongside other Foundational work; T010 must follow it
- The whole of US4 can run alongside US1 if staffed — it touches only `store/migrate.py` and its own tests
- T086–T088 in Polish are three separate documents

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together, before any implementation:
Task: "US1 acceptance scenarios in tests/integration/test_us1_store.py"
Task: "Offline guarantee (no socket) in tests/integration/test_offline.py"
Task: "Repository upsert and revisions in tests/unit/test_repository.py"
Task: "Withdrawal, negative case first, in tests/integration/test_withdrawal.py"
Task: "Future-dated records in tests/integration/test_future_dated.py"
Task: "Concurrency in tests/integration/test_concurrency.py"
Task: "Corruption handling in tests/integration/test_corruption.py"
```

---

## Implementation Strategy

### MVP: Setup + Foundational + US1 (T001–T048)

Stop after T048 and validate. At that point there is a private store that accepts normalized records from
any source and hands them back by day and by source, offline — including the withdrawal and future-dated
semantics that the later connectors depend on being right. Every subsequent feature in the project writes
to this.

### Incremental Delivery

1. Setup + Foundational → a store can be created and opened
2. **+ US1 → MVP.** Records in, records out, offline
3. + US2 → attribution can be iterated on without re-downloading the year
4. + US3 → the irreplaceable data is safe across all three paths
5. + US4 → upgrades stop being frightening
6. Polish, including reconciling `0002`

### Parallel Team Strategy

After Foundational, US1 and US4 can proceed simultaneously — US4 touches only the migration runner and its
own fixtures. US2 needs US1's records to exist. US3 can start on its own model and export format
immediately, deferring only its two cross-story assertions (T065, T066).

---

## Notes

- `[P]` = different files, no dependencies on incomplete tasks
- No test may touch a real git repository, mail account, or calendar — fixtures only (constitution)
- Migrations are tested against **both** an empty and a populated store (constitution)
- The negative tests carry the weight here: no socket opened (T027), incremental never withdraws (T029),
  no record content in the log (T011's API shape), a store never deleted on the tool's initiative (T032)
- Commit after each task or logical group
