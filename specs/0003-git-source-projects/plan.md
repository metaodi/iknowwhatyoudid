# Implementation Plan: Git Source and Projects

**Branch**: `0003-git-source-projects` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/0003-git-source-projects/spec.md`

## Summary

This feature makes the tool read something real for the first time. It discovers local git repositories
from configured paths and patterns, records the commits and merges the user authored, and attributes every
one of them to a project — declared in a new mapping file, or invented from the repository's own name where
the user has not said. Changing that mapping re-attributes existing activity without touching a repository.

The approach is stdlib-only: git is read by running the `git` binary's read-only plumbing as a subprocess,
which keeps the runtime dependency count at zero and — verified — leaves `.git` byte-identical. A schema
migration introduces the **Project** as a first-class row with a stable identity, replacing the free-text
`project` column that `0001` left as a placeholder.

Three findings from Phase 0 shaped the design more than the spec's literal text:

1. **Branch creation is not in git's object model.** It exists only in the reflog, which is local-only and
   expires after 90 days by default. FR-010 asks for branch creations; they can be recorded, but only as
   best-effort evidence that silently thins out — and they must be excluded from withdrawal, or expiry
   would look like deletion.
2. **A bare clone, a worktree and the original share a root commit**, so root-commit identity treats them
   as one repository. That is right for time-tracking and wrong for reporting "where it was found", which
   is why a repository has one identity and many observed paths.
3. **`git status` is safe but the general class is not.** Read-only plumbing was verified non-mutating;
   the design therefore names the exact commands allowed rather than trusting "git commands don't write".

## Technical Context

**Language/Version**: Python 3.12, as established in `0001`.

**Primary Dependencies**: None added. Standard library only — `subprocess` (the `git` binary), `sqlite3`,
`tomllib`, `pathlib`, `os.walk`, `dataclasses`, `datetime`. The project's one existing runtime dependency
(`tzdata`, Windows-only) is unchanged.

**External tool**: `git` on `PATH`. **Verified**: git 2.51.2 present on the development machine. This is a
tool requirement, not a Python dependency; its absence is detected at validation time and reported as a
not-ready source rather than a crash.

**Storage**: SQLite, via `0001`'s store. This feature ships migration **m0002** adding `project` and
`repository` tables and moving attributions onto a project id.

**Testing**: `pytest`, against **fixture git repositories built by the tests themselves** — created in
`tmp_path`, never the developer's own repositories, as the constitution requires. `mypy` strict.

**Target Platform**: Windows 11 primary; macOS and Linux supported. Platform divergence is limited to path
handling and symlink semantics during discovery.

**Performance Goals**: Discovering repositories under a configured root reports its results in seconds and
reads no history. Ingesting a year of history across 20 repositories completes without loading a whole
repository into memory — commit output is streamed.

**Constraints**: No repository is modified in any way (FR-018). No network connection is opened, even where
remotes are configured (FR-019). No diffs, file contents, or per-file statistics are stored (FR-014). No
commit message body is stored (FR-015). No duration or effort estimate is stored (FR-016).

**Scale/Scope**: 5–50 repositories typical; the design should not fall over at 500. Roughly 1,400–1,800
lines across discovery, reading, projects, mapping and attribution.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How this feature satisfies it | Verdict |
|-----------|-------------------------------|---------|
| **I. Local-First and Private by Default** | A local git repository is not a network source; nothing is fetched and no socket is opened (FR-019), asserted by a test that fails on socket creation. Only the commit *subject* is stored, never the body (FR-015) — the place pasted logs and customer names accumulate never lands on disk. No diffs or file contents (FR-014). | PASS / PASS |
| **II. Read-Only at the Source (NON-NEGOTIABLE)** | This is the first feature where the principle has teeth: the source is the user's real repositories. Only an allow-list of read-only plumbing commands is ever run, `GIT_OPTIONAL_LOCKS=0` prevents lock-taking, and **verified**: the whole `.git` tree hashes identically before and after a full read. A test hashes every fixture repository before and after ingestion. | PASS / PASS |
| **III. Spec-Driven Development** | `spec.md` complete, three clarifications resolved, checklist 16/16. This plan precedes any code. | PASS / PASS |
| **IV. Rebuildable Local Store** | Attributions stay derived: changing the mapping and re-deriving re-attributes everything with zero repository reads (FR-037). Raw git activity is stored normalised and separately from the attribution derived off it. Migration m0002 ships with the schema change and is tested against empty and populated stores. | PASS / PASS |
| **V. Transparent, Correctable Attribution (NON-NEGOTIABLE)** | Every attribution records its rule — declared mapping or ad-hoc fall-back — and its evidence (FR-036). An ad-hoc project is marked as such everywhere it appears (FR-035), so an assumption is never displayed as a decision. User corrections continue to win over any mapping (FR-038). | PASS / PASS |
| **VI. CLI-First** | Discovery, project listing, mapping validation, re-derivation and its preview are all commands with `--json` and non-zero exits (FR-045). No dashboard surface. See [contracts/cli-commands.md](./contracts/cli-commands.md). | PASS / PASS |

### Technology and Data Constraints

| Constraint | Compliance |
|------------|------------|
| Python ≥ 3.12, `uv` toolchain, `mypy` strict | Yes |
| Single embedded database, chosen once | Unchanged — SQLite, decided in `0001` |
| Connector behind the common interface | Yes: this feature supplies the `SourceReader` for the already-declared `git.local` kind. No parallel mechanism |
| Connector `plan.md` documents exact paths read, fields extracted, credential scopes, retention | Below and in [contracts/git-reading.md](./contracts/git-reading.md). **Credential scopes: none.** A local repository needs no credential, and `git.local` declares none |
| Standard library default; every dependency justified | **No new dependency.** The `git` binary is an external tool, justified in [research.md](./research.md) R1 |
| Credentials never committed, logged, or stored | No credential is handled at all |
| No abstraction for a single anticipated caller | No new port. The `SourceReader` protocol already exists |

**Gate result: PASS.** No violations; Complexity Tracking is empty and omitted.

### What this connector reads, exactly

The constitution requires a connector's plan to state this precisely:

| Read | Not read |
|------|----------|
| Commit hash, parent hashes, author name/email/time, committer name/email/time, subject line | Commit message body, diffs, file contents, file names, per-file statistics |
| Branch names and their tip commits | Remote contents — nothing is fetched |
| Reflog entries for branch creation, where present | Anything requiring a write, a lock, or a network round-trip |

**Retention**: recorded activity is retained indefinitely, as with every source; `0001`'s store owns that.

## Project Structure

### Documentation (this feature)

```text
specs/0003-git-source-projects/
├── plan.md                     # This file
├── research.md                 # Phase 0 — decisions and alternatives
├── data-model.md               # Phase 1 — new tables, entities, migration
├── quickstart.md               # Phase 1 — validation walkthrough
├── contracts/
│   ├── cli-commands.md         # New commands and their exit codes
│   ├── git-reading.md          # The exact git invocations, and why each is safe
│   ├── mapping-file.md         # projects.toml format and validation
│   └── schema-m0002.md         # The migration
├── checklists/
│   └── requirements.md         # 16/16
└── tasks.md                    # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/iknowwhatyoudid/
├── git/                        # NEW — everything that knows what git is
│   ├── __init__.py
│   ├── binary.py               # Locating git; the allow-list of read-only invocations
│   ├── discovery.py            # Walking configured paths and patterns for repositories
│   ├── identity.py             # Repository identity: root commit, with path fallback
│   ├── history.py              # Streaming commits and merges out of `git log`
│   ├── refs.py                 # Branches, and best-effort branch creation from the reflog
│   └── reader.py               # The SourceReader for the `git.local` kind
├── projects/                   # NEW — the project entity and the mapping
│   ├── __init__.py
│   ├── model.py                # Project, Repository, Mapping
│   ├── mapping.py              # Reading and validating projects.toml
│   ├── repository.py           # Project and repository storage
│   └── attribution.py          # Applying the mapping; ad-hoc fall-back; re-derivation
├── store/
│   └── migrations/
│       └── m0002_projects.py   # NEW — project and repository tables
├── kinds/
│   └── git_local.py            # CHANGED — gains a reader; reading becomes AVAILABLE
└── cli/
    ├── main.py                 # CHANGED — `projects` group, `repos` group
    └── projects_commands.py    # NEW — list, map preview, re-derive

tests/
├── unit/                       # discovery, identity, mapping validation, reflog parsing
├── integration/                # one per user story, plus the read-only and offline suites
└── fixtures/
    └── gitrepos.py             # NEW — builds fixture repositories in tmp_path
```

**Structure Decision**: Two new packages, split along the seam the feature itself has. `git/` is the only
place that knows git exists — it turns repositories into normalised records and knows nothing about
projects. `projects/` is the only place that knows what activity *means* — it maps records to projects and
knows nothing about git. That separation is what makes FR-037 (re-attribute without reading a repository)
structurally true rather than a rule someone has to remember: `projects/` has no import path to `git/`.

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1. No new violations. Three things the design tightened:

- **Read-only is an allow-list, not a convention.** `git/binary.py` is the only module that may invoke git,
  and it refuses any command not on a fixed list. "Don't run a mutating command" becomes something a
  reviewer can check in one file rather than a property of every call site.
- **`projects/` cannot read a repository.** Enforced by the package boundary above, and by a test asserting
  no module under `projects/` imports `git/` or `subprocess`. FR-037's "without reading any repository" is
  therefore not something re-derivation could regress into.
- **Reflog-derived events cannot be withdrawn.** Recorded separately from commits precisely so that a
  90-day expiry cannot be mistaken for a deleted branch. See research R2 — this is the finding most likely
  to have produced silent data loss had it been discovered during implementation instead.

One limitation recorded rather than papered over: **branch creation history is incomplete by nature.** A
freshly cloned repository has no reflog, and entries older than the expiry window are gone. The tool
reports what it has and states what it cannot know, rather than presenting a partial branch history as
complete.
