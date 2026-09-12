# Research: Email Sources and Correspondent Attribution

Phase 0 for [plan.md](./plan.md). Every decision below was checked against a primary source or verified
locally; where a claim could not be settled, it says so rather than guessing.

Two findings change what the specification can deliver, and both are recorded first because everything
else depends on them. R1 was **revised** after the user pointed out Hey's official CLI, which had not
appeared in the first pass's sources; the conclusion it replaces is stated inside it rather than deleted.

---

## R1. Hey: read from an exported archive (verified)

**Revised.** An earlier pass concluded Hey was unreadable — no IMAP, no POP, no API — and proposed an MBOX
import in place of User Story 4. That was true of Hey's *protocol* surface and is still true of it. It is no
longer the whole picture: **37signals ship an official CLI**, `basecamp/hey-cli`, a Go binary with a
documented command set, structured output, and its own authentication.

**Decision, after verification**: read Hey from an **exported MBOX archive**. The official CLI cannot
supply what a message record needs — see *Verified against a real account* below.

This section records two earlier conclusions and why each was superseded, because the
reasoning matters more than the answer: the first pass said Hey was unreadable, the second
said it should be read through the CLI, and the third is what the CLI's own output showed.

**The second pass’s rationale, kept because it still holds for the parts it covers.** `hey` is a
dual-capability tool — it can `compose` and `reply` — just as `git` can `push` and `gc`, so if it is ever
invoked it must be through an allow-list in one module, exactly as `git/binary.py` does. And it has a real
advantage over the other two providers: **the tool would never handle a Hey credential at all**, since `hey`
keeps its own in the system keyring and refreshes it itself.

Neither point survives contact with what the CLI actually returns. Both are recorded because they are the
reasons to reach for the CLI again if a future feature can live with what it offers.

### What the documentation said

| | |
|---|---|
| Read-only subcommands | `box list`, `box view`, `thread read`, `search`, `screener list`, `watch` |
| Mutating subcommands — **never invoked** | `reply`, `compose`, `event add`, `setup` |
| Structured output | `--json` for full output; JSON is also automatic when piped. Also `--jq`, `--ids-only`, `--count`, `--quiet` |
| `search` flags | `--required --any --none --exact --from --to --subject --date --in --label --attachment --page --all` |
| Authentication | Browser sign-in via `hey`; credentials in the system keyring, file fallback `~/.config/hey-cli/credentials.json`; refreshed automatically |
| Boxes | Imbox, The Feed, Set Aside, Reply Later, Paper Trail |

On paper `search --from` made FR-048 plausible: filter on your own address and get the mail you sent,
without enumerating an inbox. The next section is what happened when that was tried.

### Verified against a real account (T067), and the assumption failed

Run by the user on 2026-09-10 against `hey` 1.4.3. The three commands are in the task
list; what they returned settles the question, and not the way this decision assumed.

**`hey box list` confirms there is no sent box.** Six boxes exist — Imbox, The Feed, Set
Aside, Reply Later, Paper Trail, Bubble Up — and none of them holds sent mail. `search`
is therefore the only route to it, which makes everything below load-bearing.

**A `hey search` result does not carry what a message record needs:**

| Needed | In a search result? |
|---|---|
| Subject | **yes**, at thread level |
| Sender | **yes**, as `messages[].creator.email_address` |
| Instant | **yes**, as `created_at` — but **UTC only** (`2026-09-10T12:16:04Z`) |
| **Recipients (`To`, `Cc`)** | **no. Absent entirely.** |
| **`Message-ID`** | **no.** Only Hey's own `id` and `topic_id`, which differ per account |

Three consequences, in order of severity:

1. **No recipients means no correspondent attribution.** FR-034 matches a rule against the
   addresses on a message, and FR-039's ad-hoc fallback names a project after the
   *recipients'* domain. Neither can run on a Hey record. Subject rules would still work;
   nothing else would.
2. **No `Message-ID` breaks identity, and not only across providers.** Research R10 chose
   it so that one message reaching the store twice becomes one record. Hey has no shared
   identifier at all — and where a user runs **several accounts inside one Hey**, the same
   email appears once per account with different ids each time. Verified below. That is
   double-counted work in a billing record, which is the failure this project exists to
   avoid.
3. **The instant loses its offset.** FR-022 requires the original offset preserved, because
   a message sent at 00:30+0200 belongs to the previous day in UTC and would land on the
   wrong timesheet line. `Z` timestamps cannot supply it.

**And a fourth finding that was not anticipated at all**: every search result carries a
`summary` field holding **the first ~100 characters of the message body**:

> `"summary": "Hoi Irène ja ich bin bereits auf dem Verteiler und habe alles bekommen…"`

FR-023 forbids storing any part of a body. This does not breach it — nothing stores
`summary` — but it changes the *kind* of guarantee available for Hey. For Microsoft 365
and Gmail the scope makes a body **impossible to receive**. Here a body arrives on every
result and the connector must discard it. That is a materially weaker promise, and the
difference belongs in the open rather than smoothed over.

**`thread read` is not the way out** — verified, not assumed. See below: it returns full
bodies, a timestamp with no zone at all, and still no recipients and no `Message-ID`.

### `--from` does filter — and the multi-account case is the real problem

The verification ran `--from YOUR-ADDRESS@hey.com` — the **placeholder**, not a real
address — and still returned ten threads. Three distinct creators appear across them:

| `account_id` | contact `id` | address | `contactable_type` |
|---|---|---|---|
| 111587 | 2902503 | stefan.oderbolz@hey.com | User |
| 464571 | 65977909 | stefan.oderbolz@metaodi.ch | User |
| 111587 | 17006724 | stefan.oderbolz@metaodi.ch | **Person** |

**An earlier reading of this table was wrong** and is corrected here rather than removed,
because the mistake is instructive. `contactable_type: "Person"` was taken to mean "sent
by somebody else", and therefore that the result mixed sent with received. It does not.
The user manages **several accounts inside one Hey**, and `metaodi.ch` is one of theirs;
`User` is an account holder, `Person` is the *contact record* the same address has when
seen from a different account. All ten threads are the user's own.

That is evidence the filter **worked**: an ignored `--from` would have returned a mailbox,
and a mailbox is mostly other people. Ten out of ten authored by the account owner is not
what no filter looks like. The mechanism is still unexplained — a placeholder address
should not have matched anything — so this is "behaves as if it filters", not a contract
to build on. But FR-048 is no longer the blocker here.

`summary: "10 matching threads"` with `meta.pages_fetched: 1` still suggests ten is a
default page size rather than a complete answer.

### Several accounts in one Hey means the same message arrives twice

The finding that decides this section, and it only appeared because the user pointed out
the multi-account setup.

| Thread | Message | `created_at` | `account_id` | `contactable_type` |
|---|---|---|---|---|
| 1238108147 | 2244055844 | 2026-08-27T21:12:13Z | 464571 | User |
| 1238108298 | 2244057639 | 2026-08-27T21:14:23Z | 111587 | Person |

Different thread ids, different message ids, two minutes and ten seconds apart — and
**byte-identical `summary` fields**. It is one email, recorded once as sent from one
account and once as received into another.

Hey gives these no shared identifier. `id` and `topic_id` differ, and there is no
`Message-ID`. A connector reading `search` would therefore store one email as **two
records**, and a timesheet built on them would **count the work twice**.

Research R10 chose the RFC 5322 `Message-ID` precisely so that one message reaching the
store by two routes collapses into one record. For a single-account user that is a
nicety; for this user it is load-bearing, and it is the strongest single reason the export
route wins. An export carries the real header, so the duplicate collapses on its own.

### `thread read --json` was checked too, and closes the last door

`search` returns summaries, so it was fair to ask whether the detailed view carries more.
It does not. `hey thread read 2111404921 --json` returns, for one message:

```json
{
  "id": 2244051207,
  "created_at": "2026-08-27T21:07",
  "creator": { "id": 65977909, "name": "Stefan Oderbolz",
               "email_address": "stefan.oderbolz@metaodi.ch" },
  "summary": "Hallo Velo!",
  "body": "Hallo Velo!",
  "body_state": "hydrated"
}
```

| | |
|---|---|
| Recipients | **still absent** |
| `Message-ID` | **still absent** — `id` is Hey's own, and differs per account |
| Instant | **worse than search**: `2026-08-27T21:07` drops both the seconds and the `Z` |
| Body | **fully hydrated**, not a preview |

`id` cannot stand in for a `Message-ID`, and the duplication above is the proof: the same
email carried ids `2244055844` and `2244057639` in two of the user's accounts. `creator`
is the sender, which `search` already supplied; what attribution needs is who it went to.

So `thread read` would mean receiving **every body in full** in exchange for a field it
does not have.

### Why no further command will help

Hey models **a conversation, not an envelope**. A posting has a `creator`, a `body` and a
thread; there is no `To` or `Cc` because RFC 5322 recipients are not part of how Hey
represents mail. That is a design decision rather than an omission, and it is why this
section stops looking: the fields are not hidden behind a flag, they are absent from the
model.

For completeness, `thread read`'s breadcrumbs advertise two further mutating subcommands
beyond those already catalogued: `hey reply <id>` and `hey forward <id> --to <email>`. Any
future use of this binary must go through an allow-list for that reason.

### The box listing exposes a change feed

Worth recording even though it does not rescue this connector. Each box in `hey box list`
carries a per-box cursor:

```text
"posting_changes_url": ".../boxes/557203/postings/changes.json?since=<ISO-8601>&v=2"
```

The `since` value differs per box and tracks that box's most recent change — Imbox at
minutes old, Bubble Up at 2022. That is a versioned delta feed, exactly the shape FR-015
wants, and the boxes also carry `signed_stream_name` and `updates_channels`, which are
live-push stream tokens rather than polling.

Hey therefore *has* incremental infrastructure. The CLI does not surface it as a command,
and none of it supplies a recipient.

### Every search row carries part of a body

Not anticipated, and the strongest argument in this section. Each message in a result has
a `summary` field holding roughly the first hundred characters of the body. In the
captured output those hundred characters included a sick note, a child’s name and school
schedule, a reservation number, and political affiliation.

Nothing stores it, so FR-023 is not breached. What changes is the **kind** of guarantee:
Microsoft 365 and Gmail are read under scopes that make a body *impossible to receive*,
while Hey hands one over on every row and asks the client to be careful. Careful is a
weaker promise than incapable, and for a source the user rated P4 it is not a trade worth
making.

### Decision, revised again

**Hey is read from an exported MBOX archive** — the conclusion of the first pass, restored
for reasons the CLI's own output supplies rather than for want of an alternative. An
export carries real `Message-ID`s, real offsets, and real recipients, so a Hey message
becomes the same shape as every other and every rule applies to it unchanged.

`mail.mbox` was already built as the feature's foundation, so this costs nothing new.

**The CLI is not discarded.** It stays worth having for two things a future feature can
use, and the allow-list module is worth writing when either arrives:

- **`hey box list` and `posting_changes_url`** — the box listing exposes a
  `changes.json?since=…` endpoint per box, which is the shape of an incremental feed and
  may well carry more than `search` does.
- **`hey search --subject`** — subject rules alone could attribute Hey mail without
  recipients, if a coarse answer is ever preferable to an export.

**Alternatives considered and rejected**:

- **`search` plus `thread read`** — recovers recipients at the cost of receiving every
  body in the thread. Rejected: it makes Hey the only provider where the read-only body
  guarantee is behavioural rather than structural, for a source the user rated P4.
- **`search` alone, subject rules only** — no recipients, no ad-hoc domain fallback, so
  Hey mail would need a fifth fallback rule of its own. Rejected: a provider-specific
  attribution path is exactly what FR-028 exists to prevent.
- **Hey's HTTP API directly** (`/advanced_search.json`) — undocumented for third parties,
  and it would mean holding a credential the CLI already holds properly.

### What the binary is still good for

The `hey` CLI is installed on the developer's machine and works; nothing here says
otherwise. What it cannot do is supply the fields a *record* needs. Those are different
claims, and the distinction is worth keeping straight — an earlier draft of the README
said this tool invokes `hey`, which it does not.

Two uses survive, neither of which needs a recipient, and both belong to a **later
feature** rather than to `0004`:

- **Telling the user their export is stale.** `hey box list` returns a per-box
  `changes.json?since=<cursor>`. Comparing that against the newest message already in the
  store would let `ikwyd sources check` say *"your export covers up to 27 August; Hey has
  changed since then"*. That is the CLI doing what it is demonstrably good at — knowing
  what exists — without asking it for fields it does not have.
- **Subject-only attribution**, if a coarse answer were ever preferable to an export.
  Rejected for now: it would need a fifth, Hey-specific fallback rule, and a
  provider-specific attribution path is what FR-028 exists to prevent.

Either would have to go through an allow-list module in the manner of `git/binary.py`.
`hey` can `compose`, `reply`, `forward`, `event add` and `setup`; its own breadcrumbs
advertise the first three, so an allow-list is not a hypothetical precaution.

**Alternatives considered**:

- **`search` alone** — no recipients, no `Message-ID`. Rejected: the two fields
  attribution and identity are built on.
- **`search` plus `thread read --json`** — verified above. Returns full bodies, a
  timestamp with neither seconds nor zone, and still no recipients. Rejected: it gives up
  the structural body guarantee and gains nothing.
- **Calling Hey's HTTP API directly** (`/advanced_search.json`, per the CLI's
  `API-COVERAGE.md`). Rejected on two grounds: it is undocumented for third parties and
  unversioned as a public contract, and we would have to implement Hey's authentication
  ourselves. It would also not help — the CLI's output *is* that API's output, and the
  recipients are missing from the model rather than from the CLI.
- **`hey watch`**, which streams new mail as JSON. It observes arrivals rather than
  answering "what did I send last Tuesday", and a long-running process is a poor fit for a
  tool that runs and exits.

Sources: [basecamp/hey-cli](https://github.com/basecamp/hey-cli) ·
[hey-cli CLI reference](https://raw.githubusercontent.com/basecamp/hey-cli/main/docs/cli.md) ·
[hey-cli API coverage](https://raw.githubusercontent.com/basecamp/hey-cli/main/API-COVERAGE.md) ·
[Hey FAQs](https://www.hey.com/faqs/) · plus `hey` 1.4.3 output captured from a real
account on 2026-09-10, which is what actually decided this.

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
