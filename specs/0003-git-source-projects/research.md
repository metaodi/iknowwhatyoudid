# Phase 0 Research: Git Source and Projects

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-09-10

Findings marked **verified** were established by running git on the target machine (Windows 11, git
2.51.2), not recalled.

---

## R1. Reading git — the `git` binary's read-only plumbing, via subprocess

**Decision**: Run the installed `git` executable as a subprocess, restricted to an allow-list of read-only
commands, with `GIT_OPTIONAL_LOCKS=0` set. No Python git library.

**Rationale**:

1. **No new dependency.** The constitution defaults to the standard library and requires each third-party
   package to be justified. `subprocess` is stdlib; git is a tool the user already has, and a tool the user
   demonstrably has, since this feature only reads repositories they already work in.
2. **Read-only is verifiable, and was verified.** Hashing every file under `.git` before and after running
   `rev-list`, `log`, `for-each-ref` and `cat-file` produced an identical digest. The same check on
   `git status` also came back unchanged on this repository, but `status` is *not* on the allow-list: it
   refreshes the index under other conditions, and the design does not rely on which conditions those are.
3. **git's own guarantees are stronger than a reimplementation's.** Packfiles, alternates, worktrees,
   shallow clones, replace-refs and commit-graph files are all handled correctly because git handles them.
   A pure-Python reader would reimplement that surface and get some of it wrong on exactly the repositories
   that matter — large, old ones.
4. **`GIT_OPTIONAL_LOCKS=0`** tells git not to take locks it does not strictly need, which removes the main
   way a read could interfere with a user working in the repository at the same time (FR-020).

**Alternatives considered**:

- **`dulwich`** — pure Python, no C extension, genuinely good. Rejected: a runtime dependency for something
  the stdlib plus an already-present tool does, and its coverage of the awkward cases (worktrees, shallow
  clones, commit-graph) is narrower than git's own.
- **`pygit2`** (libgit2) — fastest, and a proper library API. Rejected: a compiled dependency, wheel
  availability per platform, and libgit2 version skew — a heavy price for reading commit metadata.
- **Parsing `.git` directly** — zero dependencies of any kind. Rejected outright: packfile and delta
  decoding is a large, subtle body of work whose failure mode is silently wrong history.

**Consequences**: git becomes an external tool requirement. Its absence is detected during validation and
reported as a not-ready source naming what to install — not a traceback at ingestion time. The allow-list
lives in one module (`git/binary.py`) so that "no mutating command is ever run" is checkable in one place.

---

## R2. Branch creation is not in git's object model — only in the reflog

**Decision**: Record branch creations as **best-effort** events read from the reflog, stored distinctly from
commit-derived activity, and **excluded from withdrawal**.

**Rationale**: **Verified — this is the finding that most changed the design.** `git for-each-ref` reports a
branch's name and its tip commit's date, and nothing about when the branch came into existence:

```text
feature tip=e34c0a6 committerdate=2026-09-10 08:04:24 +0200
master  tip=12d42c3 committerdate=2026-09-10 08:04:25 +0200
```

The creation event exists only in the reflog, where it is explicit and timestamped:

```text
0000000000000000000000000000000000000000 a4993aa… Me <me@example.com> 1789020264 +0200	branch: Created from HEAD
```

But the reflog has two properties that make it unlike every other source of truth here:

- **It is local.** It is not transferred by clone or fetch. A repository cloned yesterday has no reflog
  history for branches created two years ago, even though the branches are right there.
- **It expires.** `gc.reflogExpire` defaults to 90 days (**verified** unset on this machine, so the default
  applies). Entries simply disappear.

The consequence that matters is for FR-023. An exhaustive read marks records the source no longer presents
as *withdrawn*. If branch-creation events were treated like commits, then ninety days after the fact the
reflog entry would expire, the sweep would not see it, and the tool would mark a branch creation that
genuinely happened as withdrawn — turning a retention policy into apparent data loss, in the artifact that
feeds a timesheet.

So: branch creations are recorded when the evidence exists, are never withdrawn by a sweep, and the tool
states that its branch history is necessarily incomplete rather than presenting it as complete.

**Alternatives considered**:

- **Infer branch creation from the first commit unique to a branch.** Available from history alone and
  survives cloning. Rejected as a *substitute*: it is not the same event — a branch created and left empty
  has no such commit, and a branch created from an old point would be dated by the old commit. It remains
  a reasonable enrichment for a later feature, but not something to present as a creation time.
- **Do not record branch creations at all**, contrary to FR-010. Rejected: the evidence is genuinely there
  most of the time, and the user asked for it. Recording it with honest limits beats discarding it.
- **Treat expiry as withdrawal** — rejected on the argument above; this is the trap, not the design.

---

## R3. Repository identity — root commit, with the git-common-dir as fallback

**Decision**: A repository's identity is the SHA of its **root commit** (the earliest commit with no
parents). Where a repository has no commits, identity falls back to the resolved path of its
`--git-common-dir`. A repository has one identity and **many observed paths**.

**Rationale**: FR-005 requires the same repository reachable by two configured paths to be recorded once,
and the spec's Repository entity requires an identity "independent of that path (so a moved repository is
still the same one)". Root commit satisfies both — it is stable across moves, renames and re-clones.

**Verified**, and the result cuts both ways:

| Path | bare | root commit | git-common-dir |
|------|------|-------------|----------------|
| `repo` | false | `a4993aa6` | `repo/.git` |
| `bare.git` (clone) | true | `a4993aa6` | `bare.git` |
| `wt` (worktree) | false | `a4993aa6` | `repo/.git` |

All three share a root commit, so root-commit identity treats a bare clone, a linked worktree and the
original as **one repository**. For this tool that is the desirable answer: the user worked on that
repository, and which checkout they happened to be sitting in is not what a timesheet cares about. It also
makes the project mapping simpler — one entry covers every checkout.

But it means identity cannot double as "where it lives", so the model keeps a set of observed paths per
repository and reports all of them.

`--git-common-dir` is what distinguishes a linked worktree from an independent clone within a single run,
and is the fallback identity for a repository with no commits — **verified**: `empty`, `nested/outer` and
`nested/outer/inner` all returned no root commit.

**Alternatives considered**:

- **Resolved filesystem path as identity** — simple, and distinguishes clones. Rejected: moving a
  repository would orphan all of its history, which is exactly what the spec says must not happen.
- **The `origin` remote URL** — stable and meaningful. Rejected: not every repository has a remote, several
  can share one, and reading it does not survive a repository that is later re-pointed.
- **A generated id stored in the repository** — rejected outright; writing to the user's repository
  violates Principle II.

---

## R4. Discovery — walking for repositories, not for `.git` directories

**Decision**: Walk each configured location; at every directory ask git whether it is a repository, via
`rev-parse --git-dir`. Do not descend into a discovered repository's `.git`, but **do** descend into its
working tree, so nested repositories are found. Do not follow symbolic links out of the configured root.

**Rationale**: **Verified** that the naive check is wrong: a directory containing a `.git` *directory* full
of unrelated files is not a repository, and `git rev-parse --git-dir` correctly rejected it while
recognising the bare clone, the linked worktree, and both nested repositories. Asking git costs one process
per candidate directory and removes a whole class of false positives — including the `.git` *file* used by
worktrees and submodules, which a "is `.git` a directory?" test gets backwards.

Continuing into a repository's working tree is what satisfies FR-006 (a nested repository is reported and
treated separately) — **verified** with `nested/outer` and `nested/outer/inner`, both found.

Not following symlinks out of the configured location (FR-008) prevents a link into `/` from turning a
narrow configuration into a filesystem-wide scan.

**Alternatives considered**:

- **Test for a `.git` entry without invoking git** — much faster. Rejected on the false-positive and
  `.git`-file findings above. A cheap pre-filter (`.git` exists at all) before asking git is a reasonable
  optimisation and is what the implementation does; the *decision* is still git's.
- **`git rev-parse --show-toplevel` from the walk root** — finds only the outermost repository, so nested
  ones are silently missed.

---

## R5. The Project entity, and migration m0002

**Decision**: A `project` table with a surrogate id, a display name, a normalised name for uniqueness, and
an `ad_hoc` flag. `derived_attribution` gains `project_id`; the free-text `project` column it has today is
migrated into rows and dropped. A `repository` table records identity, current name and observed paths.

**Rationale**: FR-024 requires a project's identity to survive renaming, which a free-text column cannot
do — renaming a project would silently orphan its attributions. `0001` left `project TEXT NOT NULL` as an
honest placeholder for exactly this feature.

FR-027 forbids two projects sharing a name including case differences, so uniqueness is enforced on a
normalised (case-folded, whitespace-trimmed) name while the display name preserves what the user typed.

The migration is where the constitution's rule bites: it ships with the change and is tested against both
an empty and a populated store. Because `0001` verified that DDL and `PRAGMA user_version` roll back
together, a failed m0002 leaves the store exactly as it was.

**Alternatives considered**:

- **Keep `project` as text and add a projects table for metadata only** — smaller migration. Rejected: it
  does not fix the rename problem, which is the entire reason FR-024 exists.
- **A separate attributions table for git only** — rejected: attribution must be uniform across sources, or
  the eventual timesheet has to special-case each one.

---

## R6. The mapping file — `projects.toml`, beside the sources configuration

**Decision**: TOML, hand-edited, named `projects.toml`, in the same directory as `config.toml`. Never
written by the tool. Absent is valid and means everything falls back to ad-hoc projects.

**Rationale**: This is the user's answer to the clarification, and it keeps `0002`'s FR-041 intact — the
sources configuration still rejects a project mapping with a blocking finding, and that shipped check needs
no amendment. The separation is not bureaucratic: attribution rules change often and are expected to be
wrong at first, and a bad rule must not be able to break the configuration that says where to read from.

TOML for the same reasons as `0002` D1: stdlib `tomllib`, read-only by construction (so FR-029's "never
rewritten" has no code path to violate), positions on parse errors, and no implicit type coercion.

Validation reuses `0002`'s finding model wholesale — every fault in one run, located by project and entry,
blocking separated from warning — so a user learns one way of being told they made a mistake.

**Alternatives considered**:

- **Mapping in the store, edited by commands** — no new file. Rejected: it stops being diffable and
  reviewable, and the mapping is exactly the kind of thing a user wants to read, edit in bulk and keep in
  their dotfiles.
- **Mapping in `config.toml`** — one file. Rejected by the clarification, and it would require amending a
  shipped, tested requirement.

---

## R7. Withdrawal for git, and what a sweep actually means

**Decision**: An exhaustive read enumerates every commit reachable from every ref within the window and
supplies those identifiers as the seen set. Commits are therefore withdrawable — a rewritten history
genuinely removes them. **Reflog-derived branch creations are excluded from the seen set and never
withdrawn** (R2).

**Rationale**: `0001` built the withdrawal machinery and `0002` threaded `RunMode` through, but until now
nothing could actually trigger it — no reader existed. Git is the first source where "the source no longer
presents this record" is a real, meaningful event: a rebase, an amend, or a force-push rewrites history and
the old commits genuinely cease to exist.

FR-023 asks for exactly that, and the store already does the right thing: mark withdrawn, never delete, so
the evidence behind an already-submitted timesheet does not evaporate.

**Alternatives considered**:

- **Never sweep; always incremental** — safest, and never withdraws anything. Rejected: FR-023 asks for
  rewritten history to be reflected, and the incremental default already means a sweep is deliberate.
- **Sweep by default** — rejected: a user running `ingest` on a repository mid-rebase should not have
  half their history marked withdrawn as a side effect of a routine command.

---

## R8. Time, identities, and what maps onto `0001`'s record shape

**Decision**: Store the author time as the record's time, with git's own UTC offset, and `occurred_zone`
NULL. Keep committer time in the record's payload. Match the user's declared identities against author and
committer email, case-insensitively.

**Rationale**: git stores a commit's time as an epoch second plus a UTC offset — **verified** in the
`%aI`/`%cI` output — and never an IANA zone name. That maps exactly onto `0001`'s FR-007 storage (instant,
offset, optional zone name), with the zone simply absent. Worth stating: for git activity, a
daylight-saving repeated hour is genuinely unresolvable, and the design does not pretend otherwise.

Author time is the record's time because FR-012 distinguishes work done from work landed, and "when I did
it" is the timesheet-relevant one. Committer time is preserved in the payload so a rebase weeks later
remains visible.

Email is the matching key because names are inconsistent and get rewritten; case-insensitive because mail
addresses are.

**Alternatives considered**:

- **Committer time as the record's time** — rejected: a rebase would move a month of work to one afternoon.
- **Record both as two activities** — rejected as double-counting for a tool whose purpose is totalling
  time.

---

## R9. The "too many repositories" threshold (FR-009)

**Decision**: Warn when a first ingestion would cover more than **100** repositories, and require the user
to proceed deliberately. Configurable; the number is a guardrail, not a limit.

**Rationale**: The number's job is to catch `paths = ["~"]`, not to express a real capacity limit. A working
developer plausibly has tens of repositories under one root and implausibly has hundreds they actively
commit to, so 100 sits above the honest case and below the accident. It is a warning with an override
rather than a refusal, because the tool should not be the arbiter of how many repositories someone has.

**Alternatives considered**:

- **No threshold** — rejected: a mistyped pattern quietly reading a whole home directory is precisely the
  surprise FR-009 exists to prevent.
- **A hard limit** — rejected: someone with 300 repositories is not doing anything wrong.

---

## R10. Streaming, not accumulating

**Decision**: Read commits by streaming `git log`'s output line by line with a unit-separator (`\x1f`)
field delimiter, yielding records as they are parsed.

**Rationale**: **Verified** that `git log --format='%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%cI%x1f%s'`
produces exactly one line per commit with unambiguous fields, parents empty for a root commit, and merges
identifiable by a parent count of two or more. `\x1f` cannot occur in any of the fields read.

Streaming keeps a repository with a decade of history from being materialised in memory, and matches the
`SourceReader.read()` contract, which yields rather than returns.

**Rejected**: `rev-list --parents --pretty=format:` — **verified** to duplicate the hash and interleave the
parent list into the formatted output, producing exactly the kind of mangled parse that looks fine on a
small fixture and corrupts a real repository.

---

## R11. What is stored so that hours can be derived later

**Decision**: Store no duration (FR-016). Store, per activity, the repository, the exact commit, the author
and committer instants, and the activity kind.

**Rationale**: The user chose to store no durations, so this feature's obligation is FR-017: leave enough
that a later feature can derive hours *from the records alone*, with no repository re-read. Ordering and
timing per repository is exactly what any session heuristic needs — the gap between consecutive commits in
a repository is the input, and it is fully recoverable from what is stored.

Recording this explicitly matters because the temptation, when the summarising feature is written, will be
to go back to the repositories for something that was not kept. It should not need to.

---

## Open items carried into implementation

None blocking. Two consequences recorded so they are not rediscovered:

1. **`git.local` currently declares `reading = NOT_YET_IMPLEMENTED`.** This feature flips it and supplies
   the reader. Its settings (`paths`, `identities`) already exist and are unchanged; `exclude` is added
   (FR-002), which is a new optional setting on an existing kind and breaks no existing configuration.
2. **Branch history is incomplete by nature** (R2), and the tool must say so rather than let a user
   conclude their branch record is complete.
