# Contract: The configuration file

**Format**: TOML ([research.md](../research.md) D1) · **Parser**: stdlib `tomllib`, read-only
**Default location** (D10), overridable with `--config PATH`:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\iknowwhatyoudid\config.toml` |
| macOS | `~/Library/Application Support/iknowwhatyoudid/config.toml` |
| Linux | `$XDG_CONFIG_HOME/iknowwhatyoudid/config.toml`, else `~/.config/iknowwhatyoudid/config.toml` |

The tool **never modifies this file** (FR-002). Nothing it does will change, reformat or reorder a line
you wrote.

**Amended by `0005`**: `ikwyd init` may **create** this file where none exists, and `ikwyd sources edit`
opens it in your editor without reading or writing it. Neither touches a file that is already there, and no
flag makes them — there is deliberately no `--force`. `tomllib` is still read-only by construction, so the
tool has no parse-and-rewrite path to reach for.

---

## Grammar

```text
config        := version? source*
version       := "version" "=" integer          # optional; defaults to 1
source        := "[[source]]" name kind enabled? since? credential? setting*
name          := "name" "=" string              # unique, [A-Za-z0-9][A-Za-z0-9._-]*
kind          := "kind" "=" string              # a registered kind name
enabled       := "enabled" "=" boolean          # default true
since         := "since" "=" offset-date-time   # timezone-aware
credential    := "credential" "=" string        # a NAME, never a value
setting       := <dotted key> "=" <value>       # declared by the kind
```

Everything outside this grammar is a **blocking** finding. A misspelled key is a source the user believes
is configured; refusing is safer than ignoring.

---

## Worked example

```toml
# iknowwhatyoudid — sources
# This file holds no secrets. Credentials are referenced by name only.

version = 1

# --- git: local repositories -------------------------------------------------
[[source]]
name       = "work-repos"
kind       = "git.local"
since      = 2026-01-01T00:00:00+01:00
paths      = ["~/dev/*", "~/work/monorepo"]
identities = ["stefan@example.com", "Stefan Oderbolz"]

# --- mail --------------------------------------------------------------------
[[source]]
name            = "work-mail"
kind            = "mail.outlook"
credential      = "outlook-work"          # a name; the secret lives elsewhere
since           = 2026-01-01T00:00:00+01:00
addresses       = ["stefan@example.com"]
folders.include = ["Inbox", "Sent Items"]
folders.exclude = ["Junk Email"]

[[source]]
name       = "personal-mail"
kind       = "mail.hey"
enabled    = false                        # switched off; its records stay in the store
credential = "hey-personal"
addresses  = ["stefan@hey.com"]

# --- calendar ----------------------------------------------------------------
[[source]]
name       = "work-calendar"
kind       = "calendar.google"
credential = "google-work"
calendars  = ["primary"]
```

**Verified**: this shape parses under `tomllib` with `since` arriving as a timezone-aware `datetime` and
`folders.include` as a nested dict.

---

## Registered kinds

Kind names are stable — they appear in users' files and cannot be renamed without breaking them.

| Kind | Credential | Destinations | Reading | Settings |
|------|-----------|--------------|---------|----------|
| `git.local` | no | none | **available** (0003) | `paths` (PATH_LIST, required), `identities` (IDENTITY_LIST, required), `exclude` (PATH_LIST) |
| `mail.outlook` | yes | `graph.microsoft.com`, `login.microsoftonline.com` | **available** (0004) | `addresses` (required), `client_id`, `tenant`, `folders.include`, `folders.exclude` |
| `mail.gmail` | yes | `gmail.googleapis.com`, `oauth2.googleapis.com` | **available** (0004) | `addresses` (required), `client_id`, `tenant`, `labels.include`, `labels.exclude` |
| `mail.hey` | no | none | **available** (0004) — reads an export | `addresses` (required), `paths` (required) |
| `mail.mbox` | no | none | **available** (0004) | `addresses` (required), `paths` (required) |
| `calendar.outlook` | yes | Microsoft Graph | *later (0005)* | `calendars` (required) |
| `calendar.google` | yes | Google Calendar API | *later (0005)* | `calendars` (required) |
| `fixture` | no | none | **available** | `recorded` (PATH_LIST, required) |

`mail.hey` was declared by `0002` as "Hey IMAP". That was wrong — Hey offers no IMAP, no POP and no
third-party API — and `0004` corrected it to an archive import rather than removing the name, so a
configuration written on the strength of the old declaration still resolves.

`client_id` is deliberately a **setting, not a credential**. It is public — it appears in every sign-in
URL — and `credentials.toml` registers everything it holds with the redaction filter, which would mask the
client_id out of the very URL `sources authorise --no-browser` asks the user to open.

Kinds marked *later* validate fully today and report readiness `NOT_READABLE` (see
[data-model.md](../data-model.md)). They are declarations, not stubs pretending to work.

`fixture` is the kind that proves the contract end to end (FR-034, SC-012). It is registered in all
builds, reads recorded data from disk, and is what every integration test configures.

---

## What this file must not contain

| Rejected | Severity | Requirement |
|----------|----------|-------------|
| A `[projects]`, `[attribution]`, or `[mapping]` table | blocking | FR-041 — project mapping belongs to a later feature, and is rejected rather than ignored |
| A secret value (`password = "…"`, a PEM block, a prefixed token) | warning | FR-023 — heuristic, so it warns and never blocks |
| Any key not declared by the source's kind | blocking | FR-027 |

Declaring which identities are *yours* (`identities`, `addresses`) **is** allowed and required — it is how
a connector tells what you did from what was done to you (FR-040). Declaring what those identities *mean
for a project* is what FR-041 rejects.

---

## The credentials file

Separate from this file, same permission check (D3).

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\iknowwhatyoudid\credentials.toml` |
| macOS / Linux | alongside the configuration file |

```toml
[credential.outlook-work]
# shape is 0004's decision; this feature only asks whether the entry exists
```

This feature resolves a credential to `PRESENT`, `ABSENT`, or `UNREADABLE` and **never reads its value**
(D6). A keyring-backed store may replace the file in `0004`, behind the same boundary.
