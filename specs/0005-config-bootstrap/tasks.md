# Tasks: Getting Configured — `init` and `edit`

**Input**: Design documents from `/specs/0005-config-bootstrap/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **Required**, not optional. The constitution says automated tests MUST accompany
every behavioural change. No test here spawns a real editor or writes to the real
configuration directory.

**Organization**: Grouped by user story. US1 and US2 are both P1 and both concern `init` —
US2 is the safety property that makes US1 safe to ship, so its test is written first.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different files, no dependency on incomplete work
- **[Story]**: US1–US3 from [spec.md](./spec.md); Setup, Foundational and Polish carry none

## Path Conventions

Single project: `src/iknowwhatyoudid/`, `tests/` at the repository root.

---

## Phase 1: Setup — moving the templates

**Purpose**: Put the template files where they will actually ship. Verified in
[research.md](./research.md) R1: `examples/` is **not** in the wheel, so reading templates
from there would work in a checkout and fail for everyone who installed the tool.

- [X] T001 Create `src/iknowwhatyoudid/templates/__init__.py` with a docstring explaining
      that this is a package directory **only** so `importlib.resources` can address it by
      module name rather than by guessing a filesystem path
- [X] T002 **Move** (`git mv`, not copy) `examples/config.toml` to
      `src/iknowwhatyoudid/templates/config.toml`
- [X] T003 **Move** `examples/projects.toml` to `src/iknowwhatyoudid/templates/projects.toml`
- [X] T004 **Move** `examples/credentials.toml.example` to
      `src/iknowwhatyoudid/templates/credentials.toml`, dropping the `.example` suffix — the
      file is now addressed by code, and the suffix existed to stop it being mistaken for a
      real credentials file in a directory users browse
- [X] T005 Write `examples/README.md` replacing the files: what they were, where they went,
      and that `ikwyd init` is now how you get them
- [X] T006 Update `README.md` — replace the `cp examples/config.toml "$APPDATA/…"`
      instruction with `ikwyd init`, since deleting that instruction is what this feature is
      for
- [X] T007 [P] Write `tests/unit/test_templates.py` asserting every template is readable
      through `importlib.resources`, parses as TOML, and holds placeholders only — no real
      address, path or token, because this repository is public
- [X] T008 [P] Add the packaging assertion to `tests/unit/test_templates.py`, marked `slow`:
      build a wheel and assert all three templates are inside it. **This is the test that
      would have caught the original bug**, and it is the only one here that runs a build

**Checkpoint**: the templates ship, and a test proves it.

---

## Phase 2: Foundational — amending what came before

**Purpose**: `0002` FR-002 and `0003` FR-029 currently forbid the code this feature adds.
Principle III says the spec is the source of truth and the code is the defect, so the specs
change **first** — not afterwards to match what was built.

**⚠️ CRITICAL**: No user story work may start before this phase completes. Writing the code
first would mean shipping code that its own specification forbids.

- [X] T009 [P] Amend FR-002 in `specs/0002-configurable-sources/spec.md` from "never writes"
      to "never modifies, reformats, reorders or rewrites anything the user wrote", recording
      that `0005` narrowed it and why
- [X] T010 [P] Amend `specs/0002-configurable-sources/contracts/config-file.md` likewise,
      naming `ikwyd init` as the one command that may create the file
- [X] T011 [P] Amend FR-029 in `specs/0003-git-source-projects/spec.md` the same way
- [X] T012 [P] Amend `specs/0003-git-source-projects/contracts/mapping-file.md` likewise
- [X] T013 [P] Amend `specs/0004-email-sources/contracts/config-file.md` and
      `contracts/mapping-file.md`, which say the never-writes rule is "unchanged" — they now
      inherit the narrowed rule
- [X] T014 Implement `src/iknowwhatyoudid/config/bootstrap.py`: read a named template through
      `importlib.resources`, and create one file **only where none exists**. Create empty,
      `restrict_to_owner`, then write — in that order, for **every** file, so the sensitive
      case cannot be the one somebody forgets (research R5)
- [X] T015 Add the `Outcome` result type to `src/iknowwhatyoudid/config/bootstrap.py`:
      `CREATED`, `LEFT_ALONE`, `FAILED`, one per file, with its path — never one verdict for
      the whole run (research R6)

**Checkpoint**: the specifications permit what follows, and the one module that writes files
exists.

---

## Phase 3: User Story 1 — Getting started without a treasure hunt (Priority: P1) 🎯 MVP

**Goal**: One command puts the three files where the tool looks for them.

**Independent Test**: In an empty configuration directory, run `ikwyd init` and verify all
three files appear with the shipped content, that `credentials.toml` is readable by its owner
alone, that the tool then finds them without being told where, and that they validate.

### Tests for User Story 1 ⚠️ write first, ensure they fail

- [X] T016 [P] [US1] Write `tests/integration/test_init.py::fresh` — all three files appear
      in an empty directory, are exactly the shipped templates, and the directory is created
      if absent with nothing written outside it
- [X] T017 [P] [US1] Write the validation test in `tests/integration/test_init.py`: after
      `init`, `sources validate` and `projects validate` both pass with **zero errors**.
      `0004` shipped an `examples/config.toml` that could not validate and no test caught it;
      `init` makes these files the first thing a new user sees
- [X] T018 [P] [US1] Write `tests/integration/test_init.py::credentials` — created readable
      by its owner and nobody else, **asked of the operating system** rather than trusted from
      the write, and asserting permissions are applied *before* content (FR-015)
- [X] T019 [P] [US1] Write `tests/integration/test_init.py::reporting` — every combination of
      present and absent across the three files, verifying each is decided independently and
      that `init` exits `0` when there is nothing to do

### Implementation for User Story 1

- [X] T020 [US1] Implement `init` in `src/iknowwhatyoudid/cli/setup_commands.py`: resolve the
      configuration directory, create it if absent, call `bootstrap` once per file, and
      report per file with its path
- [X] T021 [US1] Add the `--json` form of `init` in
      `src/iknowwhatyoudid/cli/setup_commands.py`, matching
      [contracts/cli-commands.md](./contracts/cli-commands.md) — `files[]` with an outcome
      each, and `owner_only` on the credentials entry
- [X] T022 [US1] Add the closing guidance to `init`'s output in
      `src/iknowwhatyoudid/cli/setup_commands.py`: what to edit, and that
      `ikwyd sources validate` is next (FR-018)
- [X] T023 [US1] Register `init` in `src/iknowwhatyoudid/cli/main.py` with `--config` and
      `--json`

**Checkpoint**: a new user goes from installed tool to validating configuration in one
command. **This is the MVP.**

---

## Phase 4: User Story 2 — Never losing what I wrote (Priority: P1)

**Goal**: Nothing the user wrote is ever altered, and no flag exists that would.

**Independent Test**: With all three files present — including a `credentials.toml` holding a
recognisable value — run `init` and verify every one is byte-identical afterwards, that the
output says it left them alone, and that nothing was written anywhere.

### Tests for User Story 2 ⚠️ write T024 before T014's implementation is trusted

- [X] T024 [P] [US2] Write `tests/integration/test_init.py::existing` — write all three files
      with known content, hash them, run `init`, hash again, assert byte-identical. **The
      guarantee the whole requirement amendment rests on**
- [X] T025 [P] [US2] Write the negative assertion in `tests/integration/test_init.py`: walk
      the argument parser for `init` and assert **no** option resembling `--force`,
      `--overwrite` or `--replace` exists (FR-009). This is what stops the narrowing in
      [contracts/amendments.md](./contracts/amendments.md) quietly becoming a relaxation
- [X] T026 [P] [US2] Write `tests/integration/test_init.py::credentials_untouched` — an
      existing credentials file holding a recognisable value is byte-identical after `init`.
      The highest-stakes case: overwriting it destroys a secret rather than a preference
- [X] T027 [P] [US2] Write `tests/integration/test_init.py::partial` — one file present and
      two absent creates two and leaves one, with the output saying which was which

### Implementation for User Story 2

- [X] T028 [US2] Confirm and, if needed, correct `src/iknowwhatyoudid/config/bootstrap.py` so
      an existing file is never opened for writing at all — checked before the file is
      touched, not by catching an error afterwards
- [X] T029 [US2] Extend and rename the whole-surface test in
      `tests/integration/test_sources_cli.py`: cover `init`, `sources edit` and
      `projects edit`, and cover `projects.toml` and `credentials.toml` as well as
      `config.toml`. The renamed test asserts the property that matters — **nothing the user
      wrote is ever changed** (FR-004)

**Checkpoint**: the amendment is safe, because the thing it narrowed is still enforced.

---

## Phase 5: User Story 3 — Opening the file I need to change (Priority: P2)

**Goal**: One command opens the right file in the editor the user already uses.

**Independent Test**: With the launcher substituted, run each command and verify the correct
path is handed over, that the file is unchanged afterwards, and that a file of invalid TOML
still opens.

### Tests for User Story 3 ⚠️ write first, ensure they fail

- [X] T030 [P] [US3] Write `tests/unit/test_editor_command.py` for the resolver: every row of
      [research.md](./research.md) R2, including the Windows path both `shlex` modes mangle,
      the quoted form, `$VISUAL` winning over `$EDITOR`, and an editor set to something that
      does not exist being reported **by name**
- [X] T031 [P] [US3] Write the safety assertions in `tests/unit/test_editor_command.py`: the
      file path is **always the last argument**, appended rather than interpolated, and
      `shell=True` appears nowhere — checked through the AST, because a path containing `&`
      must be an argument rather than a command
- [X] T032 [P] [US3] Write `tests/integration/test_edit.py` — `sources edit` hands over the
      configuration path, `projects edit` the mapping path, `--config` and `--projects` are
      honoured, and the file is byte-identical afterwards
- [X] T033 [P] [US3] Write the invalid-TOML test in `tests/integration/test_edit.py`: a file
      too broken to parse still opens, because `edit` never reads it (FR-024). This is the
      case you most need the command for
- [X] T034 [P] [US3] Write `tests/integration/test_edit.py::missing` and `::no_editor` — a
      missing file is **not created** and `init` is named; no editor at all prints the path
      and says plainly that it could not open it, never silently doing nothing

### Implementation for User Story 3

- [X] T035 [US3] Implement the resolver in `src/iknowwhatyoudid/cli/editor.py` as a **pure
      function** returning a list of arguments: `$VISUAL`, then `$EDITOR`, then the platform
      opener. Whole-value-is-a-file first, else `shlex.split(posix=True)` (research R2)
- [X] T036 [US3] Implement the launcher in `src/iknowwhatyoudid/cli/editor.py`: `shell=False`,
      path appended last, and `os.startfile` on Windows so the default-application path needs
      no subprocess at all (research R3)
- [X] T037 [US3] Implement `sources edit` and `projects edit` in
      `src/iknowwhatyoudid/cli/setup_commands.py`, doing **nothing** once the editor closes —
      no validation, no ingestion (FR-025)
- [X] T038 [US3] Register both in `src/iknowwhatyoudid/cli/main.py`, under the existing
      `sources` and `projects` groups
- [X] T039 [US3] Add `cli/editor.py` to the permitted process-spawning modules in
      `tests/integration/test_mail_boundaries.py`, **with its reason recorded beside the other
      two** — and note that its lock is a different shape: an editor is chosen by the user, so
      what is asserted is that the tool never *constructs* a command (research R4)
- [X] T040 [US3] Correct the claim in `src/iknowwhatyoudid/cli/mail_commands.py` that
      `sources authorise` is "the only interactive command in the tool". Replace the count
      with the rule that actually matters: **no interactive command is reachable from
      `ingest`**
- [X] T041 [US3] Add `tests/integration/test_edit.py::not_reachable_from_ingest` asserting
      that rule for all three interactive commands, so a scheduled run can never block on a
      browser or an editor (FR-026)

**Checkpoint**: the edit loop is one command long.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T042 [P] Update `README.md` with the three new commands and the getting-started flow
      they replace
- [X] T043 [P] Update `specs/0001-local-store-foundation/contracts/cli-commands.md` with the
      `init` and `edit` commands, as each feature has done for its own additions
- [X] T044 Write `tests/integration/test_init.py::isolation` — snapshot the **real**
      configuration and data directories, run every command in this feature against a
      temporary one, and assert nothing in the real ones changed. `0001` wrote its log to the
      real data directory once despite `--store`
- [X] T045 Write `tests/integration/test_init.py::offline` — every command in this feature
      succeeds with sockets forbidden and no store present, because this feature opens neither
      (FR-028, FR-029)
- [X] T046 Run all 10 scenarios in [quickstart.md](./quickstart.md) by hand and correct
      anything that does not behave as written
- [X] T047 Verify each of SC-001 to SC-012 has a test asserting it, recording the test name
      against each in [quickstart.md](./quickstart.md)
- [X] T048 Review against the constitution gates in [plan.md](./plan.md): no network, no store
      access, no source touched, no credential value written, templates hold placeholders only
- [X] T049 Confirm the merge gate over `src/iknowwhatyoudid/` and `tests/`: `uv run pytest`
      green and `uv run mypy src tests` clean

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies. Moves files; writes no code.
- **Foundational (Phase 2)**: depends on Setup — **blocks every user story**, because the
  specifications currently forbid the code the stories add.
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on Foundational; shares `bootstrap.py` with US1, so in practice
  after it — but see the ordering note below.
- **US3 (Phase 5)**: depends on Foundational only. **Shares nothing with US1 or US2** and can
  run alongside them if staffed.
- **Polish (Phase 6)**: depends on all desired stories.

### Within each user story

- Tests written and failing before implementation.
- **T024 before T014 is trusted.** US1 and US2 are both P1 and both concern `init`; US2 is not
  a separate deliverable but the safety property that makes US1 safe to ship. The
  "never overwrite" test should exist and fail before the creating code is believed — the
  same discipline `0003` used for the reflog and `0004` for the archive sweep.
- **T030 and T031 before T035.** The resolver's whole value is that it is pure, so every case
  in research R2 is a test that spawns nothing. Writing it first is what keeps it that way.
- **T009–T013 before any code.** Amending afterwards to match what was built is precisely
  what Principle III forbids.

### Known cross-story file contention

Sequence these; do not parallelise them:

| File | Touched by | Order |
|---|---|---|
| `config/bootstrap.py` | T014, T015 (Found.), T028 (US2) | Foundational → US2 |
| `cli/setup_commands.py` | T020–T022 (US1), T037 (US3) | US1 → US3 |
| `cli/main.py` | T023 (US1), T038 (US3) | US1 → US3 |
| `cli/editor.py` | T035, T036 (US3) | in order |
| `tests/integration/test_init.py` | T016–T019 (US1), T024–T027 (US2), T044–T045 (Polish) | US1 → US2 → Polish |
| `tests/unit/test_templates.py` | T007, T008 (Setup) | in order |
| `tests/unit/test_editor_command.py` | T030, T031 (US3) | in order |
| `README.md` | T006 (Setup), T042 (Polish) | Setup → Polish |

### Parallel opportunities

- T007 and T008 in Setup, after the moves
- **All five amendment tasks T009–T013** — five separate documents, no code
- Every test-writing task within a story: T016–T019, T024–T027, T030–T034
- **US3 can run entirely alongside US1 and US2** — it shares only `cli/setup_commands.py` and
  `cli/main.py`, which the contention table sequences
- T042 and T043 in Polish are two separate documents

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together, before any implementation:
Task: "Fresh directory creates three files in tests/integration/test_init.py"
Task: "Created files validate cleanly in tests/integration/test_init.py"
Task: "Credentials file is owner-only, asked of the OS, in tests/integration/test_init.py"
Task: "Per-file outcomes across every present/absent combination in tests/integration/test_init.py"
```

---

## Implementation Strategy

**MVP is Phase 1 + Phase 2 + Phase 3 (US1)** — 23 tasks. That delivers `ikwyd init`: a new
user goes from an installed tool to a validating configuration in one command, which is the
step most likely to make someone give up today.

**Phase 4 (US2) is not optional in practice.** It is listed separately because it is
separately testable, but shipping `init` without the never-overwrite guarantee would mean
shipping a command that can destroy a year of tuned attribution rules. Treat Phases 3 and 4
as one deliverable.

**Phase 5 (US3) is genuinely additive** and can be dropped or deferred without touching
anything already built — the paths it opens are already printed by several existing commands.

### Risks

- **The wheel-build test (T008) is the only one that runs a build**, and it is the only one
  that would catch research R1's bug recurring. If it is ever marked skip, the feature
  silently breaks for installed users while every other test stays green.
- **T040 corrects a claim rather than code.** It is easy to skip and leaves a comment
  asserting something false, which is worse than no comment: the next person to read it will
  believe it.
