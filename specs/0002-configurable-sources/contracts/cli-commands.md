# Contract: CLI commands

Console script: `ikwyd` (also `python -m iknowwhatyoudid`).

Every command below reads arguments, writes results to **stdout**, writes diagnostics to **stderr**,
offers `--json`, and exits non-zero on failure — the constitution's Principle VI, applied without
exception.

## Global options

| Option | Effect |
|--------|--------|
| `--config PATH` | Use this configuration file instead of the default (FR-003) |
| `--json` | Emit the machine form on stdout (FR-019). See [json-output.md](./json-output.md) |
| `-v`, `--verbose` | More diagnostics on stderr. Never changes stdout |

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success. For validation: no blocking findings (warnings alone still exit `0`) |
| `1` | Blocking findings, or at least one source failed during a run (FR-040, FR-044) |
| `2` | Usage error, or the configuration file could not be parsed at all (FR-004) |

`2` is separated from `1` deliberately: a broken file and a valid file describing a broken source are
different problems, and a script driving this tool should be able to tell them apart.

---

## `ikwyd sources list`

Lists every configured source with its status (FR-015).

```console
$ ikwyd sources list
Configuration: C:\Users\ods\AppData\Roaming\iknowwhatyoudid\config.toml

NAME             KIND               ENABLED  STATUS
work-repos       git.local          yes      not readable (git reading arrives in a later release)
work-mail        mail.outlook       yes      credential missing: 'outlook-work'
personal-mail    mail.hey           no       disabled
work-calendar    calendar.google    yes      not readable (calendar reading arrives in a later release)
recorded-day     fixture            yes      ready

5 sources · 1 ready · 1 needs a credential · 2 not yet readable · 1 disabled
```

Contacts nothing. Exits `0` unless a source is `INVALID`.

---

## `ikwyd sources validate`

Full offline validation (FR-014, FR-016, FR-017). **Reports every fault in one run**, never stopping at
the first (SC-004).

```console
$ ikwyd sources validate
Configuration: /home/stefan/.config/iknowwhatyoudid/config.toml

ERROR  source[1] 'work-mail'      duplicate source name (also at source[3])
       → names identify a source in the store; give one of them a different name
ERROR  source[2] 'notes'          unknown kind 'obsidian.vault'
       → available kinds: git.local, mail.outlook, mail.gmail, mail.hey,
         calendar.outlook, calendar.google, fixture
ERROR  source[4].paths            required setting missing
WARN   source[5].token            value looks like a secret
       → put it in credentials.toml and reference it with credential = "..."
WARN   config.toml                readable by other accounts on this machine

3 errors, 2 warnings · not ready
$ echo $?
1
```

Guarantees: contacts nothing, writes nothing to the store, leaves the configuration file untouched.

---

## `ikwyd sources check NAME [--live]`

Checks one source (FR-018). Without `--live` this is the offline validation narrowed to one source. With
`--live` it additionally contacts the source to confirm it is reachable and the credential is accepted —
**the only command in this feature that opens a connection**, and only to a destination the named source
declares.

`--live` prints the destination it is about to contact before contacting it, and a kind whose reading is
not yet implemented reports that rather than pretending to succeed.

---

## `ikwyd sources kinds [NAME]`

Lists available source kinds and their settings (FR-028). This is the user-facing documentation of what
can be configured, generated from the same declarations validation uses — so it cannot drift from what is
actually accepted.

```console
$ ikwyd sources kinds git.local
git.local — commits, branches and merges in local git repositories
  reading:      not yet implemented (arrives with feature 0003)
  credential:   not required
  destinations: none (local only)

  paths        PATH_LIST      required   Repositories to read. Accepts a path or a
                                         glob over a containing folder.
  identities   IDENTITY_LIST  required   Author or committer identities that are yours.
```

---

## `ikwyd sources destinations`

Lists every network destination the configured sources may contact, **before anything is contacted**
(FR-045, SC-010).

```console
$ ikwyd sources destinations
work-mail        mail.outlook       Microsoft Graph
work-calendar    calendar.google    Google Calendar API
work-repos       git.local          none (local only)
recorded-day     fixture            none (local only)
```

This command is Principle I made inspectable: the user can see the full egress surface of their
configuration without granting anything or running an ingestion.

---

## `ikwyd ingest [--source NAME] [--dry-run]`

Runs ingestion across all enabled, ready sources, or one named source (FR-042). One source failing never
aborts the others (FR-043).

```console
$ ikwyd ingest
recorded-day     fixture            ok        142 records
work-mail        mail.outlook       failed    credential: 'outlook-work' not found
work-repos       git.local          skipped   reading not yet implemented
personal-mail    mail.hey           skipped   disabled

1 succeeded, 1 failed, 2 skipped
$ echo $?
1
```

Every configured source appears in the report, including skipped ones — a source that silently
contributes nothing must still be visible.

Source state is durable — resumption points survive process exit, backed by `0001`'s store.

---

## Invariants every command upholds

| Invariant | Requirement |
|-----------|-------------|
| The configuration file is never written | FR-002 |
| No credential value reaches stdout, stderr, or a log — redaction is applied at the single render chokepoint | FR-022, SC-007, D7 |
| No destination outside the configured sources is contacted | FR-045, Principle I |
| `--json` output is a stable envelope keyed on finding `code`, not on message text | FR-019 |
| Human output is deterministic and ordered by file position, so runs diff cleanly | — |
