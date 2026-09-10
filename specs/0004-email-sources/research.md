# Research: Email Sources and Correspondent Attribution

Phase 0 for [plan.md](./plan.md). Every decision below was checked against a primary source or verified
locally; where a claim could not be settled, it says so rather than guessing.

Two findings change what the specification can deliver, and both are recorded first because everything
else depends on them. R1 was **revised** after the user pointed out Hey's official CLI, which had not
appeared in the first pass's sources; the conclusion it replaces is stated inside it rather than deleted.

---

## R1. Hey: read through the official CLI, the way git is read

**Revised.** An earlier pass concluded Hey was unreadable — no IMAP, no POP, no API — and proposed an MBOX
import in place of User Story 4. That was true of Hey's *protocol* surface and is still true of it. It is no
longer the whole picture: **37signals ship an official CLI**, `basecamp/hey-cli`, a Go binary with a
documented command set, structured output, and its own authentication.

**Decision**: read Hey by invoking the `hey` binary, through an **allow-list of read-only subcommands**,
exactly as `0003` reads git through `git/binary.py`.

**Rationale**: this is the same problem `0003` already solved, and the same solution fits. `hey` is a
dual-capability tool — it can `compose` and `reply` — just as `git` can `push` and `gc`. Principle II is not
satisfied by intending to use only the safe half; it is satisfied by making the other half unreachable. One
module holds the list, every invocation goes through it, and a subcommand not on the list raises rather than
runs. A reviewer reads one file to know what this tool can do to a mailbox.

There is a real advantage over the other two providers: **the tool never handles a Hey credential at all.**
`hey` stores its own in the system keyring (file fallback `~/.config/hey-cli/credentials.json`) and
refreshes it itself. Nothing about Hey goes in `tokens.toml`, there is no OAuth flow to implement, and there
is no refresh token for us to leak. FR-008 is satisfied by having nothing to keep.

### Verified from the documentation

| | |
|---|---|
| Read-only subcommands | `box list`, `box view`, `thread read`, `search`, `screener list`, `watch` |
| Mutating subcommands — **never invoked** | `reply`, `compose`, `event add`, `setup` |
| Structured output | `--json` for full output; JSON is also automatic when piped. Also `--jq`, `--ids-only`, `--count`, `--quiet` |
| `search` flags | `--required --any --none --exact --from --to --subject --date --in --label --attachment --page --all` |
| Authentication | Browser sign-in via `hey`; credentials in the system keyring, file fallback `~/.config/hey-cli/credentials.json`; refreshed automatically |
| Boxes | Imbox, The Feed, Set Aside, Reply Later, Paper Trail |

`search --from` is what makes FR-048 plausible here: filtering on the user's own address should return the
mail they sent, without enumerating an inbox.

### Not verified, and it matters

The published documentation does not describe **the JSON schema of a search result**, and lists **no sent
box**. Two questions therefore remain open, and neither can be settled from documentation:

1. **Does `hey search --from <your address>` return mail you sent?** The flag exists and the semantics are
   the obvious ones, but "from" could plausibly mean "sender of a received message" only.
2. **Does a search result carry recipients, date and subject — or only `topic_id` and a summary?**

Question 2 is the one that decides how good this connector can be. If search results carry `From`, `To`,
`Cc`, `Date` and `Subject`, the connector is clean: it reads exactly the fields the message shape needs and
never sees a body. If they carry only thread identifiers, the recipients would have to come from
`thread read` — which renders **an entire thread as Markdown, bodies included**.

That difference is not cosmetic. For Microsoft 365 and Gmail the scope makes a body *impossible to receive*
(R5, R2), so FR-023 holds structurally. If Hey required `thread read`, Hey alone would fall back to a weaker
guarantee: bodies arrive in memory and the connector must be careful not to store them. Careful is worse
than incapable, and the difference should be visible rather than glossed over.

**Decision under uncertainty**: build the connector against `search` and treat "search returns the header
fields" as an assumption to be **verified before `/speckit-tasks` writes tasks for it**. Verification is
three commands against a real account, run by hand by the user — no test may do it (constitution).

```bash
hey search --from YOUR-ADDRESS@hey.com --date last_30_days --json | head -c 4000
hey box list --json
hey --version
```

**If the assumption fails** — search returns only identifiers, or `--from` does not mean sent mail — the
fallback is unchanged from the earlier pass: the **MBOX export**, which Hey still offers and which needs no
new decision. The `mail.mbox` kind is worth building regardless: it is the fixture format for the entire
feature and the escape hatch for both other providers.

### A third integration pattern, and a note on dependencies

Hey makes this feature span all three ways a source can be reached: an HTTP API we call (Graph, Gmail), a
file we read (MBOX), and an **external binary we invoke** (Hey). The binary is not a Python dependency and
does not touch the constitution's dependency-justification rule — it is a tool the user installs, exactly as
`git` is. It must be treated as `git` is in every other respect: detected, version-checked, absent-tolerated
with a clear message, and never assumed present.

**Alternatives considered**:

- **Calling Hey's HTTP API directly**, which the CLI's `API-COVERAGE.md` shows exists (`/advanced_search.json`
  and box endpoints). Rejected: it is undocumented for third parties, unversioned as a public contract, and
  we would have to implement Hey's authentication ourselves — taking on custody of a credential that the
  official CLI already holds properly. Going through the CLI means the auth is Basecamp's problem.
- **MBOX only**, as the previous pass concluded. Still the fallback, no longer the plan.
- **`hey watch`**, which streams new mail as JSON. Interesting for a future live mode, but it observes
  arrivals rather than answering "what did I send last Tuesday", and a long-running process is a poor fit
  for a tool that runs and exits.

Sources: [basecamp/hey-cli](https://github.com/basecamp/hey-cli) ·
[hey-cli CLI reference](https://raw.githubusercontent.com/basecamp/hey-cli/main/docs/cli.md) ·
[hey-cli API coverage](https://raw.githubusercontent.com/basecamp/hey-cli/main/API-COVERAGE.md) ·
[Hey FAQs](https://www.hey.com/faqs/) (no IMAP/POP/API, still accurate)

---

## R2. Gmail: the API, not IMAP — and the constitution decides it

**Finding**: IMAP access to Gmail requires the OAuth scope `https://mail.google.com/`, which grants **full
mailbox access including send and delete**. Google's own guidance is to migrate off it to the Gmail API
where narrower scopes are available.

**Decision**: Read Gmail through the **Gmail API** with the **`gmail.metadata`** scope.

**Rationale**: This is not a preference, it is Principle II applied literally. The constitution requires
"the narrowest read-only scope the source offers". IMAP offers exactly one scope and it includes the power
to delete the user's mail and send mail as them. Choosing IMAP would mean holding a credential that could
destroy the thing we promised only to observe — and no amount of careful client code makes that acceptable,
because the guarantee would rest on our restraint rather than on what the token can do.

`gmail.metadata` grants headers and labels only: **no message body, no attachments**. FR-023 and FR-024 stop
being rules the implementation must remember and become facts about what the server will hand over.

**The user asked "API or IMAP?"** — the answer is API, and the reason is that IMAP cannot be made read-only.

**Cost of this decision** (R3 and R4 below): `gmail.metadata` is a *restricted* scope, and it disables the
Gmail API's search parameter.

Sources: [Gmail OAuth 2.0 / XOAUTH2 mechanism](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol) ·
[Gmail API scopes reference](https://developers.google.com/workspace/gmail/api/auth/scopes) ·
[Gmail API scopes explained](https://www.unipile.com/gmail-api-scopes-guide/)

---

## R3. `gmail.metadata` disallows search, so filtering moves client-side

**Finding**: under `gmail.metadata`, the Gmail API's search parameter (`q`) is unavailable.

**Consequence**: `q="in:sent after:2026/01/01"` — the obvious way to satisfy FR-005 (a start date) and
FR-048 (sent mail only) — cannot be used.

**Decision**: list messages by **label** (`labelIds=["SENT"]`), which is supported, and apply the start date
**client-side** after fetching headers. Incremental runs use `users.history.list` from a stored `historyId`,
which is the API's own change feed and does not need search either.

**Rationale**: FR-048 is still satisfied structurally — asking only for the `SENT` label means received mail
is never fetched, not merely discarded after fetching. The start date is the weaker case: on a *first* run
the tool pages through message identifiers newer than the start date it cannot express server-side. Headers
are small, and every subsequent run is driven by `historyId`, so the cost falls on the first run only.

**Alternatives considered**: `gmail.readonly` would restore search, at the price of granting body and
attachment access we have promised never to use. Rejected — the same reasoning as R2. A capability we hold
and choose not to exercise is a weaker guarantee than one we were never granted.

---

## R4. Google's 7-day token expiry conflicts with FR-012, and cannot be fully resolved

**Finding**: Google expires refresh tokens issued by apps in **Testing** consent-screen status after
**exactly 7 days**. Publishing to Production removes the limit, but the restricted scopes (`gmail.metadata`
among them) require Google app verification and, for production, a CASA security assessment.

**The conflict**: FR-012 says a credential must not be re-entered on every run. A 7-day expiry does not
violate that literally — a run is not a week — but a personal tool that demands a browser round-trip every
Monday is a real cost the specification did not anticipate.

**Decision**: implement Gmail against the OAuth flow (R7) and **treat re-authorisation as an expected,
handled event**, not an error: when the refresh token is rejected with `invalid_grant`, the account reports
`credential expired — re-authorise with 'ikwyd sources authorise gmail'` and every other account still
ingests. Document the 7-day reality plainly in the README rather than hiding it.

**Rationale**: the alternatives are worse. Verification and a CASA assessment for a single-user local tool
is disproportionate, and neither is something this project can promise. The MBOX route (R1) remains
available for a user who would rather export than re-authorise weekly.

**Honest limitation**: this is the one place where the feature will be more annoying than the specification
implies, and no amount of implementation care fixes it. It is a property of Google's policy.

Sources: [Google OAuth refresh token expiration](https://www.unipile.com/google-oauth-refresh-token/) ·
[Restricted scopes — Google Cloud Console Help](https://support.google.com/cloud/answer/13464325?hl=en)

---

## R5. Microsoft 365: Graph with `Mail.ReadBasic`, and delta for incrementality

**Finding**: the delegated permission **`Mail.ReadBasic`** returns a user's messages **without the body and
without attachments**. Microsoft Graph's **`/messages/delta`** returns messages added, changed or removed
since a stored state token, which is exactly the incremental read FR-015 and FR-016 describe.

**Decision**: read Microsoft 365 through **Microsoft Graph** with **`Mail.ReadBasic`** (delegated), scoped
to the **Sent Items** folder, using `/delta` for incremental runs.

**Rationale**: this is the best structural fit of the three providers. The scope makes FR-023 and FR-024
impossible to violate — the server does not send a body, so no code path can store one. Reading the Sent
Items folder rather than the whole mailbox makes FR-048 structural too. Delta tokens make resumption
(FR-016) the server's problem rather than ours.

**On reading local Outlook data instead** (the user's open question): rejected, as the spec assumed. A local
`.ost` is an undocumented format held open by the running desktop client, and `.pst` access on Windows means
MAPI. Both mean opening a live database that another process is writing — the precise scenario Principle II
calls a liability. Graph is a network read of a system designed to be read.

Sources: [New basic read access to a user's mailbox](https://devblogs.microsoft.com/microsoft365dev/new-basic-read-access-to-a-users-mailbox/) ·
[message: delta — Microsoft Graph v1.0](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0) ·
[Get incremental changes to messages in a folder](https://learn.microsoft.com/en-us/graph/delta-query-messages)

---

## R6. Whether the work tenant permits this is a policy question, not a permission question

**Checked, because the secondary sources were wrong.** Several forum answers state that `Mail.ReadBasic`
requires administrator consent. Microsoft's own permissions reference says **"Admin consent required: No"**
for delegated `Mail.Read`, `Mail.ReadBasic` and `Mail.ReadWrite` alike.

**What is actually true**: by default a work or school user *can* consent for themselves. Many corporate
tenants, however, **disable user consent entirely** as a hardening measure, and in such a tenant every
application needs administrator approval regardless of which permission it asks for. The forum reports
describe that configuration, not the permission.

**Decision**: the tool MUST NOT try to predict this. It attempts authorisation, and when the tenant answers
with `AADSTS65001` (consent required) or an admin-approval prompt, it reports **"your organisation requires
an administrator to approve this application"** as a distinct, actionable state — separate from "no
credential configured" and from "credential expired", as FR-010 requires.

**Consequence for the user**: whether User Story 1 can be delivered against the work account is not
knowable from here. If the tenant blocks it, the fallback is the same MBOX route as R1, via an Outlook
export. The P1 priority should be revisited at that point rather than worked around.

Sources: [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) ·
[Overview of user and admin consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview)

---

## R7. Authorisation flow: authorization code with PKCE, on a loopback redirect

**Decision**: OAuth 2.0 **authorization code flow with PKCE**, redirecting to `http://127.0.0.1:<random
port>/`, served by a one-shot handler from `http.server`. No client secret is stored, because a native
application cannot keep one.

**Verified locally**: `secrets`, `hashlib`, `base64`, `http.server`, `urllib.request` and `webbrowser` are
all present in the standard library, so the whole flow needs **no third-party dependency**.

**Rationale**: PKCE is the current standard for native apps precisely because it removes the need for a
secret the binary cannot hide. A loopback redirect keeps the authorisation code out of the terminal and out
of shell history.

**Alternatives considered**: the **device code flow** (show a code, user types it at a URL) avoids opening a
port and is pleasant over SSH. It is the better second choice and is worth adding later; PKCE is chosen
first because it works for both providers with one implementation.

---

## R8. Tokens live in a permission-checked file, reusing what `0001` already built

**Decision**: refresh tokens go in `tokens.toml` beside `credentials.toml`, written with user-only
permissions and **checked on every read with `protection/permissions.py`** — the Windows SDDL and POSIX
mode machinery `0001` already ships and tests.

**Rationale**: the constitution permits "the OS keyring or a local configuration file outside version
control with user-only permissions". A keyring means a third-party dependency on every platform; the
permission-checked file means none, and the checking code exists, is tested, and already guards the store.

**This is the one place the feature writes a credential to disk**, and it is called out here because the
constitution requires a pull request to flag exactly that. Nothing else changes: the token is never logged,
never printed, never written to the database, and `credentials/redaction.py` already exists to keep it out
of diagnostics.

---

## R9. HTTP: the standard library, and rate limits taken seriously

**Decision**: `urllib.request` over HTTPS. On `429` or `503`, honour the **`Retry-After`** header; otherwise
back off exponentially from one second, at most five attempts, then fail that account and continue with the
others.

**Rationale**: the constitution makes the standard library the default and requires every dependency to be
justified. What this feature does over HTTP is issue GET requests and parse JSON. `httpx` and `requests`
buy connection pooling and ergonomics that a tool making a few hundred requests a day does not need.

FR-018 is the reason the retry policy is written down rather than improvised: a tight retry loop against a
corporate tenant is how an account gets throttled, and the user would experience that as their employer's
mail breaking.

---

## R10. One identifier across three providers: the RFC 5322 `Message-ID`

**Decision**: a message's stable identity is its **`Message-ID` header**, normalised. Where a message has
none — rare, but legal — fall back to the provider's own identifier, recorded as such.

**Rationale**: it is the only identifier all three sources share. Graph's `id` changes when a message moves
between folders; Gmail's id is Gmail's alone; an MBOX has no ids at all beyond byte offsets. `Message-ID` is
assigned once by the sending system and travels with the message, which means the *same* message exported
from Hey and read from Graph is recognised as one thing rather than two.

**Verified locally**: `email.utils.getaddresses` and `email.utils.parsedate_to_datetime` parse addresses and
dates from raw headers, the latter **preserving the original UTC offset** (`Tue, 10 Mar 2026 09:14:00 +0100`
→ `2026-03-10 09:14:00+01:00`), which is precisely what FR-022 requires.

---

## R11. Subject rules match by case-insensitive substring — no globs, no regular expressions

**Decision**: a subject rule matches when its text appears anywhere in the subject, compared
case-insensitively. There is no wildcard syntax.

**Rationale**: the obvious choices are both traps.

The convention this feature exists to serve is the bracketed tag — `[ACME]`, `[INV-2231]`. Under
glob matching, `[ACME]` is a **character class** meaning "any one of A, C, M, E", so the single most
likely rule anyone writes would silently match almost every subject. That is not a syntax users can be
expected to escape their way around; it is a design that punishes the common case.

Regular expressions avoid that but bring their own: an unanchored `.*` that matches everything, catastrophic
backtracking on a hostile subject, and an attribution rule that a user cannot read back a month later and
understand. Attribution feeds a billing record; explicability is worth more than expressiveness here.

**Alternatives considered**: an optional `regex = true` per rule was considered and rejected as a
configuration surface for a single anticipated caller, which the constitution forbids. If anchoring is
genuinely needed it should arrive as its own requirement with its own tests.

---

## R12. Address normalisation stops at case

**Decision**: normalise by trimming whitespace, stripping display name and angle brackets, and lowercasing
the whole address. Nothing else.

**Rationale**: FR-031 asks that the same correspondent written two ways be recognised as one. Case is the
only difference that is universally safe to erase — no mail provider in practice treats local parts as
case-sensitive, though RFC 5321 permits it.

**Explicitly not done**: stripping Gmail's dots and `+tags`. That is provider-specific canonicalisation, it
would merge addresses the user never said were the same, and the spec's own assumption is that recognising
one human behind several addresses is out of scope. Erasing a `+client` tag would also destroy exactly the
signal a correspondent rule might want to use.

---

## R13. What a sweep means for mail

**Decision**: mail is read incrementally by default. A `--sweep` re-reads the whole window and may mark a
message withdrawn if the provider no longer presents it. **MBOX sources never withdraw**, because an
archive is one export at one moment and its absence proves nothing about the mailbox.

**Rationale**: this reuses `0001`'s withdrawal rule and `0003`'s hard-won lesson — a source whose evidence
expires or is partial must never have absence read as deletion. An MBOX export is exactly such a source:
export a narrower date range next month and every message outside it would look deleted. Records from an
MBOX therefore carry the same non-withdrawable marking that git branch creations do, which the store already
honours.

---

## R14. What this feature adds to the store

**Decision**: migration `m0003` adds correspondents and the link from a record to them:

- `raw_correspondent` — one row per normalised address;
- `raw_record_correspondent` — which addresses appeared on which message, and in which role.

Project mapping rules stay **in the mapping file**, not in the database, exactly as `0003` decided for
repositories. `derived_attribution` is unchanged in shape and gains three new rule values.

**Rationale**: FR-054 ("see which correspondents contribute most to a project") is a query over
correspondents, and answering it by re-parsing every payload's JSON would be both slow and untypable. A
correspondent is a first-class entity in the spec, so it is a table.

---

## Summary of what changed relative to the specification

| Spec expectation | Reality | Action |
|---|---|---|
| Hey read live via IMAP (`0002`'s kind says so) | No IMAP, no POP, no third-party API — but an official CLI exists | `0002`'s kind declaration is corrected; US4 stands, read through the CLI (R1) |
| Hey read incrementally like the others | The CLI is a third integration pattern: an invoked binary, as git is | Allow-list of read-only subcommands, mirroring `git/binary.py` (R1) |
| "API or IMAP" an open choice for Gmail | IMAP demands full mailbox access | Settled by Principle II: API (R2) |
| FR-012, credential not re-entered per run | Google expires testing-mode tokens weekly | Implemented and handled; documented honestly (R4) |
| FR-015, cost proportional to what changed | True for Graph and Gmail; date-bounded for Hey; false for MBOX | Stated per provider rather than claimed generally (R1) |
| Company tenant "may" refuse | Depends on tenant consent policy, unknowable in advance | Detected and explained as a distinct state (R6) |
