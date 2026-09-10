# Quickstart: validating Git Source and Projects

How to prove this feature works. Every scenario runs against **fixture repositories the tests build in
`tmp_path`** — never the developer's own repositories, as the constitution requires.

## Prerequisites

```bash
uv sync
uv run mypy src tests      # must be clean
uv run pytest              # must be green
git --version              # the external tool; 2.51.2 confirmed on the dev machine
```

Fixture repositories are built by `tests/fixtures/gitrepos.py`, which creates real repositories with known
histories: a plain one, a bare clone, a linked worktree, an empty one, nested ones, one with commits by
other people, and one whose history gets rewritten mid-test.

## Scenario 1 — the repository is not touched (US1, FR-018, SC-003)

**The most important test in the feature.** Principle II says a tool that can alter what it observes is a
liability no amount of usefulness offsets — and this is the first feature pointed at the user's real work.

```bash
uv run pytest tests/integration/test_git_readonly.py -v
```

Hash every file under `.git` for every fixture repository, run a full ingestion including `--sweep`, hash
again, assert the digests are identical. Also assert the working tree is unchanged and no new ref exists.

Then assert the negative directly: `git/binary.py` refuses a command not on its allow-list, so a future
author cannot reach `fetch` or `gc` without changing the one file a reviewer checks.

## Scenario 2 — no socket is ever opened (FR-019, SC-004)

```bash
uv run pytest tests/integration/test_git_offline.py -v
```

Assert on **socket creation**, not on output. Give a fixture repository a remote pointing at an
unreachable host, then ingest: a run that tried to fetch would fail loudly, but a run that opened a socket
at all must fail the test even if it succeeded.

## Scenario 3 — commits, merges and identities (US1)

Expected: commits with fewer than two parents recorded as `commit`, two or more as `merge`; only commits
whose author or committer email matches a declared identity (FR-011); author time as the record's time with
git's offset and **no zone name**; committer time preserved in the payload (FR-012, research R8).

Assert the negatives too: **no message body** anywhere in the store (SC-014 — plant a sentinel in a commit
body and search for it), no diff, no file name, and **no duration on any record** (SC-013).

## Scenario 4 — discovery finds what it should and nothing else (US4)

```bash
uv run pytest tests/unit/test_git_discovery.py -v
```

| Fixture | Expected |
|---|---|
| A folder with three repositories | All three found |
| `notarepo/.git/` full of junk | **Not** a repository — verified that `rev-parse --git-dir` rejects it |
| A bare clone | Found, marked bare |
| A linked worktree | Found; **same identity as its origin**, recorded as a second path (research R3) |
| An empty repository | Found, `identity_kind = path`, contributing no activity (FR-021) |
| `nested/outer` and `nested/outer/inner` | Both found, reported as nested (FR-006) |
| A pattern matching nothing | A warning naming the location (FR-004, SC-010) |
| A symlink pointing outside the root | Not followed (FR-008) |
| More than 100 repositories | The large-match warning (FR-009) |

Assert that `repos list` reads **no commit history** — the whole point of FR-003 is deciding whether to
proceed before a year of history is read.

## Scenario 5 — everything lands on a project (US2, SC-002)

Ingest with a `projects.toml` mapping some repositories and not others.

Expected: every recorded activity carries a project (SC-002); mapped repositories use the mapped project
with rule `mapping:declared`; unmapped ones get a project named after the repository with rule
`mapping:ad-hoc`; and the two are distinguishable in every view (FR-035, SC-009). Two repositories mapped
to one project both contribute to it.

## Scenario 6 — changing the mapping re-attributes without reading (US3, SC-006)

The property that makes the mapping safe to get wrong at first.

1. Ingest with one mapping; record a hand correction on one activity.
2. Change `projects.toml` — move a repository from its ad-hoc project into a declared one.
3. Run `projects rederive` with **every fixture repository deleted from disk** and sockets forbidden.

| Assertion | Requirement |
|---|---|
| Every affected activity carries the new project | FR-037 |
| Zero repositories read, zero sockets opened | FR-037, SC-006 |
| The corrected activity still holds its correction | FR-038, SC-007 |
| The emptied ad-hoc project is no longer listed | FR-040 |
| `--dry-run`'s predicted moves match applying it exactly | FR-041, SC-012 |

Deleting the repositories is the point: it makes "reads no repository" impossible to pass by accident.

## Scenario 7 — the mapping file (FR-028 to FR-031)

```bash
uv run pytest tests/unit/test_projects_mapping.py -v
```

Absent file is valid and yields all ad-hoc (FR-030). A duplicate project name blocks, including one
differing only in case (FR-027). A repository claimed by two projects blocks. A repository matching nothing
**warns** rather than blocks (FR-042) — mapping a repository you have not configured yet is reasonable.
Every fault is reported in one run.

And FR-029, asserted across the whole surface: hash `projects.toml` and `config.toml` before and after
running every command in this feature, and assert both are byte-identical.

## Scenario 8 — withdrawal, and the trap (FR-022, FR-023)

The scenario most likely to be got wrong, so test the negative first.

1. **Incremental withdraws nothing.** Ingest, rewrite history, ingest again without `--sweep`. Assert zero
   records withdrawn.
2. **A sweep withdraws vanished commits.** Repeat with `--sweep`. Assert exactly the rewritten-away commits
   are marked withdrawn, dated, and **not deleted** — the total record count must not fall.
3. **A sweep never withdraws a branch creation.** Record a branch creation, expire or delete the reflog
   entry, sweep, and assert the branch creation is still present and not withdrawn.

Step 3 is the finding from research R2: the reflog is local and expires after 90 days, so treating its
absence as deletion would report a retention policy as data loss.

## Scenario 9 — the migration (m0002)

```bash
uv run pytest tests/integration/test_migration_m0002.py -v
```

Against **both an empty and a populated store**, per the constitution. Cases are listed in
[contracts/schema-m0002.md](./contracts/schema-m0002.md); the load-bearing ones are that two project names
differing only in case collapse to one project, that a deliberately failing migration leaves the store at
v1 with counts unchanged, and that corrections are untouched.

## Scenario 10 — `projects/` cannot read a repository

```bash
uv run pytest tests/unit/test_package_boundary.py -v
```

Assert no module under `src/iknowwhatyoudid/projects/` imports `git/`, `subprocess`, or `socket`. This is
what makes FR-037 structural rather than a rule someone has to remember — re-derivation cannot regress into
reading a repository, because it has no way to.

## Scenario 11 — failures are named, never silent (FR-007, FR-020)

One unreadable repository, one mid-rebase, one deleted between discovery and reading: each is reported by
path and the remaining repositories are still ingested (SC-011). A repository that cannot be read safely is
**skipped, not forced**.

## Scenario 12 — performance

Generate a repository with ~20,000 commits and assert ingestion streams rather than accumulating — peak
memory stays flat as history grows. Assert `repos list` over 100 repositories returns in seconds, reading
no history.

## Known limits at the end of this feature

Both are consequences of what git records, not of the implementation, and the tool states them:

1. **Branch history is incomplete by nature.** The reflog is local and expires after 90 days, so a freshly
   cloned repository yields no branch creations however old its branches are.
2. **No hours are produced.** Activity is recorded as points in time (FR-016); turning them into durations
   is a later summarising feature, which FR-017 guarantees will not need to re-read anything.
