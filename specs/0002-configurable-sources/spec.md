# Feature Specification: Configurable Sources

**Feature Directory**: `specs/0002-configurable-sources`

**Created**: 2026-09-09

**Status**: Draft

**Input**: User description: "the tool should have multiple sources that can be configured in a config file (most probably a YAML file, but open to other suggestions if there is a good reason for it). It should be extensible so that new sources can be added later. I imagine to have at least these sources to start: 1) Local git repositories (i.e. which git repo was worked on, when were commits made, branches merged etc.) 2) e-mail from Outlook, GMail, Hey (i.e. what email were sent or reveiced on each day, which projects certain persons belong to etc.) 3) calendar integration with Outlook and Google Calendar"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Declare where my traces live (Priority: P1)

Someone has a store but nothing in it. They open one file, write down the places their working day
leaves traces — the folder holding their git repositories, their work mail account, their calendar — and
ask the tool whether it understood them. It answers with a list: every source it found, what kind it is,
whether it is switched on, and for each one either "ready" or a specific, actionable reason it is not.
Nothing has been read from any source yet and nothing has been written to the store.

**Why this priority**: This is the whole feature's reason to exist. Until a user can name their sources
and get told plainly whether the tool understood, no connector can be written and no ingestion can be
scheduled. Delivered alone it is already useful: it turns "what can this tool see?" from a question about
code into a question about one readable file.

**Independent Test**: Write a configuration file naming several sources of different kinds, run the
validation command, and confirm every source is listed with a correct ready/not-ready verdict — then
introduce one fault at a time (a missing path, a duplicate name, an unknown kind) and confirm each is
reported by name with its location in the file.

**Acceptance Scenarios**:

1. **Given** a machine with no configuration file, **When** the user asks what sources are configured,
   **Then** they are told no configuration exists, are shown the exact path where one is expected, and
   nothing is created or read.
2. **Given** a valid configuration naming several sources, **When** the user lists sources, **Then** each
   appears with its name, its kind, whether it is enabled, and a ready/not-ready verdict — and with a
   `--json` form carrying the same information.
3. **Given** a configuration with a malformed entry, **When** validation runs, **Then** the user is told
   which source and which setting is at fault and where in the file it is, and no source is treated as
   ready.
4. **Given** a configuration whose file is syntactically broken, **When** any command runs, **Then** the
   tool reports the parse failure with its location and refuses to run rather than proceeding with a
   partial configuration.
5. **Given** any validation run, **When** it completes, **Then** no configured source has been contacted
   or read, and the store is unchanged.

---

### User Story 2 - Add, disable, and retire a source without disturbing the rest (Priority: P1)

The user already has three sources working. They add a fourth, and later switch one off because it is
noisy. Each change affects only the source it names: the others keep their history, their resumption
points, and their already-ingested records. Switching a source off stops it being read; it does not
delete what it already contributed.

**Why this priority**: A configuration file that must be right all at once is a configuration file people
stop editing. Independent, reversible per-source changes are what make the file safe to touch, and they
are what let the three initial source kinds be adopted one at a time rather than all together.

**Independent Test**: Start from a configuration with several sources and a populated fixture store; add
one source, disable another, and rename a third; then confirm that the untouched sources' record counts
and resumption points are unchanged, and that each change produced exactly the intended effect.

**Acceptance Scenarios**:

1. **Given** a working configuration, **When** a new source is added to it, **Then** the existing sources'
   stored records, resumption points, and ingestion histories are unchanged.
2. **Given** a source that has already contributed records, **When** it is disabled, **Then** it is
   skipped by any subsequent ingestion and its existing records remain in the store and remain queryable.
3. **Given** a disabled source, **When** it is re-enabled, **Then** the next ingestion resumes from where
   it previously stopped rather than re-reading from the beginning.
4. **Given** a source that has already contributed records, **When** it is removed from the configuration
   entirely, **Then** the user is told the store still holds its records, and those records are neither
   deleted nor silently orphaned.
5. **Given** two sources declared with the same name, **When** validation runs, **Then** the conflict is
   reported and no source is treated as ready.
6. **Given** a source whose name is changed, **When** validation runs, **Then** the user is told plainly
   that the renamed source will be treated as new and will be read from the beginning.

---

### User Story 3 - Secrets are named, never pasted (Priority: P1)

The user configures a mail account and a calendar. The configuration file records which account and which
credential to use — never the credential itself. The file is safe to read over someone's shoulder, safe to
diff, and safe to keep in a private dotfiles repository. If a credential is missing or expired, the tool
says which source needs which credential and how to supply it, without ever printing the secret.

**Why this priority**: Every remote source in the initial set — Outlook, Gmail, Hey, Google Calendar —
needs a credential. Getting this wrong once leaks a mail account, and it is the kind of mistake that is
made on the first day and discovered on the worst one. It is P1 because it must be true before the first
remote source is ever configured, not retrofitted afterwards.

**Independent Test**: Configure sources that require credentials, confirm validation reports exactly which
credentials are missing; supply them out-of-band; confirm the sources become ready; then search the
configuration file, all command output, all logs, and the store for the secret values and confirm none
appears.

**Acceptance Scenarios**:

1. **Given** a source needing a credential, **When** the credential has not been supplied, **Then**
   validation reports that source as not ready, names the credential it needs, and states how to supply
   it.
2. **Given** a configured credential, **When** any command runs, **Then** the credential value does not
   appear in command output, diagnostics, logs, or the store.
3. **Given** a configuration file containing what appears to be an inline secret, **When** validation
   runs, **Then** the user is warned that secrets do not belong in this file and told where to put it.
4. **Given** a credential the source has revoked or expired, **When** the source is next read, **Then**
   the failure is reported as a credential problem naming the source, distinct from a network or source
   outage, and no other source's ingestion is aborted.
5. **Given** a configuration file readable by other accounts on the machine, **When** validation runs,
   **Then** the user is warned about its permissions.

---

### User Story 4 - A kind of source that does not exist yet (Priority: P2)

A kind of source the tool did not previously support — a time-tracking export, a chat archive, an issue
tracker — arrives in a later release. From the user's side nothing about the tool changes: the new kind
declares what settings it accepts, and from then on it is configured, validated, listed, enabled, and
ingested through exactly the same file and the same commands as everything else. The user does not learn
a second way of doing things, their existing configuration keeps validating untouched, and no existing
source kind had to be modified to make room for the new one.

**Why this priority**: The user asked for extensibility explicitly, and the intended source list in the
constitution is longer than the three starting kinds. It is P2 rather than P1 because the first kinds can
be delivered against a fixed set and the extension point proven immediately afterwards — but the shape of
the configuration file must accommodate it from the start, or the first added kind forces a breaking
change to everyone's file.

**Independent Test**: Add a fixture source kind that no other part of the product knows about, configure
an instance of it, and confirm it validates, lists, enables, disables, and ingests through the same
commands as a shipped kind — with no change to any existing kind and no change to any existing
configuration file.

**Acceptance Scenarios**:

1. **Given** a newly added source kind, **When** the user asks which kinds exist, **Then** it is listed
   alongside the others, with the settings it accepts and which of them are required.
2. **Given** a configured instance of a newly added kind, **When** validation runs, **Then** it is
   validated against that kind's own declared settings and reported like any other source.
3. **Given** a configuration naming a kind the tool does not know, **When** validation runs, **Then** the
   user is told which kind is unrecognised and which kinds are available, and the remaining sources are
   still validated and reported.
4. **Given** a release that adds a new source kind, **When** an existing user upgrades, **Then** their
   existing configuration file continues to validate unchanged.
5. **Given** a source kind offered from outside the tool's own distribution, **When** the tool starts,
   **Then** it is not loaded and not listed as available.

---

### Edge Cases

- No configuration file exists; or it exists but is empty; or it declares no sources at all.
- The configuration file is not readable, or is readable by other accounts on the machine.
- The file is syntactically invalid, or is valid but has a setting of the wrong shape.
- Two sources share a name; or a name changes between runs; or a name contains characters the store
  cannot use as an identifier.
- A source names a kind the tool does not recognise, or a kind that was available last week and is not
  now.
- A local path does not exist, is not readable, is not of the expected kind, or is on a volume that is
  not mounted.
- A pattern matching local repositories matches nothing, or matches thousands, or matches nested
  repositories, or matches the same repository twice by two different paths.
- A repository is a bare clone, a shallow clone, a submodule, or has no commits at all.
- Two configured sources resolve to the same underlying account or the same underlying repository.
- A credential is absent, malformed, expired, revoked mid-run, or grants narrower access than the source
  needs.
- A remote source is unreachable, rate-limits the tool, or is reachable but refuses authorization.
- The configuration changes between two ingestion runs in a way that alters what a source covers — a
  widened folder list, an earlier starting point.
- The same person appears with several addresses across mail and calendar, or the same address is written
  with different capitalisation.
- Sources report times in different time zones from each other and from the machine.
- One source fails while others succeed during a run over all sources.

## Requirements *(mandatory)*

### Functional Requirements

**Configuration file**

- **FR-001**: System MUST read the set of configured sources from a single human-editable text file, and
  MUST NOT require any other step to make a source known to the tool.
- **FR-002**: System MUST look for that file at one documented default location, MUST report that exact
  path when the file is absent, and MUST NOT **modify, rewrite, reformat, or reorder** a file the user has
  written.
  > **Amended by `0005`.** This requirement originally also forbade *creating* the file. It was narrowed so
  > that `ikwyd init` may create one where none exists — which destroys nothing — while everything it was
  > actually protecting stays absolute: a file the user wrote must come back exactly as they left it. There
  > is no flag that overwrites. See
  > [`0005`'s amendments contract](../0005-config-bootstrap/contracts/amendments.md), which also records
  > the three things that would make this narrowing wrong.
- **FR-003**: Users MUST be able to point the tool at a different configuration file, so that alternative
  configurations can be kept side by side.
- **FR-004**: System MUST treat a configuration it cannot parse as fatal for the run: it MUST report the
  failure with the location in the file, and MUST NOT operate on a partially understood configuration.
- **FR-005**: System MUST accept a configuration that declares no sources, and MUST report an empty source
  list rather than an error.
- **FR-006**: System MUST warn when the configuration file is readable by accounts other than its owner.

**Source identity and lifecycle**

- **FR-007**: Each configured source MUST carry a user-assigned name that is unique within the
  configuration; System MUST reject a configuration containing duplicate names.
- **FR-008**: System MUST use that name as the source's stable identity in the store, so that records,
  resumption points, and ingestion history stay associated with it across runs.
- **FR-009**: Each configured source MUST be individually enabled or disabled; a disabled source MUST be
  skipped by ingestion while its already-stored records remain present and queryable.
- **FR-010**: Re-enabling a previously disabled source MUST resume from its stored resumption point rather
  than re-reading from the beginning.
- **FR-011**: Adding, changing, disabling, or removing one source MUST NOT alter any other source's stored
  records, resumption point, or ingestion history.
- **FR-012**: When a source present in the store is no longer present in the configuration, System MUST
  report its stored records as belonging to an unconfigured source, and MUST NOT delete them.
- **FR-013**: When a source's name changes, System MUST tell the user that the renamed source will be
  treated as a new source and will be read from the beginning.

**Validation and diagnostics**

- **FR-014**: Users MUST be able to validate the configuration without reading from any source and without
  writing to the store.
- **FR-015**: Validation MUST report, per source, its name, its kind, whether it is enabled, and either
  that it is ready or a specific reason it is not.
- **FR-016**: Validation MUST report every problem it finds in one run rather than stopping at the first,
  and MUST locate each problem by source name and by setting.
- **FR-017**: Validation MUST distinguish problems that prevent a source from being read from warnings
  that do not.
- **FR-018**: Users MUST be able to check the readiness of a single named source, including a check that
  actually contacts the source, separately from the offline validation in FR-014.
- **FR-019**: Every command that emits configuration or source data MUST offer a `--json` form and MUST
  exit non-zero when validation fails.

**Credentials**

- **FR-020**: The configuration file MUST identify a credential by reference only; System MUST NOT require
  a secret value to be written into it.
- **FR-021**: System MUST report, per source, which credential it needs and whether that credential is
  present, without revealing the credential's value.
- **FR-022**: System MUST NOT print, log, or store a credential value, and MUST redact anything it
  recognises as one from all output.
- **FR-023**: System MUST warn when the configuration file appears to contain an inline secret.
- **FR-024**: System MUST report a credential failure distinctly from a network or source failure, and
  MUST name the source it belongs to.
- **FR-025**: Each source kind MUST declare the access it requires, and that declaration MUST be visible
  to the user before they grant anything.

**Extensibility**

- **FR-026**: System MUST support source kinds beyond the built-in set, such that a new kind is
  configured, validated, listed, enabled, disabled, and ingested through the same file and the same
  commands as a built-in one.
- **FR-027**: Each source kind MUST declare the settings it accepts, which are required, and what each
  means; System MUST validate every configured source against its own kind's declaration.
- **FR-028**: Users MUST be able to list the available source kinds and each kind's accepted settings.
- **FR-029**: A configuration naming an unrecognised kind MUST be reported by name, alongside the kinds
  that are available, without preventing the remaining sources from being validated and reported.
- **FR-030**: Adding a new source kind MUST NOT require a change to any existing configuration file.
- **FR-031**: System MUST recognise only source kinds shipped inside this project, and MUST NOT load a
  source kind from anywhere else on the machine.
- **FR-032**: The kind declaration required by FR-027 MUST nonetheless be specified as though it were a
  public boundary — complete enough that a kind supplied from outside the project would need nothing
  further — so that FR-031 can be relaxed later without changing any existing configuration file.

**What this feature delivers, and what it defers**

- **FR-033**: This feature MUST deliver the configuration contract only. The reading behaviour of the
  three initial kinds — what each one reads, the access it needs, how it handles the source's own
  failure modes, and how it normalises what it finds — MUST be specified and delivered per source kind,
  each in its own later feature.
- **FR-034**: This feature MUST prove the contract end to end using at least one source kind that reads
  from recorded fixture data rather than any real source, so that every requirement here is demonstrable
  before the first real connector exists.

**The initial source kinds**

- **FR-035**: The configuration MUST be able to express a local git repository source: which repositories
  are in scope, both individually and by a pattern over a containing folder, and which committer or
  author identities count as the user's own.
- **FR-036**: The configuration MUST be able to express a mail source for Outlook, Gmail, and Hey
  accounts: which account, which folders or labels are in and out of scope, and which addresses belong to
  the user.
- **FR-037**: The configuration MUST be able to express a calendar source for Outlook and Google Calendar:
  which account, and which of that account's calendars are in scope.
- **FR-038**: Every source kind MUST be able to declare the earliest point in time it should read from, so
  that a first ingestion has a bounded starting point.
- **FR-039**: The settings in FR-035 through FR-038 MUST be expressible, validatable, and reportable
  through the same mechanism as any other kind's settings — this feature MUST NOT special-case them.

**Boundary with attribution**

- **FR-040**: The configuration MUST let the user declare which identities are their own — git author and
  committer identities, mail addresses — because a source cannot distinguish what the user did from what
  was done to them without it.
- **FR-041**: The configuration MUST NOT carry any mapping of people, addresses, repositories, or
  calendars to projects. That mapping belongs to a later attribution feature, and System MUST reject a
  configuration that attempts to declare it here rather than silently ignoring it.

**Running against many sources**

- **FR-042**: Users MUST be able to run an ingestion across all enabled sources, or against one named
  source.
- **FR-043**: A failure in one source MUST NOT abort the others; System MUST complete the remaining
  sources and MUST report a per-source outcome at the end.
- **FR-044**: System MUST exit non-zero when any source in a multi-source run failed, and MUST make the
  failing sources identifiable in both human and `--json` output.
- **FR-045**: System MUST NOT contact any destination that is not a configured source, and MUST be able to
  name, per source, the destination it will contact before it contacts it.

### Key Entities

- **Source Configuration**: The single file describing every source the user has told the tool about.
  Human-authored, never rewritten by the tool, holds no secret values.
- **Configured Source**: One declared origin of activity records. Carries a unique user-assigned name, the
  kind it is, whether it is enabled, its kind-specific settings, an optional credential reference, and an
  earliest-point-to-read-from. Its name is its identity in the store.
- **Source Kind**: A category of source — local git repository, mail account, calendar account, and later
  additions. Declares the settings it accepts, which are required, the access it needs, and the
  destination it contacts. The unit of extension: a new kind is a new specification inside this project,
  never configuration and never code loaded from elsewhere.
- **Credential Reference**: A name pointing at a secret held outside the configuration file. Carries no
  secret value itself; resolvable to present or absent without revealing what it resolves to.
- **Validation Finding**: One problem or warning discovered in the configuration. Carries the source it
  concerns, the setting at fault, its location in the file, a plain statement of what is wrong, and
  whether it blocks reading.
- **Source Run Outcome**: The per-source result of an ingestion across many sources. Carries the source,
  whether it succeeded, and if not, the category of failure — configuration, credential, source
  unreachable, or source error.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user who has never used the tool can go from nothing to a validated configuration naming
  their git repositories, one mail account, and one calendar by editing one file and running one command.
- **SC-002**: Validating a configuration of 20 sources completes in under 5 seconds and contacts zero
  sources.
- **SC-003**: Every rejected configuration is rejected with the offending source named and the offending
  setting named — no finding says only that the configuration is invalid.
- **SC-004**: A single validation run reports 100% of the faults present, not just the first.
- **SC-005**: Adding, disabling, or removing one source leaves every other source's stored record count
  and resumption point unchanged, verified across all three operations.
- **SC-006**: Disabling a source and re-enabling it later causes zero records to be re-read that were
  already read.
- **SC-007**: No credential value appears anywhere in command output, diagnostics, logs, the store, or the
  configuration file, verified by searching all of them for known test secrets.
- **SC-008**: A source kind that no other part of the product knows about can be configured, validated,
  listed, enabled, and ingested with zero changes to any existing kind and zero changes to an existing
  configuration file.
- **SC-009**: In a run across sources where one fails, 100% of the healthy sources still complete, the
  command exits non-zero, and the failing source is identifiable by name and failure category.
- **SC-010**: The set of destinations the tool will contact can be listed from the configuration before
  any source is read, and matches exactly what is contacted during a run.
- **SC-011**: A user upgrading to a version that adds a new source kind has their existing configuration
  file validate unchanged.
- **SC-012**: Every requirement in this specification is demonstrable against fixture data alone — no
  test touches a real git repository, mail account, or calendar account.

## Assumptions

- One person, one machine, one configuration file. Shared, team, or centrally managed configurations are
  not addressed.
- The configuration file is authored by hand in a text editor. Commands that rewrite it on the user's
  behalf are out of scope; the tool reads and validates, the user edits. A commented example file
  containing placeholders only may be shipped for the user to copy.
- The file format is assumed to be YAML, per the user's stated preference, on the grounds that it is
  comment-friendly and diff-friendly for a file people edit by hand. The final choice, with alternatives
  considered, belongs in this feature's `plan.md`; nothing in this specification depends on it.
- Credentials are held outside the configuration file, in the operating system's keyring or a
  user-only-readable local file, per the constitution. Which of the two, and how each source's
  authorization flow is driven, is a `plan.md` decision.
- Source names are chosen by the user rather than derived, because a derived name would change when a path
  or an account changes and would silently orphan stored records.
- A first ingestion needs a bounded starting point (FR-038); without one the tool would attempt to read a
  user's entire mail history on first run.
- Source kinds are added by writing a new specification and a new module inside this project (FR-031).
  "Extensible" here means the contract is open to extension, not that the installation is — the tool holds
  mail and calendar credentials, so third-party code loaded at run time is a trust decision this feature
  declines to make. FR-032 keeps that decision reversible without a configuration-file break.
- The three initial kinds are specified here only as far as what the configuration must be able to express
  (FR-035 to FR-037). Each one's reading behaviour is its own feature, expected as `0003` (git), `0004`
  (mail) and `0005` (calendar) — per the constitution's rule that adding a source is a new spec and that
  each connector's `plan.md` documents the exact endpoints or paths it reads, the credential scopes it
  needs, and how long it retains raw data. This feature is therefore exercised entirely against a fixture
  source kind (FR-034).
- Declaring which identities are the user's own (FR-040) is source configuration, not attribution: without
  it a connector cannot tell a commit the user authored from one they merely have in their history, or a
  mail they sent from one they received. Deciding what those identities *mean* for a project is attribution
  and stays out (FR-041).
- This feature depends on the local store from `specs/0001-local-store-foundation` for source identity,
  resumption points, and ingestion history. It does not depend on how that feature's two open questions
  are resolved.
- Per the constitution, ingestion connects only to sources the user configured, only to read, and reveals
  the destination before contacting it (FR-041).
- Where this feature must choose between silently ignoring part of a configuration and refusing to run, it
  refuses to run — a source the user believes is configured but that is quietly skipped produces a gap in
  a timesheet that nobody checks.

## Out of Scope

- The local store itself — schema, migrations, record shape. That is `specs/0001-local-store-foundation`.
- The git, mail, and calendar connectors themselves — what each reads from its source, the authorization
  flow it drives, and how it normalises what it finds. Each is its own specification (FR-033). This
  feature defines only what the configuration must be able to say about them.
- Any mapping of people, addresses, repositories, or calendars to projects, the rules that attribute
  activity to projects, and the interface for correcting them. This feature supplies configured sources
  and the user's own identities; it carries no project mapping and rejects one if declared (FR-041).
- Loading source kinds from outside the project's own distribution (FR-031). The contract is shaped so
  this can be revisited later (FR-032), but nothing here enables it.
- Scheduling — running ingestion automatically, in the background, or on a timer. This feature covers
  running it on demand across configured sources.
- The local dashboard, and any way of editing the configuration other than a text editor.
- Deduplicating the same real-world event seen through two configured sources.
- Browser history and SharePoint sources named in the constitution; each is its own specification.
- Migrating or versioning the configuration file format across releases, beyond the compatibility promise
  in FR-030.
