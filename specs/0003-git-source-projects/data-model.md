# Phase 1 Data Model: Git Source and Projects

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

Two new tables and one changed one, shipped as migration **m0002**. Full DDL in
[contracts/schema-m0002.md](./contracts/schema-m0002.md).

---

## Project (`user_project`)

The unit a timesheet reports against. Lives in the **user** region: a project the user declared is their
statement, not something derivable from any source.

| Field | Type | Notes |
|-------|------|-------|
| `id` | INTEGER PK | The stable identity. Attributions point here, never at the name (FR-024) |
| `name` | TEXT | As the user wrote it, or the repository name for an ad-hoc project |
| `normalised_name` | TEXT UNIQUE | Case-folded and trimmed; what FR-027's uniqueness is enforced on |
| `ad_hoc` | INTEGER | 1 when the tool invented it, 0 when the user declared it (FR-035) |
| `first_seen_utc` | INTEGER | |

**Why a surrogate id rather than the name**: renaming a project must not detach the activity already
attributed to it (FR-024). With a text key, a rename is a delete plus an insert and the history silently
goes elsewhere.

**Validation rules**

| Rule | Severity | Requirement |
|------|----------|-------------|
| `name` non-empty after trimming | blocking | FR-027 |
| `normalised_name` unique | blocking | FR-027 — including names differing only in case |
| An ad-hoc project may be promoted to declared, never the reverse | — | Declaring a name the tool invented is the user confirming it, and confirmation is one-way |

### States

```text
        a repository with no mapping is ingested
                        │
                        ▼
                 ┌─────────────┐
                 │   AD HOC    │  named after the repository, marked as invented
                 └──────┬──────┘
                        │  the user declares a mapping to this same name
                        ▼
                 ┌─────────────┐
                 │  DECLARED   │  ad_hoc = 0; the user has confirmed it
                 └─────────────┘

        an AD HOC project that holds no activity after a re-derivation
                        │
                        ▼
                    not listed (FR-040)
```

An ad-hoc project that ends up holding nothing — because its repository was mapped elsewhere — stops being
listed rather than lingering as though it held work. A **declared** project with no activity is still
listed: the user said it exists.

---

## Repository (`raw_repository`)

A discovered git repository. Lives in the **raw** region: it is a fact about the world, rediscoverable by
scanning.

| Field | Type | Notes |
|-------|------|-------|
| `id` | INTEGER PK | |
| `identity` | TEXT UNIQUE | The resolved `--git-common-dir` (research R3, revised during implementation) |
| `name` | TEXT | The working-tree directory name; the ad-hoc project name comes from this |
| `identity_kind` | TEXT | `git_dir` — recorded so a later change of rule is visible in the data |
| `first_seen_utc`, `last_seen_utc` | INTEGER | |

### Observed paths (`raw_repository_path`)

| Field | Type | Notes |
|-------|------|-------|
| `repository_id` | INTEGER FK | |
| `path` | TEXT | Resolved absolute path where it was seen |
| `is_bare`, `is_worktree` | INTEGER | |
| `last_seen_utc` | INTEGER | |

**One identity, many paths** — because a linked worktree resolves to its origin's git directory, and one
working tree is reachable at every path beneath it (**verified**, research R3). Collapsing those is right
for a timesheet: the user worked on that repository, not on a checkout. An independent clone is a
*different* repository, deliberately, because merging two that are not the same is invisible and merging
two that are is a one-line mapping entry. Identity then cannot answer "where is it", so the paths are kept
separately and all are reported.

---

## Repository → Project mapping

**Not a table.** The mapping lives in `projects.toml` (FR-028), is read on every run, and is never written
by the tool (FR-029). See [contracts/mapping-file.md](./contracts/mapping-file.md).

Keeping it out of the store is what makes FR-037 cheap: changing the file and re-deriving is the whole
operation, with nothing to migrate and nothing to keep in step.

| In-memory | Type |
|-----------|------|
| `project_name` | `str` |
| `repositories` | `tuple[str, ...]` — repository names or paths |
| `declared_at_line` | `int \| None` — best-effort, for findings |

---

## Git Activity

Not a new table. Git activity is stored as `raw_record` rows through `0001`'s existing shape, which is the
point of that shape existing.

| `raw_record` field | Filled with |
|---|---|
| `source` | The configured source name |
| `source_id` | `commit:<sha>`, `merge:<sha>`, or `branch:<repo-identity>:<branch>:<reflog-index>` |
| `occurred_utc` | Author instant (research R8) |
| `occurred_offset_minutes` | Git's own offset for that commit |
| `occurred_zone` | **NULL** — git records an offset, never an IANA zone name |
| `duration_us` | **NULL** — no duration is ever stored (FR-016) |
| `title` | The commit **subject line only** (FR-015) |
| `payload` | Repository identity, activity kind, parent count, committer instant, matched identity |

**What the payload deliberately does not contain**: the message body, any diff, any file name, any
per-file statistic (FR-014, FR-015).

### Activity kinds

| Kind | Evidence | Withdrawable? |
|------|----------|---------------|
| `commit` | A commit with fewer than two parents, authored by a declared identity | **Yes** — a rewritten history genuinely removes it |
| `merge` | A commit with two or more parents | **Yes** |
| `branch_created` | A reflog entry `branch: Created from …` | **No** — see below |

**Branch creations are never withdrawn.** The reflog is local and expires after 90 days by default
(**verified**, research R2). Treating its absence as deletion would mean that ninety days after creating a
branch, an exhaustive read would mark the event withdrawn — a retention policy misread as data loss, in the
record that feeds a timesheet.

---

## Project Attribution (`derived_attribution`, changed)

| Field | Change |
|-------|--------|
| `project_id` | **New**, FK → `user_project(id)` |
| `project` | **Dropped** — the free-text placeholder `0001` left for this feature |
| `rule` | Now carries `mapping:declared` or `mapping:ad-hoc` (FR-036) |
| `evidence` | The repository identity and the mapping entry that matched |

Everything else about the table is unchanged, including that it is wholly regenerable and lives in the
derived region — which is what lets FR-037 re-attribute a year of activity by discarding and re-deriving,
reading no repository.

### Attribution rules, in order

| Order | Rule | Result |
|-------|------|--------|
| 1 | A `user_correction` exists for the record | The correction wins; no attribution is derived (FR-038) |
| 2 | The repository appears in `projects.toml` | `mapping:declared` → that project |
| 3 | Otherwise | `mapping:ad-hoc` → a project named after the repository (FR-034) |

Rule 1 is `0001`'s existing precedence, unchanged. This feature adds rules 2 and 3 and records which one
fired, so a user can always see *why* a piece of work landed where it did.

---

## Migration m0002

| Step | Why |
|------|-----|
| Create `user_project`, `raw_repository`, `raw_repository_path` | The new entities |
| Insert a declared project for every distinct value in `derived_attribution.project` | No attribution loses its project |
| Add `project_id`, populate from those inserts, drop `project` | FR-024's stable identity |
| Leave `user_correction.project` as text | A correction names a project the user typed; it is their statement, and resolving it to an id is a later feature's problem if it needs one |

Tested against both an empty and a populated store, as the constitution requires. Because DDL and
`PRAGMA user_version` roll back together (verified in `0001`), a failure leaves the store at v1 intact.

---

## Entity coverage against the spec

| Spec entity | Where |
|-------------|-------|
| Project | `user_project` |
| Repository | `raw_repository` + `raw_repository_path` |
| Repository-Project Mapping | `projects.toml`, read per run — deliberately not stored |
| Git Activity | `raw_record` (`0001`'s shape) |
| Project Attribution | `derived_attribution` with `project_id` |
