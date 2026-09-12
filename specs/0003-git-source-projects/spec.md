# Feature Specification: Git Source and Projects

**Feature Directory**: `specs/0003-git-source-projects`

**Created**: 2026-09-10

**Status**: Draft

**Input**: User description: "Add a new git source that reads commits, branches and merged from local git repositories. The folders that are scanned for git repositories should be configuratable in the config file (including globs) so that several places are analyzed for git repositories and the time spent is recorded. There should be some kind of mapping between projects and git repositiroes, I'm not sure if there is already a "project" entity, but this needs to be added, since all time should be recorded on a project. If the mapping is missing, then the repository name should be used an an ad-hoc project. Later on this mapping might change and the recorded data should be updated."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See which repositories I worked on, and when (Priority: P1)

Someone points the tool at the folders where their repositories live — a couple of parent directories and a
pattern for the rest — and asks what they did last week. It comes back with the repositories they touched,
the commits they made, the branches they created, and the merges they landed, day by day. Nothing was
fetched, nothing in any repository was changed, and no network connection was opened.

**Why this priority**: This is the first source that reads anything real. Until it exists the store has
only fixture data, and the whole tool is a promise. Delivered alone it already answers "which projects was
I in this week?" from evidence rather than memory.

**Independent Test**: Build fixture repositories on disk with known commit histories, point a configured
source at them, ingest, and confirm every commit, branch and merge comes back attributed to the right
repository and day — then verify the repositories' contents and refs are byte-identical afterwards.

**Acceptance Scenarios**:

1. **Given** a folder containing several repositories, **When** the user configures it and ingests,
   **Then** every repository is discovered and its activity recorded, and the user is told how many
   repositories were found.
2. **Given** a repository with commits by several people, **When** ingestion runs, **Then** only commits
   matching the user's declared identities are recorded as their own work, and the rest are not.
3. **Given** any ingestion, **When** it completes, **Then** no repository has been modified — no fetch, no
   checkout, no new refs, no changed working tree.
4. **Given** a query for a day, **When** the user asks what happened, **Then** they see the repositories
   touched and the commits, branches and merges within them, with times.
5. **Given** a repository that cannot be read, **When** ingestion runs, **Then** it is reported by path and
   the remaining repositories are still ingested.

---

### User Story 2 - Everything lands on a project (Priority: P1)

The user's time has to be attributed to something a timesheet can name. Each repository belongs to a
project. Where the user has said which, that mapping is used; where they have not, the repository's own
name becomes the project so that nothing is left unattributed. The user can always see which of the two
happened, so an assumption is never mistaken for a decision.

**Why this priority**: The user's stated requirement is that *all* time is recorded on a project. Without
this, the git source produces activity nobody can bill. It is P1 with US1 because a commit with no project
is not yet useful for the purpose this tool exists for.

**Independent Test**: Ingest repositories where some are mapped to projects and some are not, then confirm
every recorded activity carries a project, that mapped repositories use the mapped project, that unmapped
ones use their repository name, and that the two are distinguishable in every view.

**Acceptance Scenarios**:

1. **Given** a repository mapped to a project, **When** its activity is ingested, **Then** that activity is
   attributed to the mapped project.
2. **Given** a repository with no mapping, **When** its activity is ingested, **Then** it is attributed to
   a project named after the repository, and that project is marked as having been created ad hoc.
3. **Given** a mix of both, **When** the user lists projects, **Then** they can see which projects they
   declared and which the tool invented.
4. **Given** any recorded activity, **When** the user inspects it, **Then** it names a project and the
   reason that project was chosen.
5. **Given** two repositories mapped to the same project, **When** activity from both is ingested,
   **Then** both contribute to that one project.

---

### User Story 3 - Change the mapping without re-reading the year (Priority: P2)

Months in, the user realises two repositories belong to the same client, or that an ad-hoc project should
have been part of a bigger one. They change the mapping, and the already-recorded activity is re-attributed
— without going back to any repository, and without losing any correction they made by hand.

**Why this priority**: The user asked for it explicitly, and it is the property that makes the mapping safe
to get wrong at first. It is P2 because the mapping has to exist before it can be changed.

**Independent Test**: Ingest with one mapping, record a hand correction, change the mapping, re-derive with
every repository made unreadable and the network down, and confirm the new attribution is applied
everywhere while the correction still wins.

**Acceptance Scenarios**:

1. **Given** activity attributed under an old mapping, **When** the mapping changes and attributions are
   re-derived, **Then** every affected activity carries the new project.
2. **Given** a re-derivation, **When** it runs, **Then** no repository is read and no network connection is
   opened.
3. **Given** a user correction on an activity, **When** the mapping changes, **Then** the correction still
   takes precedence over the new mapping.
4. **Given** an ad-hoc project that is later mapped explicitly, **When** attributions are re-derived,
   **Then** the activity moves to the declared project and the ad-hoc project no longer holds it.
5. **Given** a mapping change, **When** the user asks what would change before applying it, **Then** they
   are shown how many activities would move and between which projects.

---

### User Story 4 - Discovery is predictable and never surprising (Priority: P2)

The user writes a pattern rather than listing every repository. They need to know exactly what it matched
before a year of history is read — including the repositories they did not expect it to find, and the ones
they expected and it missed.

**Why this priority**: A pattern that quietly matches a thousand repositories, or quietly matches none, is
how this feature becomes untrustworthy. It is P2 because US1 works with explicit paths; patterns are what
make it usable at scale.

**Independent Test**: Point patterns at a tree containing nested repositories, a bare clone, a submodule, a
folder that merely looks like a repository, and the same repository reachable by two paths; confirm the
reported discovery matches expectation exactly and that each repository is recorded once.

**Acceptance Scenarios**:

1. **Given** a configured pattern, **When** the user asks what it matches, **Then** every repository is
   listed by path, without anything being read from them.
2. **Given** a pattern matching nothing, **When** validation runs, **Then** the user is warned rather than
   silently ingesting an empty source.
3. **Given** the same repository reachable by two configured paths, **When** ingestion runs, **Then** its
   activity is recorded once.
4. **Given** a repository nested inside another repository's working tree, **When** discovery runs,
   **Then** the user is told, and each is treated as a separate repository.
5. **Given** a pattern matching an unusually large number of repositories, **When** the user is warned,
   **Then** they can proceed deliberately rather than by accident.

---

### Edge Cases

- A configured folder does not exist, is not readable, or is on a volume that is not mounted.
- A pattern matches nothing; or matches thousands; or matches the same repository by two paths.
- A repository is bare, shallow, a submodule, a worktree of another repository, or has no commits at all.
- A folder contains a `.git` file rather than a directory, or looks like a repository but is not one.
- A repository is being written to during ingestion — a rebase, a checkout, a running merge.
- A commit has no author identity, an identity the user has not declared, or several identities in a trailer.
- Author time and committer time differ — a rebase, a cherry-pick, a patch applied weeks after it was written.
- A commit's timestamp has an offset the machine has never been in, or is in the future.
- Two repositories produce commits with the same identifier — a shared history, or a fork.
- A repository is renamed, moved, or deleted between two ingestions.
- Two different repositories have the same folder name in different parents.
- A repository maps to a project that no longer exists in the mapping.
- Two projects are declared with the same name, or with names differing only in case.
- An ad-hoc project and a declared project end up with the same name.
- A mapping change would move activity that carries a user correction.
- A repository's history is rewritten, so commits previously recorded no longer exist.

## Requirements *(mandatory)*

### Functional Requirements

**Discovery**

- **FR-001**: The configuration MUST accept one or more locations to search for repositories, expressed
  either as a path to a repository or as a pattern over a containing folder.
- **FR-002**: The configuration MUST accept locations to exclude, so that a broad pattern can be narrowed
  without being replaced by an explicit list.
- **FR-003**: Users MUST be able to see exactly which repositories a configuration matches, by path,
  **before** anything is read from them.
- **FR-004**: A configured location that matches no repository MUST be reported as a warning rather than
  silently contributing nothing.
- **FR-005**: The same repository reachable by more than one configured path MUST be recorded once.
- **FR-006**: A repository nested inside another repository's working tree MUST be reported, and each MUST
  be treated as a separate repository.
- **FR-007**: A location that cannot be read MUST be reported by path, and MUST NOT prevent the remaining
  locations from being searched.
- **FR-008**: Discovery MUST NOT follow symbolic links out of the configured locations.
- **FR-009**: Users MUST be warned before a first ingestion of an unexpectedly large number of
  repositories, so that a pattern that matched too much is caught before a year of history is read.

**What is read**

- **FR-010**: System MUST record commits, branch creations, and merges, each with the time it happened and
  the repository it happened in.
- **FR-011**: System MUST record only activity attributable to the identities the user has declared as
  their own, and MUST ignore other contributors' activity.
- **FR-012**: System MUST preserve both the author time and the committer time where they differ, so that
  work done and work landed can be told apart.
- **FR-013**: System MUST store, for every recorded activity, enough evidence to trace it back to the exact
  commit, branch or merge it came from.
- **FR-014**: System MUST NOT record the content of any change — no diffs, no file contents, no per-file
  statistics.
- **FR-015**: System MUST record a commit's subject line, and MUST NOT record the remainder of its message.
  The subject is what makes a day's work recognisable when confirming a timesheet; message bodies are where
  pasted logs, ticket text and customer names accumulate, and they buy nothing for that purpose.
- **FR-016**: System MUST record each activity as a point in time. It MUST NOT store a duration, an effort
  estimate, or any other derived measure of time spent — nothing observes the user working, and a number
  that was inferred rather than observed MUST NOT enter the store as though it were evidence.
- **FR-017**: Stored activity MUST be sufficient for a later feature to derive time spent from these
  records alone — the repository, ordering and timing of every activity — without re-reading any
  repository.

**Reading is never writing**

- **FR-018**: Reading a repository MUST NOT modify it in any way — no fetch, no checkout, no new or moved
  refs, no change to the working tree, no change to any file inside it.
- **FR-019**: System MUST NOT contact any network destination while reading a repository, even where the
  repository has remotes configured.
- **FR-020**: A repository that is being written to during ingestion MUST NOT be corrupted by the read, and
  a read that cannot complete safely MUST be reported and skipped rather than forced.
- **FR-021**: System MUST tolerate a repository that is bare, shallow, a submodule, a worktree, or empty,
  recording what it can and reporting what it cannot.

**Reading exhaustively**

- **FR-022**: Each ingestion MUST state whether it read the repository exhaustively over its window or only
  what was new, so that activity that has genuinely disappeared can be distinguished from activity that was
  simply not looked for.
- **FR-023**: When a repository's history has been rewritten so that previously recorded commits no longer
  exist, an exhaustive read MUST mark those records as withdrawn rather than deleting them.

**Projects**

- **FR-024**: System MUST hold a project as a first-class thing with a stable identity, so that renaming a
  project does not detach the activity already attributed to it.
- **FR-025**: Every recorded activity MUST be attributed to exactly one project.
- **FR-026**: Users MUST be able to list projects, and to see for each one how much activity it holds and
  which repositories contribute to it.
- **FR-027**: Two projects MUST NOT share a name; a declaration that would create a duplicate MUST be
  refused, including names differing only in case.

**Mapping repositories to projects**

- **FR-028**: The repository-to-project mapping MUST live in its own hand-edited file, separate from the
  sources configuration, so that a change to what activity *means* cannot invalidate the configuration
  that says where to read *from*.
- **FR-029**: System MUST NOT **modify, rewrite, reformat, or reorder** that file once the user has
  written it.
  > **Amended by `0005`**, exactly as `0002` FR-002 was: creating a mapping where none exists is permitted
  > to `ikwyd init` and destroys nothing; changing one the user wrote remains forbidden, with no flag that
  > would. See [`0005`'s amendments contract](../0005-config-bootstrap/contracts/amendments.md).
- **FR-030**: An absent mapping file MUST be valid, and MUST result in every repository falling back to its
  own ad-hoc project rather than in an error.
- **FR-031**: The mapping file MUST be validated with the same reporting as the sources configuration —
  every fault reported in one run, each located by the project and entry at fault, and blocking problems
  distinguished from warnings.
- **FR-032**: Users MUST be able to declare which project a repository belongs to.
- **FR-033**: Several repositories MUST be able to map to one project.
- **FR-034**: A repository with no declared mapping MUST be attributed to a project named after the
  repository, created for the purpose.
- **FR-035**: A project created this way MUST be distinguishable from one the user declared, everywhere it
  is displayed, so that an assumption is never mistaken for a decision.
- **FR-036**: Every attribution MUST record which rule produced it — a declared mapping or the fall-back —
  and the evidence it rests on.

**Changing the mapping**

- **FR-037**: Changing the mapping and re-deriving MUST re-attribute already-recorded activity without
  reading any repository and without opening any network connection.
- **FR-038**: A user correction on an activity MUST continue to take precedence over whatever the mapping
  would otherwise produce.
- **FR-039**: When an ad-hoc project's repository is later mapped explicitly, re-derivation MUST move that
  activity to the declared project.
- **FR-040**: An ad-hoc project that no longer holds any activity MUST NOT continue to appear as though it
  did.
- **FR-041**: Users MUST be able to see what a mapping change would do — how many activities would move,
  and between which projects — before applying it.
- **FR-042**: A repository mapped to a project that does not exist MUST be reported rather than silently
  falling back to the ad-hoc name.

**Configuration and reporting**

- **FR-043**: The git source MUST be configurable, validatable, listed, enabled, disabled and ingested
  through exactly the same file and commands as any other source.
- **FR-044**: The source MUST declare that it contacts no network destination, so that its entry in the
  tool's list of destinations reads as local-only.
- **FR-045**: Every command that emits project, repository or mapping data MUST offer a machine-readable
  form and exit non-zero on failure.

### Key Entities

- **Project**: A named thing time is recorded against — the unit a timesheet reports. Carries a stable
  identity independent of its name, whether it was declared by the user or created ad hoc, and when it was
  first seen. New in this feature.
- **Repository**: One local git repository that was discovered. Carries the path it was found at, its own
  identity independent of that path (so a moved repository is still the same one), and the configured
  location that matched it.
- **Repository-Project Mapping**: A user's statement that a repository belongs to a project. Carries the
  repository, the project, and when it was declared. Changing it re-attributes existing activity.
- **Git Activity**: One commit, branch creation, or merge, recorded as an activity record. Carries the
  repository, the commit or ref it came from, author and committer times, and the identity it is attributed
  to.
- **Project Attribution**: The link from an activity to a project, carrying the rule that produced it
  (declared mapping or ad-hoc fall-back) and the evidence. Regenerable, and distinguishable from a user's
  own correction.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from an unconfigured tool to seeing last week's repository activity by editing
  one file and running two commands.
- **SC-002**: 100% of recorded git activity is attributed to a project — no activity is left unattributed.
- **SC-003**: After ingesting a set of fixture repositories, every repository's files and refs are
  byte-identical to before, verified by comparing the whole repository directory.
- **SC-004**: Ingesting a year of history across 20 repositories opens zero network connections.
- **SC-005**: Re-running an ingestion with nothing changed at the source records zero new activities.
- **SC-006**: Changing a mapping and re-deriving re-attributes every affected activity while reading zero
  repositories.
- **SC-007**: 100% of user corrections survive a mapping change and continue to take precedence.
- **SC-008**: A user can see exactly which repositories their configuration matches, and that listing reads
  no commit history.
- **SC-009**: Every project in a listing is identifiable as declared or ad hoc, with no ambiguous cases.
- **SC-010**: A configured location matching no repositories produces a warning that names the location.
- **SC-011**: One unreadable repository never prevents the others from being ingested, and is named in the
  run report.
- **SC-012**: A mapping change can be previewed, and the preview's predicted moves match exactly what
  applying it does.
- **SC-013**: No stored activity carries a duration or effort estimate; every one is a point in time
  traceable to a specific commit, branch or merge.
- **SC-014**: No stored activity carries any part of a commit message beyond its subject line, verified by
  searching the store for body text planted in fixture repositories.

## Assumptions

- The git source is configured through the existing sources configuration file and runs through the
  existing commands; this feature adds a reader for a source kind that is already declared, rather than a
  parallel mechanism.
- Repository discovery is by presence of a git repository at a path, not by folder naming convention.
- This feature records *what happened and when*, not *how long it took*. Git knows when a commit was made
  and never how long the work behind it lasted, so a duration would be an estimate presented as evidence in
  a record that feeds billing. Turning activity into hours is a later summarising feature's job, working
  from these records (FR-016, FR-017).
- The mapping lives beside the sources configuration in its own file. This keeps `0002`'s FR-041 intact
  and unamended: the sources configuration continues to reject a project mapping, because attribution
  rules change often and a bad rule must not be able to break the configuration that says where to read
  from.
- Activity is recorded per repository, and repositories map to projects. Mapping individual commits or
  branches to different projects is not addressed.
- A project is identified separately from its name so that renaming one does not orphan its activity
  (FR-022). Merging or splitting projects is not addressed here.
- Attribution is stored as derived data: it is regenerable from recorded activity plus the current mapping,
  which is what makes FR-032 affordable. User corrections remain the only irreplaceable data.
- Which commits count as the user's own is decided by the identities already declared in the source
  configuration.
- Reading is read-only in the strongest sense: the tool never runs an operation that could take a lock or
  write to a repository, even a maintenance one.
- Where this feature must choose between silently ignoring something and reporting it, it reports it — a
  repository the user believes is being read but is not produces a gap in a timesheet that nobody checks.

## Out of Scope

- Any source other than local git repositories. Mail and calendar are separate features.
- Remote git hosting — pull requests, reviews, issues, CI. Nothing is fetched, and nothing is read from a
  forge's API.
- The content of changes: diffs, file contents, and per-file statistics.
- Attribution rules for any source other than git. This feature introduces the project entity and the
  repository mapping; mapping people, addresses or calendars to projects is not addressed.
- Merging, splitting, archiving or deleting projects.
- Exporting a timesheet, or any reporting format beyond listing projects and their activity.
- The local dashboard.
- Deriving hours, durations or effort from the recorded activity. This feature stores the points in time a
  later summarising feature will work from; it computes nothing from them (FR-016).
- Deciding time spent by observation, screen activity, or any measurement other than what commits record.
- Commit message bodies, and therefore any attribution rule that would depend on reading them (FR-015).
