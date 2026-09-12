# Contract: mail accounts in `config.toml`

Extends [`0002`'s configuration contract](../../0002-configurable-sources/contracts/config-file.md). The
grammar and the location are unchanged. The never-writes rule is inherited **as `0005` narrowed it**: the
tool never *modifies* this file, and `ikwyd init` may create one where none exists.

## Registered kinds after this feature

| Kind | Credential | Destinations | Reading | Settings |
|---|---|---|---|---|
| `mail.outlook` | yes | `graph.microsoft.com`, `login.microsoftonline.com` | **available** (0004) | `addresses` (required), `folders.include`, `folders.exclude` |
| `mail.gmail` | yes | `gmail.googleapis.com`, `oauth2.googleapis.com` | **available** (0004) | `addresses` (required), `labels.include`, `labels.exclude` |
| `mail.hey` | no | none | **reads an export** — see below | `addresses` (required), `paths` (required) |
| `mail.mbox` | no | none | **available** (0004) | `addresses` (required), `paths` (required) |

### `mail.hey` is corrected, not removed

`0002` declared this kind with destination "Hey IMAP" and required access "Read your mail over IMAP". That
was wrong — Hey offers no IMAP and no POP — but the kind is not dead: 37signals ship an official CLI, and
Hey is read through it ([research R1](../research.md)).

The name stays, and its declaration is corrected: Hey mail is read from an **exported archive**, exactly as
`mail.mbox` is, because the official CLI cannot supply recipients or a `Message-ID`
([research R1](../research.md), verified against a real account). `credential_required` becomes **false** —
there is nothing to authorise, only a file to point at.

## Worked example

```toml
version = 1

[[source]]
name       = "work-mail"
kind       = "mail.outlook"
credential = "outlook-work"               # a name; the secret lives elsewhere
since      = 2026-01-01T00:00:00+01:00
addresses  = ["stefan.oderbolz@ebp.ch"]

[[source]]
name       = "personal-mail"
kind       = "mail.gmail"
credential = "gmail-personal"
since      = 2026-01-01T00:00:00+01:00
addresses  = ["oderbolz@gmail.com"]

[[source]]
name      = "hey-mail"
kind      = "mail.hey"                    # reads an export, as mail.mbox does
addresses = ["stefan@hey.com"]
paths     = ["~/exports/hey-2026-09.mbox"]

# An exported archive — a fallback for any provider, and how old mail is brought in.
[[source]]
name      = "old-archive"
kind      = "mail.mbox"
addresses = ["stefan@hey.com"]
paths     = ["~/exports/hey-2026-09.mbox"]
```

## Settings

| Setting | Type | Required | Meaning |
|---|---|---|---|
| `addresses` | identity list | yes | Which addresses are **yours** on this account. Only mail sent from one of these is recorded (FR-048). At least one is required — without it the connector cannot tell your mail from anyone else's. |
| `folders.include` / `labels.include` | string list | no | Narrows what is read. Defaults to the account's Sent folder, which is all this feature needs. |
| `folders.exclude` / `labels.exclude` | string list | no | Never read. Applied after include. |
| `paths` | path list | `mail.mbox` only | One or more `.mbox` files. `~` and globs expand, as for `git.local`. |

`mail.hey` needs **no credential and no `ikwyd sources authorise`** — export from Hey, point `paths` at the
file, and ingest. It is `mail.mbox` under a name that says where the mail came from.

`addresses` is validated as syntactically well-formed at configuration time, offline. A malformed address is
**blocking**: silently ignoring one would mean silently recording nothing.

## What is rejected

| Rejected | Severity | Requirement |
|---|---|---|
| A `[projects]`, `[attribution]` or `[mapping]` table | blocking | `0002` FR-041, unchanged — mapping lives in `projects.toml` |
| A password, token or app password inline | warning | `0002` FR-023's secret scan, unchanged |
| `addresses` absent or empty | blocking | FR-003 |
| `paths` on a non-`mbox` mail kind, or absent on `mail.mbox` | blocking | FR-027 |
| A folder or label named in `include` that the account does not have | **warning at validate, reported at read** | FR-004 — offline validation cannot know what folders exist, so the check happens when the account is first contacted |

## The credentials file

Unchanged from `0002`: `credentials.toml`, same location, same permission check. An entry exists so that the
tool knows an account is *meant* to be authorised; the OAuth material itself lives in `tokens.toml`
(below), because a refresh token is obtained by the tool rather than typed by the user.

```toml
[credential.outlook-work]
client_id = "…"        # the application registration; not a secret, but account-specific
tenant    = "…"        # optional; "organizations" by default
```

## `tokens.toml` — new, and written by the tool

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\iknowwhatyoudid\tokens.toml` |
| macOS / Linux | alongside `config.toml` |

**This is the only file outside the data directory that this feature writes**, and the only place a
credential is persisted. It holds one refresh token per configured account and nothing else.

- Created with user-only permissions, and its permissions **checked on every read** using
  `protection/permissions.py` — the same Windows SDDL and POSIX mode machinery `0001` built for the store.
- Never logged, never printed, never written to the database. `credentials/redaction.py` covers it.
- Written by `ikwyd sources authorise NAME` and by a token refresh; by nothing else.
- If it is missing or unreadable, every affected account reports `credential absent` and other accounts
  still ingest.
