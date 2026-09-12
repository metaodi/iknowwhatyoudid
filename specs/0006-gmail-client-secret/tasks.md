---

description: "Task list for 0006 — Reading a Secret, and Saying What Went Wrong"
---

# Tasks: Reading a Secret, and Saying What Went Wrong

**Input**: Design documents from `/specs/0006-gmail-client-secret/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **Required**, not optional — the constitution says automated tests MUST accompany every
behavioural change. Three changes already shipped without them (FR-017), so this feature is partly
a debt payment and the tests are the deliverable, not the trimming.

No test signs in to a live provider, reads the developer's mail, or contacts a network. The token
endpoint is substituted throughout; Scenario 10 of [quickstart.md](./quickstart.md) is the only
step a person runs by hand.

**Organization**: by user story. US1 and US2 are both P1 — US2 is the control that makes US1 safe
to ship, so the accessor it guards is Foundational and its containment proof comes after.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel — different files, no dependency on incomplete work
- **[Story]**: US1–US3 from [spec.md](./spec.md); Setup, Foundational and Polish carry none

## Path Conventions

Single project: `src/iknowwhatyoudid/`, `tests/` at the repository root.

---

## Phase 1: Setup

**Purpose**: make the thing the user has to edit discoverable before anything reads it.

- [ ] T001 Add a commented `client_secret` line to
      `src/iknowwhatyoudid/templates/credentials.toml.template`, placeholder only, with a comment
      saying it is **not** the `client_id` and which provider needs it
      ([contracts/credential-file.md](./contracts/credential-file.md))
- [ ] T002 Extend `tests/unit/test_templates.py` so the new line is covered by the existing
      "placeholders only" and "no real value" assertions — the template is committed to a public
      repository and the check already exists; it must not silently skip the one key that now
      holds a secret

---

## Phase 2: Foundational — the doorway

**Purpose**: one accessor, correct from the first commit. Blocking for US1 and US2 alike: US1
needs a value to send, US2 needs one to prove contained.

⚠️ Written with registration included. An accessor that returns an unregistered value, even
briefly in a branch, is the leak this feature exists to prevent.

### Tests first

- [ ] T003 [P] Write `tests/unit/test_credential_value.py::returns` — a value is returned by
      credential name and key; a second key under the same name is returned too (FR-001)
- [ ] T004 [P] Write `tests/unit/test_credential_value.py::absent` — missing name, missing key,
      empty string and whitespace-only all produce one identical outcome, asserted as equality of
      results rather than four separate assertions (FR-005)
- [ ] T005 [P] Write `tests/unit/test_credential_value.py::registers_before_returning` — the value
      is registered with the redaction filter **before** it is returned. Assert the **order** by
      spying, as `0005` did for permissions-before-content: the end state is identical either way
      and the window is the whole point (FR-004)
- [ ] T006 [P] Write `tests/unit/test_credential_value.py::permission` — a world-readable
      credentials file refuses a **value** read, naming the file and the remedy (FR-003, FR-003b)
- [ ] T007 [P] Write `tests/unit/test_credential_value.py::presence_still_only_warns` — the same
      world-readable file still answers "is this name present?" and still only warns, so
      `sources list` and `sources validate` keep working (FR-003a). This is a regression test for
      a **deliberate** inconsistency; without it, someone tidying the two paths into agreement
      would break every loose-file user and look right doing it
- [ ] T008 [P] Write `tests/unit/test_credential_value.py::only_path` — walk the public surface of
      the credential store and assert no other member returns a credential value (FR-001a)

### Implementation

- [ ] T009 Implement the accessor in `src/iknowwhatyoudid/credentials/store.py`: takes a credential
      name and a key, registers whatever it returns with `credentials/redaction.py` **before**
      returning it, and returns the one "not there" outcome for every shape of absence
- [ ] T010 Add the permission refusal to the same accessor in
      `src/iknowwhatyoudid/credentials/store.py`, reusing `protection/permissions.py`. It must
      raise **before** returning anything and before any caller could make a request
- [ ] T011 Update the class docstring in `src/iknowwhatyoudid/credentials/store.py`: it currently
      says "There is deliberately no method returning a value. A future feature that must actually
      authenticate adds one behind this boundary." That future has arrived — replace it with what
      now guards the doorway, and why reading a value refuses where checking a name warns

**Checkpoint**: a value can be read, and cannot be read unsafely.

---

## Phase 3: User Story 1 — Authorising a Gmail account at all (Priority: P1)

**Goal**: `ikwyd sources authorise` works for Gmail.

**Independent Test**: with the token endpoint substituted, assert what the exchange carried — for
Gmail, and for Microsoft, and for a Microsoft account whose entry holds a secret anyway.

### Tests first

- [ ] T012 [P] [US1] Write `tests/integration/test_gmail_authorise.py::gmail_carries_it` — the
      token exchange for a Gmail account includes the client secret (FR-006)
- [ ] T013 [P] [US1] Write `tests/integration/test_gmail_authorise.py::microsoft_carries_none` —
      the exchange for a Microsoft account includes **no** client secret (FR-006, SC-002)
- [ ] T014 [P] [US1] Write `tests/integration/test_gmail_authorise.py::wrong_entry` — a Microsoft
      account whose credential entry **does** hold a secret still sends none. A secret in the wrong
      place must not enter a flow (spec Edge Cases)
- [ ] T015 [P] [US1] Write `tests/integration/test_gmail_authorise.py::refresh_carries_it` — the
      refresh request for a Gmail account carries the secret too (FR-006)
- [ ] T016 [P] [US1] Write `tests/integration/test_gmail_authorise.py::missing` — a Gmail account
      with no secret fails **before a browser opens**, naming the file, the entry and the key.
      Assert the browser was never invoked, not merely that the exit code was non-zero: a message
      arriving after a window has opened has saved nobody anything (FR-007, SC-004)
- [ ] T017 [P] [US1] Write `tests/integration/test_gmail_authorise.py::unused` — a secret in an
      entry whose kind never sends one produces exactly one warning naming the entry, **and the
      source still validates as ready**. Both halves are the assertion (FR-006a, SC-010)
- [ ] T018 [P] [US1] Write `tests/integration/test_gmail_authorise.py::nowhere_else` — no request
      the tool makes other than to a token endpoint carries the secret (FR-008)

### Implementation

- [ ] T019 [US1] Add the declarative `sends_client_secret` flag to `SourceKind` in
      `src/iknowwhatyoudid/kinds/spec.py` and set it on the kinds in
      `src/iknowwhatyoudid/kinds/mail.py` — `mail.gmail` only. Declared rather than tested for by
      provider name, so what is sent and what is warned about cannot disagree (research R6)
- [ ] T020 [US1] Extend `exchange_code` and `refresh` in `src/iknowwhatyoudid/auth/flow.py` to
      include `client_secret` in the form **only when one is supplied**, so the Microsoft call
      sites pass nothing and the negative case is structural rather than conditional
- [ ] T021 [US1] Resolve the secret in `src/iknowwhatyoudid/cli/mail_commands.py` before the
      exchange, from the credential the source names, and fail with the FR-007 message before
      `webbrowser.open` is reached
- [ ] T022 [US1] Inject the credential store into `MailReader` in
      `src/iknowwhatyoudid/mail/reader.py`, mirroring the existing `use_config_path` setter, and
      resolve the secret there for the refresh call (research R3). The reader must not construct a
      store of its own
- [ ] T023 [US1] Pass the store from `src/iknowwhatyoudid/sources/run.py`, which already
      orchestrates the reader and already has it from `open_config`
- [ ] T024 [US1] Add the unused-secret warning to `src/iknowwhatyoudid/config/validate.py`, driven
      by the kind's flag, as a **warning** finding so readiness is unaffected (FR-006a)

**Checkpoint**: Gmail authorises, Microsoft is untouched, and a secret in the wrong place says so.

---

## Phase 4: User Story 2 — A secret that cannot leak (Priority: P1)

**Goal**: the value reaches none of the six paths, and no new bypass can appear.

**Independent Test**: place a known value in a credentials file, run every command in the tool —
succeeding and failing — and assert the value appears in no stream, no log line and no payload.

### Tests first

- [ ] T025 [P] [US2] Write `tests/integration/test_secret_containment.py::six_paths` — a known
      value reaches none of stdout, stderr, `--json`, the log file, an error message, or a
      traceback, over every command in the tool (FR-009, SC-003)
- [ ] T026 [P] [US2] Write `tests/integration/test_secret_containment.py::failing_commands` — the
      same, for commands **forced to fail** while the value is loaded. The success path is the easy
      half; an error message built from provider output is where a value would actually surface
- [ ] T027 [P] [US2] Write `tests/integration/test_secret_containment.py::other_key` — a value
      stored under a key this feature never uses is masked too, proving the containment belongs to
      the accessor rather than to the one caller (FR-004a)
- [ ] T028 [P] [US2] Write `tests/integration/test_secret_containment.py::no_print_bypass` — an
      **AST** check that no module under `src/iknowwhatyoudid/cli/` writes to stdout or stderr
      without passing through the redaction chokepoint. Text matching is not enough: `0003` and
      `0004` were each caught by a grep hitting a docstring that said the opposite of the code
      (research R4)
- [ ] T029 [P] [US2] Write `tests/integration/test_secret_containment.py::echoed_back` — a provider
      response that echoes a registered value back is masked before the user sees it (FR-011)

### Implementation

- [ ] T030 [US2] Route the narration in `src/iknowwhatyoudid/cli/mail_commands.py` through the
      redaction chokepoint rather than printing directly
- [ ] T031 [US2] Route the "Opening … with $EDITOR" line in
      `src/iknowwhatyoudid/cli/setup_commands.py` through the same path. It prints no secret today;
      the guarantee is that the chokepoint has no bypasses, not that each one happens to be
      harmless
- [ ] T032 [US2] Record the known limit in `src/iknowwhatyoudid/credentials/redaction.py`: a value
      below `_MIN_LENGTH` is not registered, the threshold stays, and the accessor's contract says
      registration is *attempted* rather than guaranteed (research R5)

**Checkpoint**: the doorway from Phase 2 has no unguarded exit.

---

## Phase 5: User Story 3 — Being told what the provider actually said (Priority: P2)

**Goal**: settle the test debt from the three diagnostic fixes (FR-017), and keep the log narrow.

**Independent Test**: drive each refusal shape through the classifier and assert what the user is
shown; assert separately that the log line did not change.

### Tests first

- [ ] T033 [P] [US3] Write `tests/unit/test_refusals.py::consent` and `::expired` — each recognised
      marker produces its own message and remedy (FR-015). These could never have passed before
      the body was carried, which is what made the classification dead code
- [ ] T034 [P] [US3] Write `tests/unit/test_refusals.py::unclassified` using the **actual**
      response that produced this feature — `{"error": "invalid_request", "error_description":
      "client_secret is missing."}` — and assert the text is shown verbatim (FR-014). The test
      fails if the classification regresses to the state that made this bug take a day to find
- [ ] T035 [P] [US3] Write `tests/unit/test_refusals.py::empty_body` — a refusal with no body still
      reports the host and status, which is more than nothing (spec Edge Cases)
- [ ] T036 [P] [US3] Write `tests/unit/test_refusals.py::bounded` — a 900-character body is
      truncated to the declared maximum, asserted against the named constant rather than a literal
      (FR-013, research R7)
- [ ] T037 [P] [US3] Write `tests/unit/test_refusals.py::undecodable` — a body that is not valid
      UTF-8 produces something legible rather than an exception (spec Edge Cases)
- [ ] T038 [P] [US3] Write `tests/unit/test_refusals.py::log_unchanged` — the log line is still
      `host=… method=… status=…` and contains no fragment of the body (FR-010). The body reaches
      the user; it must not reach a file that persists and gets shared
- [ ] T039 [P] [US3] Write `tests/integration/test_gmail_authorise.py::narration` — the narration
      is on stderr **before** the blocking call is entered, and is **still there** after the
      exchange raises. Assert the ordering, not the presence: presence alone passes against the old
      behaviour, which printed everything at the end and discarded it on failure (FR-016, SC-006)

### Implementation

- [ ] T040 [US3] Confirm and, where needed, correct `src/iknowwhatyoudid/net/http.py` so the
      refusal body is carried into the error, bounded by a named constant, decoded with
      replacement, and **never** logged
- [ ] T041 [US3] Confirm and, where needed, correct the fallback branch of `_classify` in
      `src/iknowwhatyoudid/auth/flow.py` so an unrecognised refusal shows the provider's own words

**Checkpoint**: every refusal reaches the user carrying something, and the debt is paid.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T042 [P] Update `README.md`: Gmail needs a client secret in `credentials.toml`, Microsoft
      does not, and why — the current text says the configuration holds no secrets and that the
      only stored secret is a refresh token, which is about to stop being true
- [ ] T043 [P] Amend `specs/0004-email-sources/contracts/` with a note that the refusal
      classification specified there shipped unreachable and is corrected by
      [contracts/refusals.md](./contracts/refusals.md), in the manner `0005` amended `0002` and
      `0003`
- [ ] T044 [P] Update `specs/0002-configurable-sources/contracts/config-file.md` where it describes
      the credentials file as presence-checked only, with an `> **Amended by 0006**` note
- [ ] T045 Run all 10 scenarios in [quickstart.md](./quickstart.md) and correct anything that does
      not behave as written, including checking that every `-k` selector actually selects the tests
      its scenario describes — `0005` shipped three that selected nothing
- [ ] T046 Verify each of SC-001 to SC-011 has a test asserting it, recording the test name against
      each in [quickstart.md](./quickstart.md)
- [ ] T047 Review against the constitution gates in [plan.md](./plan.md): no new destination, no new
      dependency, no schema change, no widened scope, no credential in the log or the store
- [ ] T048 Confirm the merge gate: `uv run pytest` green and `uv run mypy src tests` clean
- [ ] T049 Run [quickstart.md](./quickstart.md) Scenario 10 by hand against the real Gmail account —
      `authorise`, then `ingest`, which is the only way to exercise the **refresh** path that
      [research R1](./research.md) could not verify in advance. Record the outcome in research R1,
      replacing "unverified" with what actually happened

---

## Dependencies

- **Phase 1 → Phase 2 → Phases 3, 4, 5 → Phase 6.**
- **Phase 2 blocks everything.** US1 needs a value to send; US2 needs one to prove contained. The
  accessor is not part of either story because it belongs to both.
- **T005 before T009.** The registration-order test must exist before the accessor does, or the
  accessor will be written the obvious way — return it, then register it — and the test will be
  written afterwards to match.
- **T007 before T010.** The permission refusal is easy to over-apply. The test that says the
  presence check still only warns has to exist before the refusal is written, or the refusal will
  be added at the wrong level and break `sources list`.
- **T019 before T020, T024.** Both the sending and the warning read the same flag.
- **T022 after T009.** The reader cannot resolve a secret before there is a way to resolve one.
- **US3 is independent of US1 and US2** and could ship alone. It is P2 only because it is diagnosis
  rather than function — but it is what made US1 specifiable, so it is not optional.
- **T049 last**, and only after T048: it is the one task that touches a live account.

## File-level ordering

| File | Tasks | Order |
|---|---|---|
| `credentials/store.py` | T009, T010, T011 | in order |
| `auth/flow.py` | T020 (US1), T041 (US3) | either order — different functions |
| `mail/reader.py` | T022 | after T009 |
| `cli/mail_commands.py` | T021 (US1), T030 (US2) | US1 → US2 |
| `cli/setup_commands.py` | T031 | independent |
| `kinds/mail.py`, `kinds/spec.py` | T019 | before T020, T024 |
| `config/validate.py` | T024 | after T019 |
| `net/http.py` | T040 | independent |
| `tests/unit/test_credential_value.py` | T003–T008 | parallel with each other |
| `tests/integration/test_gmail_authorise.py` | T012–T018 (US1), T039 (US3) | US1 → US3 |
| `tests/integration/test_secret_containment.py` | T025–T029 | parallel with each other |
| `tests/unit/test_refusals.py` | T033–T038 | parallel with each other |

## Parallel opportunities

- Every test-writing task within a phase: T003–T008, T012–T018, T025–T029, T033–T038
- T042, T043 and T044 in Polish are three separate documents
- US3 (Phase 5) can proceed alongside US1 and US2 — it touches `net/http.py` and `auth/flow.py`'s
  `_classify`, neither of which US1 or US2 modify

## Implementation Strategy

**MVP is Phase 2 + Phase 3 + Phase 4** — not Phase 3 alone. US1 and US2 are both P1 and the
reason is written into the spec: this feature cuts the first opening through which a credential
value can be obtained, so shipping the opening without the control would be shipping the risk on
its own. Phase 4 is not a follow-up.

Phase 5 could be deferred without breaking anything a user does. It should not be, because it is
the debt the constitution says should never have been taken, and because the next authorisation
failure will be as opaque as this one was without it.

## Notes worth keeping

- **T005, T007 and T039 all assert an *order*, not an end state.** Register-then-return and
  return-then-register end identically; narration before and after a blocking call ends
  identically once the call returns. In each case the difference is a window, and a window is only
  visible if the test looks for the sequence.
- **T014 and T018 assert absence.** Absence is not provable by watching a request succeed, which
  is why the token endpoint is substituted and the request inspected rather than the outcome.
- **T028 is an AST check for a reason.** This project has been caught three times by text matching
  a docstring that said the opposite of the code.
- **T049 is the only task that touches a live account**, and it belongs to the user rather than to
  the suite. The constitution forbids testing against the developer's own mail; running the tool
  is not a test.
