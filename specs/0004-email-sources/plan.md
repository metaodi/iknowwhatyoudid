# Implementation Plan: Email Sources and Correspondent Attribution

**Branch**: `0004-email-sources` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/0004-email-sources/spec.md`

## Summary

Read mail the user **sent**, from three accounts, normalise it to the one activity shape the store already
holds, and attribute it to projects by correspondent and by subject. Nothing in any mailbox is touched.

The design rests on one idea: **make the guarantees structural rather than behavioural**. The specification
forbids storing a message body (FR-023) and forbids storing attachments (FR-024). Rather than write code
that carefully avoids doing so, the tool is put in a position where it *cannot* — by a different mechanism
for each provider:

| Provider | What makes the guarantee structural |
|---|---|
| Microsoft 365 | The `Mail.ReadBasic` scope returns messages **without body or attachments** |
| Gmail | The `gmail.metadata` scope grants **headers and labels only** |
| Hey | The `hey` CLI is reachable only through an **allow-list of read-only subcommands**, as git is in `0003` |
| Archive | A local file, opened read-only; only the header block is parsed |

The same reasoning settles the user's open "API or IMAP?" question: IMAP's only Gmail scope grants send and
delete, so it cannot be used here at all. And FR-048 (sent mail only) is satisfied by asking only for the
Sent folder, so received mail is never fetched rather than fetched and discarded.

Two Phase 0 findings change what can be built, and both are the user's decision to accept:

1. **Hey is read from an exported archive** — verified against a real account, after two earlier
   conclusions were wrong. Hey offers no IMAP, no POP and no third-party API; 37signals do ship an official
   CLI, but its search results carry **no recipients and no `Message-ID`**, timestamps in UTC only, and a
   body preview on every row. None of that can produce the message shape, so `mail.mbox` — already built as
   this feature's foundation — is how Hey mail arrives. See [research.md](./research.md) R1 for the data.
2. **Gmail tokens expire weekly** unless the OAuth app goes through Google verification and a CASA
   assessment, which is disproportionate for a single-user local tool. Re-authorisation is therefore
   designed in as an expected event rather than treated as a failure.

Both are recorded in [research.md](./research.md) with sources.

## Technical Context

**Language/Version**: Python 3.12 (`pyproject.toml`), `mypy` strict

**Primary Dependencies**: **no Python dependency added.** `urllib.request`, `http.server`, `email`,
`secrets`, `hashlib`, `base64`, `ssl`, `json`, `mailbox`, `subprocess` — all standard library, verified
present. The existing `tzdata` marker dependency is unchanged.

**External tools**: none. The `hey` CLI was investigated and rejected (research R1); if a later feature
revisits it, it must be invoked through an allow-list module in the manner of `git/binary.py`.

**Storage**: the SQLite store from `0001`, at schema v2; this feature adds migration `m0003`

**Testing**: `pytest`, against recorded fixtures only — no test contacts a live mail account

**Target Platform**: Windows, macOS, Linux; developed and verified on Windows 11

**Project Type**: single CLI project (`src/iknowwhatyoudid/`)

**Performance Goals**: an incremental run over a week of sent mail completes in seconds; a first run over a
year of sent mail is bounded by the provider's paging, not by the size of the mailbox

**Constraints**: read-only at every source; no network destination other than the configured accounts; no
message body or attachment content anywhere in the store; no credential in the store, the log or any output

**Scale/Scope**: four source kinds, one migration, one new mapping-file section, ~1,000–5,000 sent messages
a year per account

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design. Both passes below.*

| Principle | How this feature satisfies it | Gate |
|---|---|---|
| **I. Local-First and Private by Default** (NON-NEGOTIABLE) | The only network traffic is to the two configured providers, and solely to read. No analytics, no crash reporting, no hosted model. Everything ingested stays in the local store and stays queryable offline (FR-051, SC-015), which a test asserts by forbidding sockets. | **PASS** |
| **II. Read-Only at the Source** (NON-NEGOTIABLE) | No connector may write, and here it additionally *cannot*: the requested authorisations grant reading only, and return no body. Gmail's IMAP route is rejected precisely because its only scope also grants send and delete (research R2). The MBOX kind opens a local file for reading and never writes it — asserted by hashing the file before and after. All scopes are named in full below. | **PASS** |
| **III. Spec-Driven Development** (NON-NEGOTIABLE) | `spec.md` is complete with 55 requirements and no open markers; this plan follows it. User Story 4 stands as written — the CLI makes it deliverable — but one assumption behind it is unverified and is flagged rather than assumed away. | **PASS** |
| **IV. Rebuildable Local Store** | Mail is stored in normalised raw form, separate from derived attributions (FR-026, FR-027). Deleting the store and re-ingesting reproduces equivalent state; the documented exceptions are mail the provider no longer exposes and, for Gmail, history older than the provider's retention of `historyId`. Migration `m0003` is versioned and tested against both an empty and a populated store. | **PASS** |
| **V. Transparent, Correctable Attribution** | Every attribution records the rule and the evidence — which address or which subject text matched (FR-035), and which rule won where several did (FR-037). Ad-hoc attributions are marked in every view (FR-041), as `0003` already does. A correction overrides any rule and survives re-derivation (FR-042, FR-043). | **PASS** |
| **VI. CLI-First with a Local Dashboard** | Every capability is a command with `--json` (FR-051). One new interactive element — the browser round-trip for OAuth — is confined to a single explicit `sources authorise` command and is never triggered by `ingest`, so scripted runs never block on a browser. | **PASS** |

### Technology and Data Constraints

| Constraint | Compliance |
|---|---|
| Python ≥ 3.12, `uv`, `mypy` clean | Unchanged |
| Single embedded database, chosen once | SQLite, unchanged since `0001` |
| Connector behind a common interface | `SourceReader` from `0002`, unchanged. `0003` proved it took a second kind; this feature is the real test, and adds three. |
| **Each connector's plan documents endpoints, fields, scopes, retention** | Below, in *Exactly what is read* |
| Credentials not committed, not logged, not in the database | Referenced by name in config; tokens in a permission-checked file (research R8); `credentials/redaction.py` keeps them out of diagnostics |
| Standard library is the default; each dependency justified | **No dependency added.** Considered and rejected: `msal`, `google-auth`, `httpx` — each replaces a few hundred lines of a flow we must understand anyway, and adds a supply-chain surface to a tool that holds a person's working life. |
| No abstraction for a single anticipated caller | The provider seam already exists; no new one is introduced. A per-rule `regex = true` flag was considered and rejected on exactly this ground (research R11). |

### Things a reviewer must be told about (constitution: PR disclosure)

1. **Two new network destinations**: `graph.microsoft.com` and `gmail.googleapis.com`, plus their identity
   endpoints `login.microsoftonline.com` and `oauth2.googleapis.com`. The Hey CLI reaches Basecamp's
   servers on its own account; this tool does not open that connection and does not see that traffic.
2. **New credentials**: OAuth refresh tokens for each configured account.
3. **A write outside the store**: `tokens.toml`, beside `credentials.toml`, user-only permissions, checked
   on every read with `0001`'s existing permission machinery. This is the only new write outside the data
   directory and is called out deliberately.
4. **A schema migration**: `m0003`, adding correspondents.
5. **No new runtime dependency.** One optional **external binary**, `hey`, invoked only for a configured
   Hey account.

### Exactly what is read

| Provider | Endpoint | Scope requested | Fields taken | Body reachable? |
|---|---|---|---|---|
| Microsoft 365 | `/me/mailFolders/sentitems/messages/delta` | `Mail.ReadBasic`, `offline_access` | `internetMessageId`, `sentDateTime`, `from`, `toRecipients`, `ccRecipients`, `subject`, `hasAttachments` | **No** — the scope excludes it |
| Gmail | `users.messages.list` (`labelIds=SENT`), `users.messages.get` (`format=metadata`), `users.history.list` | `gmail.metadata` | `Message-ID`, `Date`, `From`, `To`, `Cc`, `Subject` headers | **No** — the scope excludes it |
| Exported archive | a local `.mbox` file | none | the same headers, via `email` | Present in the file; **never read** — only the header block is parsed |

**Retention**: raw records are kept until the user deletes the store. No provider response is cached on
disk beyond what becomes a record. The MBOX file belongs to the user and is never modified or moved.

## Project Structure

### Documentation (this feature)

```text
specs/0004-email-sources/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R14, with sources
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1
│   ├── cli-commands.md
│   ├── config-file.md
│   ├── mapping-file.md
│   ├── message-shape.md
│   ├── provider-reading.md
│   └── schema-m0003.md
└── tasks.md             # Phase 2 — /speckit-tasks, not created here
```

### Source Code (repository root)

```text
src/iknowwhatyoudid/
├── mail/                        # NEW — everything mail-specific
│   ├── message.py               # the generic shape; parsing headers into it
│   ├── addresses.py             # normalisation (research R12)
│   ├── mbox.py                  # reading an exported archive
│   ├── graph.py                 # Microsoft 365 reading
│   ├── gmail.py                 # Gmail reading
│   └── reader.py                # MailReader — one SourceReader over all three
├── auth/                        # NEW — OAuth, used only by mail/
│   ├── pkce.py                  # code verifier/challenge, loopback redirect
│   ├── flow.py                  # authorization code exchange and refresh
│   └── tokens.py                # tokens.toml, permission-checked
├── net/                         # NEW — the only place an HTTP request is made
│   └── http.py                  # urllib wrapper: retries, Retry-After, no bodies logged
├── kinds/mail.py                # CHANGED — three kinds become readable; mail.hey corrected
├── projects/
│   ├── mapping.py               # CHANGED — correspondent and subject rules
│   └── attribution.py           # CHANGED — new rules, precedence, domain fallback
├── store/
│   ├── schema.py                # CHANGED — v3
│   └── migrations/m0003_correspondents.py   # NEW
└── cli/
    ├── mail_commands.py         # NEW — `mail` and `sources authorise`
    └── sources_commands.py      # CHANGED — authorise subcommand

tests/
├── fixtures/
│   ├── mail/*.mbox              # NEW — real archives, hand-built
│   └── responses/               # NEW — recorded Graph and Gmail JSON
├── unit/
│   ├── test_mail_addresses.py
│   └── test_subject_rules.py
└── integration/
    ├── test_mail_readonly.py    # the guarantee, asserted first
    ├── test_mail_shape.py       # one shape across three providers
    ├── test_mail_attribution.py
    ├── test_mail_auth.py
    └── test_migration_m0003.py
```

**Structure Decision**: three new packages, each with one job and a boundary worth enforcing. `net/http.py`
is the **only** module permitted to make an HTTP request, so "no destination other than a configured
account" is checkable by one import test — the technique that made `projects/` provably unable to read a
repository in `0003`. `auth/` is separated from `mail/` because tokens are the one thing here that must
never appear in a log. Provider modules sit under `mail/` because a provider is a reading detail; nothing
above `mail/reader.py` knows which one produced a record.

Address normalisation lives at `src/iknowwhatyoudid/addresses.py`, **above** both `mail/` and `projects/`.
It is pure string work that both need, and putting it in `mail/` would have forced an exception to
"`projects/` may not import `mail/`" — turning a boundary a test can check into a judgement every future
author has to re-make.

## Phase 1 design decisions

These follow from research and are recorded here rather than in the contracts because they are choices, not
interfaces.

**One reader, three providers.** `MailReader` implements `SourceReader` once and dispatches on kind. The
three provider modules share a single function signature — given an account and a start point, yield raw
header sets — and know nothing about the store, projects or the CLI.

**Attribution order** (FR-036). For each message: a correction wins; else the first matching subject rule in
declaration order; else the first matching correspondent rule in declaration order; else the ad-hoc project
named for the recipients' domain (FR-039). The order is a property of the mapping file's text, so the same
mailbox read twice in different orders attributes identically — asserted by SC-010b.

**Correspondent rules match a domain by suffix**: `acme.example` matches `anna@acme.example` and
`bob@mail.acme.example`. An address rule is compared whole. An address rule beats a domain rule regardless
of declaration order, because it is strictly more specific and any other choice would make a precise rule
unreachable behind a broad one.

**The `mail.hey` kind is corrected, not removed.** `0002` shipped it declaring destination "Hey IMAP" and
required access "Read your mail over IMAP". Hey has no IMAP; the declaration was wrong. The name stays —
someone may already have written it — and is re-declared as an archive import, so a user who wrote it gets
an explanation rather than "unknown kind".

## Complexity Tracking

No constitution violations. Two decisions cost more than the obvious alternative and are recorded so a
reviewer can disagree with them:

| Decision | Cheaper alternative | Why the cheaper one was rejected |
|---|---|---|
| Hand-rolled OAuth (PKCE, refresh, loopback) in `auth/` | `msal` + `google-auth` | Two dependencies, each pulling their own transitive tree, into a tool holding a person's mail metadata. The flow is ~200 lines of standard library and we must understand it regardless to satisfy FR-010's four distinguishable failure states. |
| Reading Hey from an export rather than from its CLI | `hey search --json` | Verified: search results carry no recipients and no `Message-ID`, so correspondent attribution and cross-provider identity both become impossible. Recovering recipients would mean `thread read`, which returns whole bodies (research R1). |
| A separate `net/http.py` that everything must route through | `urllib` called from each provider module | The boundary is the point. "No network destination other than a configured account" becomes a property one test can assert about the whole codebase, rather than a claim about three modules that a fourth could quietly break. |

## Open decisions for the user

1. **Hey is settled** (research R1, verified 2026-09-10): an exported archive, through `mail.mbox`. One
   loose end remains — the verification ran `--from` with a placeholder address and still returned the
   user's own threads, so whether that flag means "sent by me" is unknown. It does not change the decision,
   because recipients and `Message-ID` are absent either way.
2. **Microsoft 365 may be blocked by your employer's tenant policy.** Not knowable from here. If blocked,
   US1 is undeliverable against that account and the priorities should change — the fallback is an Outlook
   export through the same `mail.mbox` kind.
3. **Gmail will need re-authorising about weekly.** Accept that, or prefer the MBOX route for Gmail too?
