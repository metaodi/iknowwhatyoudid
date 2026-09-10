# Contract: CLI commands

New commands, plus the existing ones this feature changes. Conventions are unchanged from `0001` and
`0002`: results to **stdout**, diagnostics to **stderr**, `--json` everywhere, non-zero exit on failure.

## New global option

| Option | Effect |
|--------|--------|
| `--projects PATH` | Use this mapping file instead of the default, alongside `--config` |

---

## `ikwyd repos list`

Every repository the configuration matches, **without reading any history** (FR-003).

```console
$ ikwyd repos list
Source: work-repos   (~/dev/*, ~/work/monorepo)

REPOSITORY        PROJECT                  PATHS  WHERE
acme-api          acme-migration               1  ~/dev/acme-api
acme-web          acme-migration               1  ~/dev/acme-web
iknowwhatyoudid   internal-tooling             1  ~/dev/iknowwhatyoudid
scratchpad        scratchpad  (ad hoc)         2  ~/dev/scratchpad, ~/dev/scratch-wt
notes-archive     notes-archive  (ad hoc)      1  ~/work/notes-archive  (empty)

5 repositories · 3 mapped · 2 ad hoc
```

`(ad hoc)` marks a project the tool invented, everywhere it appears (FR-035). `PATHS 2` is the worktree
case — one repository, seen twice (research R3).

Opens no socket, reads no commit. Exits `0` even with warnings; `1` if a blocking finding exists.

## `ikwyd repos check`

Discovery diagnostics without ingesting: locations that matched nothing (FR-004), repositories that could
not be read (FR-007), nested repositories (FR-006), and the large-match warning (FR-009).

```console
$ ikwyd repos check
WARN   work-repos.paths[2]   '~/archive/*' matched no repository
WARN   work-repos            'nested/outer/inner' sits inside 'nested/outer'; both are read separately
ERROR  work-repos            '~/dev/locked' could not be read: permission denied

1 error, 2 warnings
$ echo $?
1
```

---

## `ikwyd projects list`

```console
$ ikwyd projects list
PROJECT            SOURCE     REPOSITORIES  ACTIVITY  FIRST SEEN
acme-migration     declared              2     1,204  2026-01-02
internal-tooling   declared              2       318  2026-01-05
admin              declared              0         0  2026-02-01
scratchpad         ad hoc                1        44  2026-03-11

4 projects · 3 declared · 1 ad hoc
```

A **declared** project with no activity is still listed — the user said it exists. An **ad-hoc** project
with no activity is not (FR-040): it existed only because something needed attributing, and nothing does.

## `ikwyd projects validate`

Validates `projects.toml` against the discovered repositories, using the same finding model as
`sources validate` (see [mapping-file.md](./mapping-file.md)).

```console
$ ikwyd projects validate
Projects: C:\Users\ods\AppData\Roaming\iknowwhatyoudid\projects.toml

ERROR  project[1] 'acme-migration'   'acme-api' is also claimed by project[3] 'legacy'
       → a repository maps to exactly one project
WARN   project[2].repositories[1]    'old-thing' matches no discovered repository
       → it may not be configured yet, or may be on another machine

1 error, 1 warning · not ready
$ echo $?
1
```

## `ikwyd projects rederive [--dry-run]`

Re-applies the mapping to activity already recorded (FR-037). **Reads no repository and opens no socket** —
enforced by the package boundary, not by intention: nothing under `projects/` may import `git/` or
`subprocess`.

```console
$ ikwyd projects rederive --dry-run
Re-deriving 1,566 attributions from projects.toml

    44 would move   scratchpad (ad hoc)  →  internal-tooling
    12 would move   acme-web             →  acme-migration
     3 unchanged by the mapping — a correction takes precedence
 1,507 unchanged

1 ad-hoc project would stop holding activity: scratchpad

Nothing has been changed (--dry-run).
```

`--dry-run` answers FR-041 before anything moves, and its predicted moves must match exactly what applying
it does (SC-012). The three held by a correction are FR-038: a rule never overrides the user's own
statement.

---

## Changed commands

| Command | Change |
|---|---|
| `sources list` / `validate` | `git.local` now reports `ready` rather than `not readable (0003 adds it)` |
| `sources kinds git.local` | `reading: available`; gains the `exclude` setting (FR-002) |
| `sources destinations` | `git.local` continues to read `none (local only)` (FR-044) |
| `ingest` | Now actually reads git. `--sweep` becomes meaningful for the first time |
| `records query` | Git activity appears, with its project |

## `ingest --sweep` and withdrawal

`--sweep` reads exhaustively over the window and supplies the commits it saw, so a rewritten history marks
the vanished commits withdrawn (FR-023). Without it a run is incremental and **nothing is ever withdrawn**
— the safe default, unchanged from `0002`.

**Branch creations are never withdrawn, in either mode.** The reflog is local and expires after 90 days
(verified, research R2); treating its absence as deletion would report a retention policy as data loss.

```console
$ ikwyd ingest --sweep --source work-repos
work-repos   git.local   ok   1,566 records, 4 withdrawn

Withdrawn: 4 commits no longer present in 'acme-api' (history rewritten).
Branch creations are never withdrawn — the reflog they come from expires after 90 days.
```

## Exit codes

Unchanged: `0` success · `1` the operation failed or a blocking finding exists · `2` usage error, an
unparseable file, or a store from a newer version.

## Invariants

| Invariant | Requirement |
|---|---|
| No repository is modified — verified by hashing `.git` before and after | FR-018 |
| No socket is opened by any command in this feature | FR-019 |
| `projects.toml` and `config.toml` are never written | FR-029 |
| No commit message body, diff, or file name is stored | FR-014, FR-015 |
| No duration or effort estimate is stored | FR-016 |
| Every listed project is identifiable as declared or ad hoc | FR-035 |
