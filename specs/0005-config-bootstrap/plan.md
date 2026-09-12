# Implementation Plan: Getting Configured — `init` and `edit`

**Branch**: `0005-config-bootstrap` | **Date**: 2026-09-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/0005-config-bootstrap/spec.md`

## Summary

Three commands: `ikwyd init` puts the configuration, mapping and credentials files where the
tool looks for them; `ikwyd sources edit` and `ikwyd projects edit` open the first two in the
user's editor. Nothing that already exists is ever altered.

The feature is small, and two things about it are not.

**It changes a requirement two features already shipped.** `0002` FR-002 and `0003` FR-029
say the tool never writes these files and that no command creates or edits them. That is
**narrowed, not relaxed**: from "never write" to "never modify, reformat, or reorder anything
the user wrote". The existing whole-surface test stays and is extended, because the property
it guards is the one that mattered — a configuration file must come back exactly as its
author left it.

**`examples/` does not ship in the wheel.** Verified by building one. A first implementation
would have worked in a git checkout and failed for everyone who installed the tool, which is
the worst shape a bug can take. The templates move inside the package
([research.md](./research.md) R1).

## Technical Context

**Language/Version**: Python 3.12, `mypy` strict

**Primary Dependencies**: **none added.** `importlib.resources`, `shlex`, `subprocess`,
`shutil`, `os` — standard library, all verified present.

**Storage**: none. This feature never opens the store.

**Testing**: `pytest`. No test spawns a real editor; the launcher is substituted and what
would have been run is asserted.

**Target Platform**: Windows, macOS, Linux. Verified on Windows 11, where both the packaging
finding (R1) and the `shlex` finding (R2) were found.

**Project Type**: single CLI project (`src/iknowwhatyoudid/`)

**Performance Goals**: `init` completes in under a second (SC-012); it copies three small
files.

**Constraints**: never modify an existing file; no network; no store access; no credential
value written, prompted for, or generated.

**Scale/Scope**: three commands, three templates, one moved directory.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design. Both passes below.*

| Principle | How this feature satisfies it | Gate |
|---|---|---|
| **I. Local-First and Private by Default** (NON-NEGOTIABLE) | Nothing leaves the machine. No network destination is contacted by any command here (FR-028), and a test asserts it by forbidding sockets. | **PASS** |
| **II. Read-Only at the Source** (NON-NEGOTIABLE) | No source is touched (FR-030). The files this feature writes are the user's *own configuration*, not a connected system — and only where nothing exists. An existing file is never altered, which is the property `0002` FR-002 was protecting. | **PASS** |
| **III. Spec-Driven Development** (NON-NEGOTIABLE) | `spec.md` is complete, 16/16 on its checklist, no open markers. The requirement change it needs is made **in the specs**, not worked around in code — FR-003 requires `0002` and `0003` to be amended so they stop contradicting shipped behaviour. | **PASS** |
| **IV. Rebuildable Local Store** | Untouched. No schema change, no migration, no store access at all (FR-029). | **PASS — not applicable** |
| **V. Transparent, Correctable Attribution** | Untouched. No attribution is made or changed. | **PASS — not applicable** |
| **VI. CLI-First with a Local Dashboard** | Three commands, each with `--json` (FR-032). `edit` is interactive by nature, and FR-026 keeps it unreachable from anything that reads a source, so a scheduled run can never block on an editor. | **PASS, with a claim to correct** |

### Technology and Data Constraints

| Constraint | Compliance |
|---|---|
| Python ≥ 3.12, `uv`, `mypy` clean | Unchanged |
| Single embedded database | Untouched — this feature does not open it |
| Connector behind a common interface | No connector added |
| Standard library is the default; each dependency justified | **No dependency added.** |
| Credentials not committed, not logged, not in the database | `credentials.toml` is created from a placeholder template, restricted to the owner **before** content is written (research R5), and never read, prompted for, or generated (FR-017) |
| No abstraction for a single anticipated caller | Three commands, three small modules, no framework. A `--force` flag was considered and rejected outright (FR-009). |

### Things a reviewer must be told about

1. **A requirement changes.** `0002` FR-002 and `0003` FR-029 are narrowed. The spec and both
   contracts are amended; the guarding test stays and grows.
2. **A new write outside the data directory**: three files in the configuration directory,
   created only where nothing exists. One of them holds credentials and is created
   owner-only.
3. **A third module may spawn a process**: `cli/editor.py`, with a different kind of lock
   from `git/binary.py`'s — see research R4.
4. **`examples/` moves into the package** as `src/iknowwhatyoudid/templates/`.
5. **No new runtime dependency, no schema migration, no new network destination.**

### The claim that has to be corrected

`cli/mail_commands.py` currently says, in as many words, that `sources authorise` is *the
only interactive command in the tool*. After this feature there are three. The sentence is
updated rather than left to become quietly false, and what actually matters is kept and
restated: **no interactive command may be reachable from `ingest`**, so a scheduled run
never blocks on a browser or an editor.

## Project Structure

### Documentation (this feature)

```text
specs/0005-config-bootstrap/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R7, each verified on this machine
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── cli-commands.md
│   ├── templates.md
│   └── amendments.md    # what changes in 0002 and 0003, and why
└── tasks.md             # Phase 2 — /speckit-tasks, not created here
```

### Source Code (repository root)

```text
src/iknowwhatyoudid/
├── templates/                   # MOVED from examples/ — ships in the wheel (research R1)
│   ├── __init__.py              # so `importlib.resources` can address it
│   ├── config.toml
│   ├── projects.toml
│   └── credentials.toml
├── config/
│   └── bootstrap.py             # NEW — reads a template, creates a file, never overwrites
└── cli/
    ├── editor.py                # NEW — the ONLY other module that may spawn a process
    └── setup_commands.py        # NEW — `init`, `sources edit`, `projects edit`

examples/
└── README.md                    # all that is left here: points at `ikwyd init`

tests/
├── unit/
│   ├── test_editor_command.py   # $VISUAL/$EDITOR parsing, including the Windows cases
│   └── test_templates.py        # every template ships, parses, and holds placeholders only
└── integration/
    ├── test_init.py             # creates, refuses, reports, and never overwrites
    └── test_edit.py             # hands the right path to the editor, and changes nothing
```

**Structure Decision**: `bootstrap.py` sits under `config/` because it is about configuration
files, and `editor.py` under `cli/` because launching an editor is a terminal concern and
nothing below the CLI should be able to do it. Keeping them apart means the module that
*writes files* and the module that *spawns processes* are separately reviewable, and neither
grows into the other.

`templates/` is a package directory with an `__init__.py` so `importlib.resources` can
address it by module name rather than by guessing a filesystem path — which is the whole
point of using it (research R1).

## Phase 1 design decisions

**One creator.** `bootstrap.py` is the only module that creates a configuration file. `edit`
does not create (FR-022), so "never overwrite" is a property of one function rather than a
rule two modules must both remember.

**Create-then-restrict, for everything.** The permission step is not special-cased to
`credentials.toml`. Every file is created empty, restricted, then written. Applying it
uniformly means the sensitive case cannot be the one somebody forgets, and it costs nothing
for the other two.

**`init` reports per file, not per run** (research R6). Three files, each independently
created or already present; a single boolean would have to call either a no-op or a partial
run a failure. Exit zero whenever nothing went wrong, so `ikwyd init && ikwyd sources
validate` works.

**The editor command is resolved, then run, and those are separate functions.** Resolution —
`$VISUAL`, then `$EDITOR`, then the platform opener — is pure and returns a list of
arguments, so every case in research R2 is a unit test that spawns nothing. Only the running
needs a process, and it is four lines.

**Nothing is read from the file being opened** (FR-024). `edit` checks that it exists and
hands over its path. It does not parse it, which is why a configuration too broken to parse
is exactly the one you can still open.

## Complexity Tracking

No constitution violations. Two decisions cost more than the obvious alternative:

| Decision | Cheaper alternative | Why the cheaper one was rejected |
|---|---|---|
| Move templates into the package | Read `examples/` from the repository | Verified: `examples/` is not in the wheel. The cheap version works for the people who wrote it and fails for everyone who installed it. |
| Resolve the editor command in a pure function, separate from running it | One function that finds and spawns | Every interesting case in research R2 — a Windows path with spaces, a quoted path, a value with arguments — becomes a test that spawns nothing. Testing the combined version means either spawning editors or asserting nothing. |

## Open decisions for the user

None. Both clarifications were answered before planning, and the three findings in
[research.md](./research.md) resolved themselves against verified facts rather than
preferences.

**Confirmed with the user**: the three template files **move** out of `examples/` into the
package. They are not duplicated — one copy before, one copy after — and `examples/` is left
with a README pointing at `ikwyd init`, which is the instruction it used to hold.

Two alternatives were offered and declined: keeping `examples/` canonical and copying it into
the wheel at build time (rejected for the dev/production split it creates in the loader), and
keeping both with a test asserting they stay identical (rejected as duplication that has to
be policed).
