# Feature Specification: Getting Configured — `init` and `edit`

**Feature Branch**: `0005-config-bootstrap`

**Created**: 2026-09-12

**Status**: Draft

**Input**: User description: "Add commands that help a user get their configuration in place and keep it current. `ikwyd init` should copy the shipped example files (config.toml, projects.toml) into the tool's configuration directory, and must never overwrite a file that already exists — it refuses without writing anything. `ikwyd sources edit` should open the sources configuration in the user's editor, and `ikwyd projects edit` the project mapping. Prefer $VISUAL then $EDITOR, falling back to the operating system's default application for the file. This requires amending FR-002 (0002) and FR-029 (0003), which currently say the tool never creates or edits these files: the purpose of those requirements — that the tool must never modify or reformat what the user wrote — has to survive the change intact."

## Overview

Four features in, the tool reads mail, git repositories and a project mapping. Getting to
that point still requires a user to find `examples/`, work out where their operating
system keeps application configuration, copy the files there by hand, and then locate them
again every time they want to change a rule.

This feature closes that gap with three small commands: one that puts the files where they
belong, and two that open them.

### Why this needs a requirement changed

`0002` FR-002 and `0003` FR-029 both say, in as many words, that the tool **never writes**
these files and that there is **no command that creates, edits, or reformats** them. A test
asserts it across the whole command surface.

That requirement exists for a specific reason, and the reason is still right: a tool that
rewrites a user's configuration can lose their comments, reorder their keys, and change
what the file means without saying so. The file is the user's statement of intent, and it
must come back exactly as they left it.

**Creating a file that does not exist does none of that.** Neither does handing an existing
file to the user's own editor. This feature narrows the requirement from "never write" to
**"never modify, reformat, or reorder anything the user wrote"** — which is what it was
protecting all along — and leaves that protection absolute.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Getting started without a treasure hunt (Priority: P1)

I have just installed the tool. I run one command, and the files I need are where the tool
will look for them, with comments explaining what goes in each. I edit them and start
ingesting.

**Why this priority**: It is the first thing anybody does, and today it is the step most
likely to make someone give up. Everything else in this feature is convenience; this is the
difference between a tool that works and a tool that needs a tutorial.

**Independent Test**: In an empty configuration directory, run the command and verify all
three files appear with the shipped content, that the credentials file is readable by its
owner alone, that the tool then finds them without being told where they are, and that they
validate.

**Acceptance Scenarios**:

1. **Given** no configuration exists, **When** I run the setup command, **Then** the
   configuration, mapping and credentials files are created where the tool looks for them,
   and it says where they went.
2. **Given** the credentials file has just been created, **When** I inspect its permissions,
   **Then** only I can read it.
3. **Given** the files have just been created, **When** I validate, **Then** they pass —
   a template that ships broken is worse than no template.
4. **Given** the files have just been created, **When** I read them, **Then** every value
   needing my attention is an obvious placeholder rather than a plausible-looking default.
5. **Given** the configuration directory does not exist, **When** I run the setup command,
   **Then** it is created, and nothing outside it is touched.

---

### User Story 2 - Never losing what I wrote (Priority: P1)

I already have a configuration I have spent time on. I run the setup command by mistake —
or a second time, months later, wanting the newer example. Nothing I wrote is lost.

**Why this priority**: Equal first with Story 1, and for a stronger reason. Story 1 is
convenience; this is the guarantee that makes the convenience safe to accept. A setup
command that can destroy a year of carefully tuned attribution rules is worse than no setup
command.

**Independent Test**: With an existing configuration and a credentials file holding a known
value, run the setup command and verify both are byte-identical afterwards, that the command
said plainly it did not touch them, and that nothing was written anywhere.

**Acceptance Scenarios**:

1. **Given** a configuration file already exists, **When** I run the setup command, **Then**
   that file is byte-identical afterwards, and the command says it left it alone.
2. **Given** some of the files exist and others do not, **When** I run the setup command,
   **Then** the missing ones are created, the existing ones are untouched, and the output
   says which was which.
3. **Given** all three files already exist, **When** I run the setup command, **Then**
   nothing is written at all, and the command still tells me where the files are.
4. **Given** any outcome, **When** I look for a flag that would overwrite, **Then** there
   is none.
5. **Given** a credentials file holding real secrets, **When** I run the setup command,
   **Then** it is byte-identical afterwards. This is the highest-stakes case of the rule:
   overwriting it destroys something the user cannot recover from a template.

---

### User Story 3 - Opening the file I need to change (Priority: P2)

I want to add a project mapping rule. I run one command and the right file opens in the
editor I already use, rather than my searching for a path I half-remember.

**Why this priority**: Useful rather than essential — the path is printed by several
existing commands, so a user can always find it. It earns its place because editing the
mapping is the loop this whole tool is built around, and that loop should be short.

**Independent Test**: With an editor configured, run each command and verify the correct
file is handed to that editor and that its contents are unchanged when the tool has
finished with it.

**Acceptance Scenarios**:

1. **Given** an editor is configured, **When** I run the edit command for sources, **Then**
   the sources configuration is opened in it.
2. **Given** an editor is configured, **When** I run the edit command for projects, **Then**
   the project mapping is opened in it.
3. **Given** no editor is configured, **When** I run either command, **Then** the file opens
   in whatever the operating system associates with it.
4. **Given** neither an editor nor an association can be found, **When** I run either
   command, **Then** the tool prints the path and says plainly that it could not open it —
   never silently doing nothing.
5. **Given** the file does not exist, **When** I run the edit command, **Then** it is not
   created, and the tool names the command that would create it.
6. **Given** I close the editor, **When** the command finishes, **Then** nothing else
   happens — no validation, no ingestion, no output I did not ask for. The command opens a
   file and stops.

---

### Edge Cases

- **The configuration directory cannot be created** — no permission, or a file sits where
  the directory should be. Reported by path, with nothing partially written.
- **One file is created and the second fails.** The first stays; the failure is named. A
  partial result that is reported is better than an all-or-nothing rollback that leaves the
  user no further forward.
- **The configuration directory exists but is read-only.** Reported as such, not as a
  missing file.
- **The user points `--config` somewhere unusual.** Both commands honour it, so a second
  configuration can be set up without disturbing the first.
- **`$EDITOR` is set to something that does not exist.** Reported by name — the user set it,
  so they can fix it — rather than silently falling through to the system default.
- **`$EDITOR` contains arguments** (`code --wait`, `subl -n -w`). Honoured as written.
- **The editor exits non-zero.** Reported, but the file is still assumed edited: editors
  exit non-zero for many reasons and refusing to continue would be unhelpful.
- **The file is open in another program.** Not the tool's concern; it hands over a path.
- **A user runs the setup command inside a git working tree.** Nothing is written to the
  repository — the files go to the configuration directory, not the current directory.

## Requirements *(mandatory)*

### Amending what came before

- **FR-001**: The tool MUST NOT modify, reformat, reorder, or rewrite any part of a
  configuration or mapping file the user has written. This replaces the previous absolute
  prohibition on writing, and is the property that prohibition existed to protect.
- **FR-002**: The tool MUST NOT change an existing configuration or mapping file under any
  circumstance, including as a side effect of any command in this feature.
- **FR-003**: The specifications and contracts of `0002` and `0003` MUST be amended to say
  this, rather than left to contradict the shipped behaviour.
- **FR-004**: The existing whole-surface test asserting that no command writes the
  configuration file MUST remain, extended to cover the new commands and to assert
  specifically that an **existing** file is never altered.

### Putting the files in place

- **FR-005**: Users MUST be able to create a starting configuration and project mapping with
  a single command.
- **FR-006**: The command MUST place them where the tool looks for them by default, and MUST
  honour an explicitly supplied location.
- **FR-007**: The command MUST create the containing directory if it does not exist, and MUST
  write nothing outside it.
- **FR-008**: The command MUST NOT overwrite, truncate, rename, or back up an existing file.
- **FR-009**: The command MUST offer no option, flag, or environment variable that would
  overwrite an existing file.
- **FR-010**: Where one file exists and another does not, the command MUST create only the
  missing one.
- **FR-011**: The command MUST report, for each file, whether it was created or left alone,
  and where it is.
- **FR-012**: The command MUST succeed when there is nothing to do. Running it twice is not
  an error.
- **FR-013**: Files the command creates MUST contain placeholders only, never a
  plausible-looking value, and MUST validate cleanly.
- **FR-014**: The command MUST also create the credentials file from its shipped template,
  so that setting up an authenticated source needs no further hunting.
- **FR-015**: The credentials file MUST be created readable by its owner alone, and those
  permissions MUST be in place **before** any content is written — there must be no instant
  at which a file intended to hold secrets is readable by anyone else.
- **FR-016**: The command MUST refuse to touch an existing credentials file for the same
  reason it refuses the others, and with more at stake: overwriting it destroys a real
  secret rather than a preference.
- **FR-017**: The template the credentials file is created from MUST contain placeholders
  only, and the command MUST NOT prompt for, read, generate, or write any credential value.
- **FR-018**: The command MUST tell the user what to do next.

### Opening the files

- **FR-019**: Users MUST be able to open the sources configuration, and the project mapping,
  each with a single command.
- **FR-020**: The tool MUST prefer the editor the user has already chosen, falling back to
  the operating system's default application for the file only when none is set.
- **FR-021**: The tool MUST honour an editor setting that includes arguments.
- **FR-022**: The tool MUST NOT create a file that does not exist, and MUST name the command
  that would.
- **FR-023**: The tool MUST report plainly when it cannot open the file, and MUST print the
  path so the user can open it themselves.
- **FR-024**: The tool MUST NOT read, parse, or alter the file's contents in order to open
  it.
- **FR-025**: The tool MUST do nothing else once the editor has closed — no validation, no
  ingestion. A command that opens a file opens a file.
- **FR-026**: These commands MUST NOT be reachable from any command that reads a source, so
  that a scheduled or scripted run can never block waiting for an editor.
- **FR-027**: There MUST be no command that opens the credentials file. Handing a file of
  secrets to an editor chosen by an environment variable is a risk this feature has no
  reason to take, and the path is printed by `init` for anyone who wants it.

### Everything this feature must not disturb

- **FR-028**: No command in this feature MUST contact any network destination.
- **FR-029**: No command in this feature MUST read, write, or migrate the store.
- **FR-030**: No command in this feature MUST touch any mail account, repository, or other
  configured source.
- **FR-031**: No command in this feature MUST print, log, or copy a credential value.
- **FR-032**: Every command MUST be usable from the command line and MUST offer a
  machine-readable form, as every other command does.

### Key Entities

- **Configuration file**: Where sources are declared. Created from a template when absent;
  never altered once it exists.
- **Project mapping file**: Where repositories, correspondents and subjects are mapped to
  projects. Same rules.
- **Shipped template**: The example files distributed with the tool. Placeholders only,
  and the same files a user could copy by hand.
- **Editor preference**: What the user has already told their system they prefer, used
  rather than second-guessed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user goes from an installed tool to a validating configuration in one
  command and one edit.
- **SC-002**: 100% of runs against an existing configuration leave every existing file
  byte-identical.
- **SC-003**: Running the setup command twice in succession produces no change on the second
  run and no error.
- **SC-004**: 0 commands, flags, or environment variables exist that would overwrite a
  configuration or mapping file.
- **SC-005**: A freshly created configuration validates with zero errors.
- **SC-005a**: A freshly created credentials file is readable by its owner and by nobody
  else, verified by asking the operating system rather than by trusting the write.
- **SC-005b**: 0 credential values are written, prompted for, or generated by any command in
  this feature.
- **SC-006**: 100% of values in a freshly created file that need the user's attention are
  recognisable as placeholders.
- **SC-007**: Both edit commands open the correct file, verified by what is handed to the
  editor rather than by what the editor does.
- **SC-007a**: 0 commands exist that open the credentials file in an editor.
- **SC-008**: A file opened for editing is byte-identical when the tool has finished with
  it — the tool changes nothing on the way in or out.
- **SC-009**: Every failure — no directory, no permission, no editor, no file — produces a
  message naming the path and what to do, and 0 failures leave a partially written file.
- **SC-010**: 0 network connections are opened by any command in this feature.
- **SC-011**: 0 commands in this feature read or write the store.
- **SC-012**: The setup command completes in under a second.

## Assumptions

- **Three files are in scope**: the configuration, the project mapping, and the credentials
  file. The store is not — it is created by the commands that use it and needs no template.
- **Including the credentials file was a deliberate choice, and it is the riskier one.**
  It saves a step when setting up an authenticated source, and the tool already has the
  permission-restricting machinery `0001` built for the store and `0004` uses for
  `tokens.toml`. The cost is that this feature now creates a file whose entire purpose is to
  hold secrets, so a permissions mistake here has a worse blast radius than one in
  `config.toml`. FR-015 answers that by requiring permissions to be in place *before* any
  content is written, and SC-005a verifies it by asking the operating system rather than
  trusting the write.
- **Nothing opens the credentials file.** Handing a file of secrets to whatever `$EDITOR`
  happens to name is a risk with no matching benefit (FR-027); `init` prints the path.
- **Templates are the files already shipped in `examples/`**, not a second copy maintained
  separately. A template that drifts from the example is worse than no template, and the
  examples are already validated by the existing suite.
- **`edit` does not create.** Keeping a single command responsible for creating files is
  what makes "never overwrite" easy to state and easy to check; two creators would be two
  places to get it wrong.
- **`edit` does nothing after the editor closes.** Validating automatically was considered
  and rejected: it only works when the editor blocks, so a graphical editor that returns
  immediately would report on a file the user had not finished writing — worse than saying
  nothing. `ikwyd sources validate` is one command away and already suggested by the
  output of several others.
- **The user's editor choice is honoured, not second-guessed.** Anyone who has set `$EDITOR`
  has already said what they want, and for a `.toml` file that is more likely to be right
  than whatever the operating system associates with the extension — which on some systems
  is nothing at all.
- **Opening an editor is interactive, and that is acceptable here** because these commands
  exist to be run by a person. `0004` established that no command reachable from an
  ingestion may block on a browser; the same rule applies to editors, and FR-022 states it.
- **A second interactive command is a change worth noting.** `0004` documented
  `sources authorise` as the only one; that claim needs updating rather than quietly
  becoming false.
- **Existing foundations are reused unchanged**: the configuration and mapping locations
  from `0002` and `0003`, their validation, and the CLI conventions from `0001`.
