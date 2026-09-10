# Contract: How git is read

**Every git invocation in this project goes through `git/binary.py`, and that module refuses any command
not on the list below.** Principle II — "no connector may create, modify, delete, send, move, label,
archive, or mark-as-read anything in a connected system" — is not a rule each call site must remember; it
is an allow-list a reviewer can check in one file.

## Environment applied to every invocation

| Setting | Why |
|---|---|
| `GIT_OPTIONAL_LOCKS=0` | git takes no lock it does not strictly need, so a read cannot interfere with the user working in the repository at the same time (FR-020) |
| `GIT_TERMINAL_PROMPT=0` | never blocks waiting for credentials |
| `GIT_CONFIG_NOSYSTEM=1` | system config cannot introduce a hook or alias that changes what these commands do |
| `-c core.fsmonitor=false` | no monitor process is started |
| `-c gc.auto=0` | no maintenance is triggered as a side effect |
| `-c log.showSignature=false` | signature verification never shells out or reaches the network |
| No `--git-dir` from user input | the path is always one discovery resolved |

## The allow-list

| Purpose | Invocation | Writes? |
|---|---|---|
| Is this a repository? | `rev-parse --git-dir` | no |
| Bare? | `rev-parse --is-bare-repository` | no |
| Worktree or clone? | `rev-parse --git-common-dir` | no |
| Working tree root | `rev-parse --show-toplevel` | no |
| Identity | `rev-list --max-parents=0 --all` | no |
| History | `log --all --no-decorate --format=<below>` | no |
| Branches | `for-each-ref --format=… refs/heads` | no |
| Branch creation | `reflog show --date=raw <branch>`, or reading `.git/logs/refs/heads/*` | no |

**Verified**: hashing every file under `.git` before and after running `rev-list`, `log`, `for-each-ref`
and `cat-file` produced an identical digest.

Anything not on this list is refused, including `status`, `fetch`, `gc`, `checkout`, `add`, `commit`,
`worktree`, `config --edit`, and every porcelain command that might refresh an index or take a lock.
`git status` was **verified** not to write in the case tested, and is still excluded — the design does not
depend on knowing the conditions under which it would.

## Reading history

```text
git log --all --no-decorate \
  --format='%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%cI%x1f%s'
```

One line per commit, unit-separated (`\x1f`, which cannot occur in any field read):

| Field | Meaning |
|---|---|
| `%H` | commit hash |
| `%P` | parent hashes, space-separated — **empty for a root commit**, two or more for a merge |
| `%an` `%ae` `%aI` | author name, email, strict-ISO instant with offset |
| `%cn` `%ce` `%cI` | committer name, email, instant |
| `%s` | **subject line only** — never `%b`, never `%B` (FR-015) |

Output is streamed and parsed line by line, so a decade of history is never materialised (research R10).

**Verified working**, including the empty-parent root commit and the two-parent merge. **`rev-list
--parents --pretty=format:` is not used**: it was verified to duplicate the hash and interleave the parent
list into the formatted output — a parse that looks correct on a small fixture and corrupts a real
repository.

## What a merge is

A commit with **two or more parents**. Nothing is inferred from the message.

## What a branch creation is, and is not

Read from the reflog, where it appears explicitly:

```text
0000000000000000000000000000000000000000 a4993aa… Me <me@example.com> 1789020264 +0200	branch: Created from HEAD
```

The all-zero "from" hash is what identifies a creation as opposed to an update.

**This evidence is local and expires.** The reflog is not transferred by clone, and `gc.reflogExpire`
defaults to 90 days (**verified** unset on the development machine). Two consequences the implementation
must honour:

1. A freshly cloned repository yields **no** branch creations, however old its branches are.
2. Branch creations are **excluded from the seen set of an exhaustive read and are never withdrawn**. If
   they were treated like commits, reflog expiry ninety days later would be read as the branch having been
   deleted — a retention policy misreported as data loss (research R2).

The tool states that its branch history is necessarily incomplete rather than presenting it as complete.

## Which activity is the user's own

A commit is recorded when its **author email** or **committer email** matches one of the source's declared
`identities`, compared case-insensitively. Other contributors' commits are read (they are in the same
history) and not recorded (FR-011).

## Failure handling

| Situation | Behaviour |
|---|---|
| `git` is not on `PATH` | The source validates as not-ready, naming what to install. Never a traceback |
| git is older than the minimum | Reported at validation with the version found |
| A repository cannot be read — permissions, corruption, a rebase in progress | Reported by path; the remaining repositories are still ingested (FR-007, FR-020) |
| A repository is empty | Recorded as discovered, contributing no activity — not an error (FR-021) |
| A command exceeds its timeout | Killed, reported, the run continues |

Every one of these names the repository by path. A repository the user believes is being read but is not
produces a gap in a timesheet that nobody checks.
