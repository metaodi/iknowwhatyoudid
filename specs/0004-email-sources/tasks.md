# Tasks: Email Sources and Correspondent Attribution

**Input**: Design documents from `/specs/0004-email-sources/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **Required**, not optional. The constitution says automated tests MUST accompany every
behavioural change, and that connector logic MUST be tested against recorded fixtures — never against the
developer's own live mail. Every test task below uses fixtures only.

**Organization**: Grouped by user story so each can be implemented, tested and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different files, no dependency on incomplete work
- **[Story]**: US1–US4 from [spec.md](./spec.md); Setup, Foundational and Polish carry no story label

## Path Conventions

Single project: `src/iknowwhatyoudid/`, `tests/` at the repository root, per
[plan.md](./plan.md)'s structure decision.

---

## Phase 1: Setup

**Purpose**: The scaffolding every later phase needs. No behaviour yet.

- [X] T001 Create the three new packages with `__init__.py` and module docstrings stating each one's single
      job: `src/iknowwhatyoudid/mail/`, `src/iknowwhatyoudid/auth/`, `src/iknowwhatyoudid/net/`
- [X] T002 [P] Add mail error types to `src/iknowwhatyoudid/errors.py`: `MailReadError`,
      `AuthorisationError`, `ConsentRequiredError`, `TokenExpiredError` — each carrying the `remedy` field
      `0001` established. The two `Hey*` types this task originally named were written and then removed
      once T067 showed there would be no CLI connector to raise them
- [X] T003 [P] Create `tests/fixtures/mail/__init__.py` and the builder module
      `tests/fixtures/mail/messages.py` that assembles RFC 5322 messages from parts, so every fixture in
      the feature is built by one place
- [X] T004 [P] Create `tests/fixtures/responses/__init__.py` with a loader that reads recorded provider
      JSON from disk, so no test embeds a payload inline
- [X] T005 Define the two sentinels in `tests/fixtures/mail/messages.py` —
      `SENTINEL-BODY-MUST-NEVER-BE-STORED` in every fixture body and `SENTINEL-ATTACHMENT.pdf` as every
      attachment name — and a helper that searches an entire store and the log for either
- [X] T006 [P] Add `hey` to the tool-detection notes in `README.md` as an optional external binary, beside
      `git`

**Checkpoint**: packages exist, fixtures can be built, nothing behaves yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The generic half of the feature — the shape, the boundaries, the schema. Everything here is
provider-agnostic, and no user story can begin until it is done.

**⚠️ CRITICAL**: No user story work may start before this phase completes.

### The boundaries, tested before they exist

- [X] T007 [P] Write `tests/integration/test_mail_boundaries.py` asserting by **AST import inspection**
      (not text search — `0003` learned that a docstring matches) that only `net/http.py` imports
      `urllib.request` or `socket`, and that nothing under `mail/` imports `subprocess`
- [X] T008 [P] Write the failing test in `tests/integration/test_mail_boundaries.py` that no module under
      `src/iknowwhatyoudid/projects/` imports `mail/`, `net/`, `auth/`, `socket` or `subprocess` — the
      structural basis for FR-044
- [X] T009 [P] Write `tests/unit/test_net_http.py` asserting `net/http.py` refuses a host not on its
      allow-list, honours `Retry-After` on 429 and 503, gives up after five attempts, and never logs a
      URL query, a header or a response body

### The only door to the network

- [X] T010 Implement `src/iknowwhatyoudid/net/http.py`: `get()` and `post()` only, a host allow-list built
      from configured account kinds, `Retry-After` handling, exponential backoff from 1s, five attempts
      maximum, and logging that records host and status and nothing else (FR-018, FR-019)

### The message shape

- [X] T011 [P] Write `tests/unit/test_mail_addresses.py` covering normalisation: case folded, display name
      and angle brackets stripped, whitespace trimmed — and asserting that Gmail dots and `+tags` are
      **not** touched (research R12)
- [X] T012 [P] Write `tests/integration/test_mail_shape.py` for the generic shape: offset preserved
      (`+0100` stays `+0100`), empty subject kept empty, fifty recipients kept in full, encoded-word
      subject decoded, a message with no `Date` skipped and reported by identifier, and both sentinels
      absent from the whole store
- [X] T013 [P] Implement `src/iknowwhatyoudid/mail/addresses.py`: `normalise()` and `domain_of()`
- [X] T014 Implement `src/iknowwhatyoudid/mail/message.py`: the `Message` dataclass from
      [contracts/message-shape.md](./contracts/message-shape.md), header parsing via `email.utils` and
      `email.header`, `Message-ID` normalisation with the derived-identifier fallback (research R10), and
      `to_record()` producing a `NormalizedRecord` with `duration=None`

### The archive reader — the simplest provider, built first

- [X] T015 [P] Write `tests/integration/test_mail_mbox.py`: an archive is read, the file is **byte-identical
      and same-mtime afterwards**, only the header block is parsed, and re-reading records zero new
      activities
- [X] T016 [P] Write the failing test in `tests/integration/test_mail_mbox.py` that a `--sweep` over an
      archive withdraws **nothing**, whatever the archive omits (research R13) — written before the reader
      so the payload flag is driven by a failing test rather than added afterwards
- [X] T017 Implement `src/iknowwhatyoudid/mail/mbox.py`: open read-only, iterate with `mailbox.mbox`, take
      headers only, set `withdrawable: false` in the payload, never write or move the file

### The store

- [X] T018 [P] Write `tests/integration/test_migration_m0003.py` covering every case in
      [contracts/schema-m0003.md](./contracts/schema-m0003.md), against **both an empty and a populated**
      store, including a deliberately failing migration that must leave the store at v2
- [X] T019 Add `CORRESPONDENT_DDL` to `src/iknowwhatyoudid/store/schema.py` and raise `SCHEMA_VERSION` to 3
- [X] T020 Implement `src/iknowwhatyoudid/store/migrations/m0003_correspondents.py` using per-statement
      `execute()` inside the runner's transaction — **never `executescript()`**, which issues an implicit
      COMMIT and would defeat the rollback `0001`'s FR-021 rests on (the mistake `m0002` was corrected for)
- [X] T021 Implement `src/iknowwhatyoudid/mail/correspondents.py`: record a message's addresses into
      `raw_correspondent` and `raw_record_correspondent`, deduplicating on the normalised address, storing
      the domain separately, and **never storing `bcc`**

### The reader seam and the kinds

- [X] T022 Implement `src/iknowwhatyoudid/mail/reader.py`: `MailReader` implementing `SourceReader`,
      dispatching on kind, yielding records, and collecting per-account skips through `0003`'s
      `ReportsSkips` protocol so a failure is named rather than swallowed (FR-017)
- [X] T023 Rewrite `src/iknowwhatyoudid/kinds/mail.py`: `mail.outlook` and `mail.gmail` become readable;
      `mail.mbox` is added with `paths`; **`mail.hey` is corrected** — destination becomes the `hey` CLI,
      required access names the read-only subcommands, and `credential_required` becomes false
      ([contracts/config-file.md](./contracts/config-file.md))
- [X] T024 [P] Write `tests/integration/test_mail_config.py` asserting the settings validation in
      [contracts/config-file.md](./contracts/config-file.md): `addresses` required and syntactically
      checked offline, `paths` required for `mail.mbox` and rejected elsewhere, every fault reported in one
      pass
- [X] T025 Extend `src/iknowwhatyoudid/config/validate.py` with those checks, contacting nothing

**Checkpoint**: an archive can be ingested end to end, attributed by `0003`'s existing repository rules to
nothing, and queried. The shape, the schema and the boundaries are all proven before a single network call
exists.

---

## Phase 3: User Story 1 — Work mail becomes evidence (Priority: P1) 🎯 MVP

**Goal**: Mail sent from a Microsoft 365 account appears in the daily record beside commits, with nothing
in the mailbox altered.

**Independent Test**: Configure one work account against recorded fixture responses, ingest, query a date
range. Every sent message appears once with the right recipients, instant and subject; received mail is
absent; the mailbox is provably unmodified; no body is anywhere in the store.

### Tests for User Story 1 ⚠️ write first, ensure they fail

- [X] T026 [P] [US1] Write `tests/integration/test_mail_readonly.py` — **the guarantee the feature rests
      on.** Assert the requested scope string is exactly `Mail.ReadBasic offline_access`, that no Graph
      endpoint used can mutate, and that no request method other than GET reaches `graph.microsoft.com`
- [X] T027 [P] [US1] Write `tests/integration/test_mail_shape.py::graph` cases against recorded Graph JSON:
      one message becomes one record with recipients, instant, subject and `sent_by`
- [X] T028 [P] [US1] Write the sentinel test in `tests/integration/test_mail_shape.py` for Graph — every
      fixture body and attachment name carries a sentinel; assert zero hits across every column of every
      table **and** the log file (FR-023, FR-024, SC-004)
- [X] T029 [P] [US1] Write `tests/integration/test_mail_auth.py` covering the five states of
      [contracts/cli-commands.md](./contracts/cli-commands.md) as distinct outcomes — absent, expired,
      administrator approval required, unreachable, ready — and asserting **no token or authorisation code
      appears** in stdout, stderr, `--json`, `--verbose` or the log (FR-010, SC-012)
- [X] T030 [P] [US1] Write `tests/integration/test_mail_resumption.py`: a second run with nothing changed
      records zero new activities; a rejected delta token falls back to a bounded full read without loss
      (SC-006)
- [X] T031 [P] [US1] Write `tests/integration/test_mail_sent_only.py`: an account fixture containing both
      sent and received mail yields only the sent messages, and the Graph request asked for the **Sent
      Items** folder rather than filtering afterwards (FR-048, SC-004a)

### Implementation for User Story 1

- [X] T032 [P] [US1] Implement `src/iknowwhatyoudid/auth/pkce.py`: code verifier and challenge via
      `secrets` and `hashlib`, and a one-shot loopback handler on `127.0.0.1` using `http.server`
      (research R7)
- [X] T033 [US1] Implement `src/iknowwhatyoudid/auth/flow.py`: authorization-code exchange and refresh over
      `net/http.py`, mapping provider errors onto `ConsentRequiredError`, `TokenExpiredError` and
      `AuthorisationError` so FR-010's states are distinguishable at the source
- [X] T034 [US1] Implement `src/iknowwhatyoudid/auth/tokens.py`: read and write `tokens.toml` beside
      `credentials.toml`, created user-only and **permission-checked on every read** with the existing
      `protection/permissions.py`; register it with `credentials/redaction.py`
- [X] T035 [US1] Implement `src/iknowwhatyoudid/mail/graph.py`: `Mail.ReadBasic offline_access`,
      `GET /me/mailFolders/sentitems/messages/delta` with an explicit `$select` that names only the seven
      fields in [contracts/provider-reading.md](./contracts/provider-reading.md), and the
      `nextLink`/`deltaLink` chain
- [X] T036 [US1] Store and restore the `deltaLink` as the source's resumption point through `0002`'s
      `src/iknowwhatyoudid/sources/state.py`, with the documented fallback when it is rejected
- [X] T037 [US1] Wire `mail.outlook` into `MailReader` in `src/iknowwhatyoudid/mail/reader.py`
- [X] T038 [US1] Implement `ikwyd sources authorise NAME` in `src/iknowwhatyoudid/cli/mail_commands.py`,
      naming the scope in plain words **before** opening the browser, with `--no-browser` and the four exit
      codes from the contract
- [X] T039 [US1] Extend `ikwyd sources check` in `src/iknowwhatyoudid/cli/sources_commands.py` to report
      the five states
- [X] T040 [US1] Implement `ikwyd mail list` in `src/iknowwhatyoudid/cli/mail_commands.py` with the
      `WHEN / ACCOUNT / PROJECT / TO / SUBJECT` columns, `--json`, and the mandatory trailing line
      `sent mail only — received mail is not read` (FR-049)
- [X] T041 [US1] Register the new commands in `src/iknowwhatyoudid/cli/main.py`

**Checkpoint**: work mail is readable, attributed to ad-hoc domain projects, queryable offline, and the
mailbox is provably untouched. **This is the MVP.**

---

## Phase 4: User Story 2 — Mail lands on the right project (Priority: P2)

**Goal**: Correspondent and subject rules put mail on projects, and changing them re-attributes without
re-reading anything.

**Independent Test**: Ingest fixture mail, apply a mapping with one correspondent rule and one subject
rule, verify each message lands where the mapping says. Change the mapping, re-derive with the fixtures
deleted and sockets forbidden, verify attributions move and every correction survives.

### Tests for User Story 2 ⚠️ write first, ensure they fail

- [X] T042 [P] [US2] Write `tests/unit/test_subject_rules.py` — including **the glob trap**: a rule
      `[ACME]` must match `Re: [ACME] plan` and must **not** match `A message`, because under glob
      semantics it would be a character class (research R11)
- [X] T043 [P] [US2] Write `tests/integration/test_mail_attribution.py` for every row of the precedence
      table in [contracts/mapping-file.md](./contracts/mapping-file.md): subject beats correspondent,
      address beats domain **whatever the declaration order**, earlier declaration beats later
- [X] T044 [P] [US2] Write the determinism test in `tests/integration/test_mail_attribution.py`: the same
      fixture mailbox ingested twice **in different orders** produces byte-identical attributions
      (SC-010b)
- [X] T045 [P] [US2] Write the ad-hoc domain test in `tests/integration/test_mail_attribution.py` for the
      algorithm in [data-model.md](./data-model.md) — own domains discarded, most frequent of the rest,
      ties broken alphabetically, own domain when nothing remains (FR-039)
- [X] T046 [P] [US2] Write `tests/integration/test_mail_rederive.py`: change the mapping, **delete every
      fixture**, forbid sockets, re-derive — attributions move, corrections stand, `--dry-run` predicts
      exactly what applying it does (FR-044, FR-045, SC-008, SC-013)
- [X] T047 [P] [US2] Write `tests/integration/test_mail_attribution.py::mapping_faults` for the fault table
      in the mapping contract, asserting every fault is reported in one pass

### Implementation for User Story 2

- [X] T048 [US2] Extend `src/iknowwhatyoudid/projects/model.py` with `CorrespondentRule` and `SubjectRule`,
      each carrying its declaration index so precedence is a property of the file's text
- [X] T049 [US2] Extend `src/iknowwhatyoudid/projects/mapping.py` to parse `correspondents` and `subjects`,
      classify an entry as address or domain by the presence of `@`, and report every fault in one pass
- [X] T050 [US2] Implement subject matching in `src/iknowwhatyoudid/projects/mapping.py` as
      case-insensitive substring — **no glob, no regex**, with the reason in a comment so a future author
      does not "improve" it
- [X] T051 [US2] Implement domain suffix matching in `src/iknowwhatyoudid/projects/mapping.py` on **domain
      labels**, so `acme.example` matches `mail.acme.example` and never `notacme.example`
- [X] T052 [US2] Extend `src/iknowwhatyoudid/projects/attribution.py` with the four new rules and the
      precedence order, recording the winning rule and its evidence (FR-035, FR-037)
- [X] T053 [US2] Implement the ad-hoc domain fallback in `src/iknowwhatyoudid/projects/attribution.py`
      exactly as [data-model.md](./data-model.md) specifies
- [X] T054 [US2] Extend `ikwyd projects validate` in `src/iknowwhatyoudid/cli/projects_commands.py` for the
      new rule kinds
- [X] T055 [US2] Implement `ikwyd mail correspondents` in `src/iknowwhatyoudid/cli/mail_commands.py`,
      including the unmapped-domain count that makes a missing mapping discoverable (FR-054)
- [X] T056 [US2] Extend `ikwyd projects list` in `src/iknowwhatyoudid/cli/projects_commands.py` to show
      correspondent counts beside repository counts

**Checkpoint**: mail lands on real projects, and getting the mapping wrong costs one file edit.

---

## Phase 5: User Story 3 — Personal mail from Gmail (Priority: P3)

**Goal**: Gmail mail appears in the same record, in the same shape, under the same rules.

**Independent Test**: Configure a Gmail account against recorded fixtures alongside the work account,
ingest both in one run, verify both produce identical activity shapes and obey the same mapping rules with
no provider-specific handling downstream of reading.

### Tests for User Story 3 ⚠️ write first, ensure they fail

- [X] T057 [P] [US3] Write `tests/integration/test_mail_readonly.py::gmail`: the requested scope is exactly
      `https://www.googleapis.com/auth/gmail.metadata`, and **`https://mail.google.com/` appears nowhere in
      the codebase** — the IMAP scope grants send and delete, and Principle II forbids holding it
      (research R2)
- [X] T058 [P] [US3] Write `tests/integration/test_mail_shape.py::gmail` — **the same assertions as the
      Graph and mbox cases, unchanged**. If Gmail needs its own assertion, FR-028 is broken (SC-014)
- [X] T059 [P] [US3] Write `tests/integration/test_mail_resumption.py::gmail`: a `historyId` 404 falls back
      to a full `SENT` list and the store deduplicates, losing nothing
- [X] T060 [P] [US3] Write `tests/integration/test_mail_auth.py::gmail_expiry`: an `invalid_grant` refresh
      reports `credential expired` with the re-authorise command, **other accounts still ingest**, and
      nothing already stored is lost (research R4)
- [X] T061 [P] [US3] Write `tests/integration/test_mail_multi_account.py`: two accounts in one run, each
      failure independent, each activity naming its account, and the same correspondent in both attributed
      to the same project by the same rule (FR-030)

### Implementation for User Story 3

- [X] T062 [US3] Implement `src/iknowwhatyoudid/mail/gmail.py`: `users.messages.list` with
      `labelIds=["SENT"]`, `users.messages.get` with `format=metadata` and `metadataHeaders` naming exactly
      the six headers, and `users.history.list` for incremental runs
- [X] T063 [US3] Apply the `since` date **client-side** on a first run in `src/iknowwhatyoudid/mail/gmail.py`,
      with a comment explaining that the metadata scope disables the API's search parameter (research R3)
- [X] T064 [US3] Store and restore `historyId` through `src/iknowwhatyoudid/sources/state.py`, with the documented 404 fallback
- [X] T065 [US3] Add Google to `src/iknowwhatyoudid/auth/flow.py` — the same PKCE flow, a different
      endpoint and scope
- [X] T066 [US3] Wire `mail.gmail` into `MailReader` in `src/iknowwhatyoudid/mail/reader.py`

**Checkpoint**: two live providers, one shape, one set of rules.

---

## Phase 6: User Story 4 — Personal mail from Hey (Priority: P4)

**Goal**: Hey mail behaves exactly as every other account does.

**Independent Test**: Configure a Hey account against an exported fixture archive and verify it produces
the same activity shape and obeys the same rules, with no change to storage, attribution or querying.

**T067 is done, and it changed this phase.** The official CLI was verified against a real account on
2026-09-10: `hey search --json` returns **no recipients and no `Message-ID`**, timestamps in UTC only, and
a body preview on every row. Without recipients there is no correspondent attribution and no ad-hoc domain
fallback; without a `Message-ID` one message read twice becomes two records. Hey mail therefore arrives
through an **exported archive**, which `mail.mbox` already reads. See [research.md](./research.md) R1 for
the captured output.

The eleven CLI tasks this phase used to hold are gone rather than deferred: `mail/hey_cli.py`,
`mail/hey.py`, the subcommand allow-list, the binary detection, the `tool missing` state and their tests.
None of them has anything to read.

- [X] T067 [US4] **Verified by hand against a real account**, and recorded in
      [research.md](./research.md) R1: no sent box exists, and a search result carries neither recipients
      nor a `Message-ID`. The assumption behind the CLI route failed
- [X] T068 [US4] Re-declare `mail.hey` in `src/iknowwhatyoudid/kinds/mail.py` as an archive kind —
      `paths` required, no credential, no destination — keeping the name so a configuration written on the
      strength of `0002`'s wrong declaration still resolves
- [X] T069 [US4] Route `mail.hey` to the archive reader in `src/iknowwhatyoudid/mail/reader.py`, recording
      `provider: "hey"` so a record still says where the mail came from
- [X] T070 [US4] Assert the corrected declaration in `tests/integration/test_mail_config.py`: no IMAP
      claimed, no credential required, `addresses` and `paths` accepted
- [X] T071 [US4] Assert in `tests/integration/test_mail_config.py` that a Hey export ingests and its
      records carry `provider: "hey"`
- [X] T072 [US4] Settled in [research.md](./research.md) R1, after a correction from the user: `--from`
      **does** filter to their own authorship, so FR-048 is not the blocker. What replaced it is worse —
      the user runs several accounts inside one Hey, and one email then appears **once per account with
      different ids and no `Message-ID`**, verified by two threads carrying identical body previews two
      minutes apart. That is double-counted work in a timesheet. Also recorded: the box listing exposes a
      per-box `changes.json?since=…` delta feed, and every search row carries ~100 characters of body
- [X] T073 [US4] Document the export route in `README.md`: where Hey's export lives, and that Hey mail is
      only as current as the last export

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T074 [P] Write `examples/config.toml` mail sections and `examples/projects.toml` correspondent and
      subject rules with **placeholders only**, per the constitution's rule on committed templates, and
      verify both validate with zero errors
- [X] T075 [P] Update `README.md`: the `mail` commands, `sources authorise`, the mapping file's new rules,
      and the six known limits from [quickstart.md](./quickstart.md)
- [X] T076 [P] Update `specs/0002-configurable-sources/contracts/config-file.md` — the three mail kinds now
      read, and `mail.hey` no longer says "Hey IMAP"
- [X] T077 [P] Update `specs/0001-local-store-foundation/contracts/cli-commands.md` if `records query`
      gains anything for mail
- [X] T078 Write `tests/integration/test_mail_offline.py`: after ingesting, forbid sockets entirely and run
      `mail list`, `mail correspondents`, `records query`, `projects list` and `projects rederive` — all
      succeed (FR-051, SC-015)
- [X] T079 Write `tests/integration/test_mail_isolation.py`: snapshot the real configuration and data
      directories, run every command in this feature against fixtures, assert nothing in them changed, and
      assert `tokens.toml` is created user-only and refused when its permissions are wider
- [X] T080 Write `tests/integration/test_mail_performance.py`: a year of sent mail streams rather than
      accumulating, with peak memory flat as the message count grows — the fault `0003` shipped and had to
      correct, so assert it here from the start
- [X] T081 Ran the quickstart scenarios and corrected what did not hold: `Mail.ReadBasic` returns
      ISO-8601 rather than RFC 5322 (so `parse_instant` handles both, and Graph's UTC-only instant is now a
      recorded limit against FR-022); `mail correspondents` listed the user as their own correspondent;
      `mail.outlook` and `mail.gmail` still declared themselves `NOT_YET_IMPLEMENTED` after gaining readers;
      and `examples/config.toml` shipped uncommented mail sources that could not validate
- [X] T082 Verify each of SC-001 to SC-016 has a test asserting it, recording the test name against each in
      [quickstart.md](./quickstart.md)
- [X] T083 Review against the constitution gates in [plan.md](./plan.md): scopes as documented, migration
      tested empty and populated, no test touching a live account, no credential in any output, `net/http.py`
      still the only door to the network
- [X] T084 Confirm the merge gate over `src/iknowwhatyoudid/` and `tests/`: `uv run pytest` green and
      `uv run mypy src tests` clean

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks every user story**
- **US1 (Phase 3)**: depends on Foundational only
- **US2 (Phase 4)**: depends on Foundational; needs US1's records to attribute, so in practice after US1
- **US3 (Phase 5)**: depends on Foundational and US1's `auth/` work; independent of US2
- **US4 (Phase 6)**: depends on Foundational only — it shares no code with the OAuth providers, so it can
  run alongside US2 and US3 if staffed
- **Polish (Phase 7)**: depends on all desired stories

### Within each user story

- Tests written and failing before implementation.
- **T016 before T017**: the "an archive never withdraws" flag must be driven by a failing test. This is the
  same trap `0003` hit with the git reflog, where treating a retention policy as deletion would have
  silently withdrawn real events.
- **T026 before any Graph code**: the read-only guarantee is what the whole feature rests on, and it is
  cheapest to keep true from the first commit.
- **T067 gated US4, and the gate closed.** The search result carried no recipients, so the CLI tasks were
  removed rather than adapted — which is what a gate is for. The archive route needs no new machinery,
  because `mail.mbox` was built in Foundational.
- **T042 before T050**: the `[ACME]` glob trap should fail first, so the substring decision is visibly
  driven by it.

### Known cross-story file contention

Sequence these; do not parallelise them:

| File | Touched by | Order |
|---|---|---|
| `mail/reader.py` | T022 (Found.), T037 (US1), T066 (US3), T069 (US4) | Foundational → US1 → US3 → US4 |
| `auth/flow.py` | T033 (US1), T065 (US3) | US1 → US3 |
| `projects/attribution.py` | T052, T053 (US2) | in order |
| `projects/mapping.py` | T049, T050, T051 (US2) | in order |
| `cli/mail_commands.py` | T038, T040 (US1), T055 (US2) | US1 → US2 |
| `cli/projects_commands.py` | T054, T056 (US2) | in order |
| `cli/sources_commands.py` | T039 (US1) | in order |
| `kinds/mail.py` | T023 (Foundational), T068 (US4) | Foundational → US4 |
| `tests/integration/test_mail_readonly.py` | T026 (US1), T057 (US3) | US1 → US3 |
| `tests/integration/test_mail_shape.py` | T012 (Found.), T027–T028 (US1), T058 (US3) | Foundational → US1 → US3 |

### Parallel opportunities

- T002, T003, T004, T006 in Setup
- T007, T008, T009 in Foundational, then T011, T012, T015, T016, T018 as a second wave
- Every test-writing task within a story: T026–T031, T042–T047, T057–T061
- **US4 is done** — it turned out to need no provider code at all
- T074, T075, T076, T077 in Polish are four separate documents

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together, before any implementation:
Task: "Read-only and scope assertions in tests/integration/test_mail_readonly.py"
Task: "Graph shape cases in tests/integration/test_mail_shape.py"
Task: "Sentinel body and attachment absence in tests/integration/test_mail_shape.py"
Task: "Five credential states in tests/integration/test_mail_auth.py"
Task: "Resumption and delta fallback in tests/integration/test_mail_resumption.py"
Task: "Sent mail only in tests/integration/test_mail_sent_only.py"
```

---

## Implementation Strategy

**MVP is Phase 1 + Phase 2 + Phase 3 (US1)** — 41 tasks. That delivers work mail in the daily record beside
commits, attributed to ad-hoc domain projects, queryable offline, with the mailbox provably untouched. It is
genuinely useful on its own: it answers "what was I doing on the 14th?" without the mapping existing yet.

**Then US2**, which is what turns a list of things that happened into "how much of Tuesday was Acme?". This
is where the feature earns its place, and it needs no further provider work.

**US3 and US4 are additive** and can be dropped or deferred without touching anything already built — which
is the test of whether FR-029 was honoured.

### One risk that could still change the plan

- **Your work tenant may refuse consent** (research R6). If it does, US1 is undeliverable against that
  account, the MVP shifts to US3 + US2, and the priority order in [spec.md](./spec.md) should be revisited
  rather than worked around. The fallback is an Outlook export, through the same archive reader Hey now
  uses.

**T067 already fired**, and is worth keeping as an example: a gate that changes the plan is doing its job.
Eleven tasks were deleted rather than written, because the thing they would have read does not exist.
