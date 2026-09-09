# Feature Specification: Local Store Foundation

**Feature Directory**: `specs/0001-local-store-foundation`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Local store foundation — the embedded database, normalized raw-record schema, migrations, and the common shape every source's data is mapped into. Establishes the storage decisions that every later connector and view depends on."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A durable place for a day's traces (Priority: P1)

Someone starts using the tool. Before any source is connected, the tool needs somewhere to put what it
finds. On first use it establishes a private store on their machine, tells them where it lives, and from
then on accepts normalized activity records — a meeting, a commit, a page visit — from any source, and
hands them back on request, filtered by time and by source. None of this requires a network connection.

**Why this priority**: Nothing else in the product can exist first. Every connector writes here, every
view reads from here, and the shape chosen here constrains both. Delivered alone it is already useful:
records can be put in and got back out, which is the smallest thing that proves the design.

**Independent Test**: Load a fixture batch of normalized records from several notional sources into a
fresh store, disconnect the network, then query by day and by source and confirm every record comes back
with its evidence intact.

**Acceptance Scenarios**:

1. **Given** a machine where the tool has never run, **When** the user runs any store command, **Then**
   a store is created in the tool's own data directory and the user is told its location.
2. **Given** a store holding records from several sources, **When** the user asks what it contains,
   **Then** they see per-source record counts, the earliest and latest record, and when each source was
   last ingested.
3. **Given** a populated store and no network connection, **When** the user queries a date range,
   **Then** every matching record is returned with no error and no attempt to reach any source.
4. **Given** a stored record, **When** the user inspects it, **Then** they can see which source it came
   from, that source's own identifier for it, when it happened, and the unmodified payload it was
   derived from.

---

### User Story 2 - Change the guesses without re-downloading the year (Priority: P2)

The rules that map activity to projects are going to be wrong at first and will keep changing. When the
user revises them, the tool re-derives every attribution from records it already holds. It never goes
back to mail, calendar, or SharePoint to do it, and it never reaches for the network.

**Why this priority**: This is the property that makes iteration on attribution affordable. Without it,
every heuristic change costs a full re-ingestion and the user stops changing heuristics.

**Independent Test**: Populate a store from fixtures, discard everything derived, re-derive with the
network disconnected and every source path made unreadable, and confirm the derived layer is rebuilt
identically.

**Acceptance Scenarios**:

1. **Given** a store with raw records and derived attributions, **When** the derived data is discarded,
   **Then** the raw records are untouched and still queryable.
2. **Given** raw records and no access to any source, **When** derivation is re-run, **Then** it
   completes without reading from any source.
3. **Given** the same raw records and the same rules, **When** derivation is run twice, **Then** both
   runs produce the same result.

---

### User Story 3 - Corrections are never lost (Priority: P2)

The user overrides an attribution the tool got wrong. That correction is theirs, not the tool's — it must
outlive a re-analysis, a schema upgrade, and deleting the whole store and re-ingesting from scratch.

**Why this priority**: Corrections are the only data in the store that cannot be regenerated. Losing one
is unrecoverable, and a tool that loses them stops being trusted for timesheets. It is P2 only because
the machinery that creates corrections arrives in a later feature; this feature guarantees the durable
place they live and the paths they survive.

**Independent Test**: Record corrections against a fixture store, delete the store, re-ingest the same
fixtures, and confirm every correction is present and re-applied to the matching records.

**Acceptance Scenarios**:

1. **Given** stored corrections, **When** derived data is discarded and re-derived, **Then** every
   correction is still present and still takes precedence over what was inferred.
2. **Given** stored corrections, **When** the store is deleted and rebuilt from the same sources,
   **Then** every correction is re-applied to the record it was made against.
3. **Given** a store with corrections, **When** the user exports them, **Then** they get a portable file
   they can import into another store on another machine.
4. **Given** an imported correction whose record is not present in this store, **When** the import runs,
   **Then** the correction is retained and reported as pending rather than discarded.

---

### User Story 4 - Upgrading does not cost the archive (Priority: P3)

Months of records have accumulated. A new version of the tool changes how records are structured. The
user upgrades and keeps everything — the store is migrated in place, and if the migration cannot finish,
the store is left exactly as it was rather than half-converted.

**Why this priority**: It only bites after real data has accumulated, but the versioning must be designed
in from the first release or the first upgrade has nothing to migrate from.

**Independent Test**: Build a store at an older structure version with records and corrections, run the
current tool against it, and confirm counts are unchanged and the version has advanced; then repeat with
a deliberately failing migration and confirm the store is unchanged and still usable.

**Acceptance Scenarios**:

1. **Given** a populated store at an older structure version, **When** the tool runs, **Then** it is
   migrated without user intervention and every record and correction survives.
2. **Given** a migration that fails partway, **When** the failure occurs, **Then** the store is left at
   its previous version, fully usable, and the user is told what failed.
3. **Given** a store written by a newer version of the tool than the one running, **When** any command
   runs, **Then** it refuses to proceed, says so plainly, and changes nothing.

---

### Edge Cases

- The tool's data directory does not exist, or exists but cannot be written to.
- A second command is started while another already holds the store.
- An ingestion is interrupted — process killed, machine sleeps, disk fills — partway through a batch.
- The same source data is ingested twice, in whole or with an overlapping time range.
- A source hands over a record with no stable identifier of its own.
- Two sources describe the same underlying event (a calendar entry and the mail that scheduled it).
- Records arrive with timestamps in a different time zone than the machine's, or inside a
  daylight-saving transition.
- The store file is truncated, corrupted, or is not a store file at all.
- The store is placed on a removable or network volume that disappears mid-run.
- A correction is imported for a record that does not exist in this store.
- A source's clock is wrong, producing records dated in the future.

## Requirements *(mandatory)*

### Functional Requirements

**Store lifecycle and visibility**

- **FR-001**: System MUST keep all ingested records, derived data, and corrections in a single local
  store inside the tool's own data directory, and MUST NOT write feature data anywhere outside it.
- **FR-002**: System MUST create the store on first use, with no manual setup step required of the user.
- **FR-003**: Users MUST be able to see, from the command line and with a `--json` form, the store's
  location, its structure version, and per-source record counts, time span, and last ingestion time.
- **FR-004**: Users MUST be able to override the store's location through configuration, so it can be
  placed on a volume of their choosing.
- **FR-005**: The store MUST be created with access restricted to the account that owns it.

**Record shape**

- **FR-006**: System MUST store every ingested record in one normalized shape shared by all sources,
  capturing at minimum the originating source, that source's own identifier for the record, the point or
  span of time it covers, a human-readable title, and the unmodified payload it was derived from.
- **FR-007**: System MUST store times such that both the original instant and the time zone it was
  expressed in are recoverable.
- **FR-008**: System MUST record, for every stored record, which ingestion run produced it and when.
- **FR-009**: System MUST accept records from a source that supplies no stable identifier of its own, and
  MUST derive a stable identifier for them from their content so that FR-011 still holds.

**Separation of raw, derived, and corrected**

- **FR-010**: System MUST hold ingested records, derived attributions and summaries, and user
  corrections in three separately addressable regions, such that any one can be discarded without
  altering the others.

**Ingestion integrity**

- **FR-011**: Ingesting source data that is already stored MUST NOT create duplicate records, whether the
  repeat is a full re-run or an overlapping range.
- **FR-012**: System MUST persist, per source, a resumption point that lets a later ingestion read only
  what is new.
- **FR-013**: An interrupted ingestion MUST leave the store consistent — a batch is either fully applied
  or not applied at all — and MUST be resumable without duplicating or skipping records.
- **FR-014**: When a source presents a record the store already holds but with changed content, the
  system MUST store the new version and keep the record identifiable as the same one.

**Rebuild and durability**

- **FR-015**: Re-deriving attributions from records already held MUST NOT read from any configured
  source.
- **FR-016**: Deleting the store and re-ingesting MUST reproduce an equivalent set of records, and the
  system MUST report every record that could not be reproduced because the source no longer exposes it.
- **FR-017**: User corrections MUST survive re-derivation, a structure migration, and a full
  delete-and-rebuild of the store.
- **FR-018**: Users MUST be able to export corrections to a portable file and import them into a store
  from the command line; an imported correction with no matching record MUST be retained and reported as
  pending rather than dropped.
- **FR-019**: Every stored derived attribution MUST be distinguishable from a user-confirmed one, and
  MUST carry the evidence and the rule that produced it.

**Versioning and migration**

- **FR-020**: The store MUST record the structure version it is at, and every change to that structure
  MUST ship with a versioned migration that upgrades an existing store in place.
- **FR-021**: A migration that cannot complete MUST leave the store at its previous version, fully
  usable, and MUST tell the user what failed.
- **FR-022**: System MUST refuse to operate on a store written by a version newer than the one running,
  MUST say so plainly, and MUST change nothing.

**Safety**

- **FR-023**: No store operation may contact any network destination.
- **FR-024**: System MUST NOT write credentials or other secrets into the store.
- **FR-025**: Concurrent use of the store MUST either wait for the holder or fail with a clear message;
  it MUST NOT corrupt the store or return partial results.
- **FR-026**: A store that cannot be read MUST be reported with its path and a stated recovery step, and
  the system MUST NOT delete or overwrite it on its own initiative.
- **FR-027**: When an incremental ingestion finds that a record it previously stored is no longer present
  at the source, the system MUST [NEEDS CLARIFICATION: retain the record and mark it withdrawn, or delete
  it to mirror the source?]
- **FR-028**: The store MUST protect ingested data at rest by [NEEDS CLARIFICATION: relying on the
  operating system's disk encryption and file permissions, or encrypting the store itself with a
  user-held secret?]

### Key Entities

- **Source**: A configured origin of activity records — mail, calendar, git, browser history, SharePoint.
  Identified by a stable name, carries its own resumption point and ingestion history.
- **Activity Record**: One normalized trace of something that happened. Carries the source it came from,
  that source's identifier for it, when it happened and in which time zone, a title, its unmodified
  source payload, and the ingestion run that produced it. Regenerable from the source.
- **Ingestion Run**: One execution of a read against one source. Carries when it ran, what range it
  covered, how many records it produced, and whether it completed.
- **Derived Attribution**: A mapping of an activity record to a project, produced by a rule. Carries the
  evidence it rests on, the rule that produced it, and its status as inferred. Fully regenerable from
  activity records; this feature stores it, later features produce it.
- **User Correction**: A user's authoritative statement about an activity record, overriding whatever was
  inferred. Not regenerable from any source; the only irreplaceable data in the store.
- **Store Version**: The structure version the store is at, and the ordered migrations that move it
  between versions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the network disconnected, 100% of previously ingested records remain queryable, and no
  command attempts to reach a source.
- **SC-002**: Re-deriving attributions over a full year of ingested records requires zero reads from any
  configured source.
- **SC-003**: Deleting the store and re-ingesting the same sources reproduces every record that the
  sources still expose; any record that cannot be reproduced appears by name in a rebuild report rather
  than disappearing silently.
- **SC-004**: 100% of user corrections made before a re-derivation, a migration, or a full rebuild are
  present and applied afterwards, across all three paths.
- **SC-005**: Ingesting the same source data a second time leaves the record count unchanged.
- **SC-006**: Upgrading a store holding a year of records completes without user intervention, and record
  and correction counts before and after are identical.
- **SC-007**: A failed migration leaves the store openable and its record count unchanged.
- **SC-008**: A user can see where the store is and what it holds in one step, in under 5 seconds on a
  store of a year's records.
- **SC-009**: Every stored record can be traced back to the source, the source-side identifier, and the
  ingestion run it came from — with no unattributed records in the store.
- **SC-010**: Interrupting an ingestion at any point leaves a store that opens cleanly and whose record
  count matches a whole number of completed batches.

## Assumptions

- One person, one machine, one store. Multi-user access, shared or server-hosted stores, and syncing a
  store between machines are not addressed; correction export and import (FR-018) is the only path
  between machines.
- Ingested records are retained indefinitely. Age-based pruning and per-source retention limits are a
  later feature; this feature only ensures nothing is deleted without the user asking.
- The store lives in the operating system's conventional per-user application data location unless the
  user overrides it (FR-004).
- Commands are run one at a time by one person; concurrency support means failing safely rather than
  supporting parallel writers (FR-025).
- No connector exists yet. This feature is exercised against fixture batches of normalized records
  standing in for real sources, per the constitution's rule that connector and attribution logic be
  tested against recorded fixtures.
- The record shape defined here is expected to be extended as real sources arrive; that is what the
  migration requirement (FR-020) exists to absorb.
- Timesheet-grade accuracy means a record's absence must be visible. Where this feature must choose
  between silently dropping data and reporting a gap, it reports the gap.

## Out of Scope

- Any connector to a real source — mail, calendar, git, browser history, SharePoint. Each is its own
  spec.
- The rules that attribute activity to projects, and the user interface for correcting them. This feature
  provides the place they are stored, not the logic.
- The local dashboard.
- Exporting a timesheet or any reporting format other than the correction export in FR-018.
- Deduplicating the same real-world event observed through two different sources. The store keeps both;
  reconciling them is an attribution concern.
- Pruning, archiving, or age-based deletion of ingested records.
