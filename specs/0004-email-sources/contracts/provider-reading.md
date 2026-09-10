# Contract: reading from a provider

What each provider module must do, and — more importantly — what it must be unable to do. This is the
constitution's "each connector's plan MUST document the exact endpoints it reads, the fields it extracts,
the credential scopes it needs, and how long it retains raw data".

## The shared shape

Every provider module exposes one function:

```text
read(account, since, resumption_point) -> yields RawHeaders, and a new resumption point
```

`RawHeaders` is a dict of header name to value plus the provider's own identifier. **No provider module
touches the store, projects, or the CLI.** Normalisation into a message happens once, in
`mail/message.py`, so a bug in it is one bug rather than three.

---

## Microsoft 365 — `mail/graph.py`

| | |
|---|---|
| **Destinations** | `login.microsoftonline.com` (authorisation), `graph.microsoft.com` (reading) |
| **Scope requested** | `Mail.ReadBasic offline_access` |
| **Why that scope** | It returns messages **without body or attachments**. FR-023 and FR-024 become facts about the token rather than rules the code must remember. `Mail.Read` would work and is broader; `Mail.ReadWrite` is never requested under any circumstance. |
| **Endpoints** | `GET /me/mailFolders/sentitems/messages/delta` with `$select`, then the `@odata.nextLink` / `@odata.deltaLink` chain |
| **Fields taken** | `internetMessageId`, `sentDateTime`, `from`, `toRecipients`, `ccRecipients`, `subject`, `hasAttachments` |
| **Never requested** | `body`, `bodyPreview`, `uniqueBody`, `attachments`, `bccRecipients` |
| **Incremental** | The `deltaLink`, stored as the source's resumption point |
| **Retention** | Nothing cached on disk beyond what becomes a record |

**Why the Sent Items folder rather than the whole mailbox**: FR-048 says only sent mail is recorded. Reading
that folder means received mail is never fetched at all, rather than fetched and thrown away. Less data
crosses the network, and the requirement holds even if the filtering code is wrong.

**Consent failure must be distinguishable.** `AADSTS65001` and an admin-approval response mean *your
organisation must approve this application* — a different action from "no credential" and from "expired".
FR-010 requires all four states to be told apart; [research R6](../research.md) explains why this one cannot
be predicted in advance.

---

## Gmail — `mail/gmail.py`

| | |
|---|---|
| **Destinations** | `oauth2.googleapis.com` (authorisation), `gmail.googleapis.com` (reading) |
| **Scope requested** | `https://www.googleapis.com/auth/gmail.metadata` |
| **Why that scope** | Headers and labels only — **no body, no attachments**. IMAP is not used because its only Gmail scope, `https://mail.google.com/`, also grants **send and delete**, which Principle II forbids holding at all. See [research R2](../research.md). |
| **Endpoints** | `users.messages.list` (`labelIds=["SENT"]`), `users.messages.get` (`format=metadata`, `metadataHeaders` naming the six headers), `users.history.list` for incremental runs |
| **Fields taken** | The `Message-ID`, `Date`, `From`, `To`, `Cc` and `Subject` headers |
| **Incremental** | `historyId`, stored as the resumption point |
| **Retention** | As above |

**Two consequences of the metadata scope**, both from [research R3](../research.md):

- **Search is unavailable**, so the `since` date is applied client-side on a first run. Every later run is
  driven by `historyId` and does not need search.
- **`format=metadata` cannot return a body even if asked.** The requirement is enforced by the API.

**Token expiry is expected, not exceptional.** Google expires refresh tokens from apps in Testing status
after 7 days ([research R4](../research.md)). On `invalid_grant` the account reports
`credential expired — re-authorise with 'ikwyd sources authorise NAME'`, other accounts still ingest, and
nothing already stored is lost.

---

## Hey — `mail/hey.py`, over `mail/hey_cli.py`

| | |
|---|---|
| **Destination** | None opened by us. The `hey` binary reaches Basecamp on its own account. |
| **Credential** | **None held.** `hey` keeps its own in the system keyring (file fallback `~/.config/hey-cli/credentials.json`) and refreshes it itself. |
| **Invoked** | `hey search --from <declared address> --date <range> --json`, paged with `--page` |
| **Fields taken** | `Message-ID`, `Date`, `From`, `To`, `Cc`, `Subject` from the search result |
| **Incremental** | Date-bounded: each run searches from the resumption point forward. The store deduplicates by `source_id`. |
| **Retention** | Nothing cached beyond what becomes a record |

### The allow-list is the mechanism

`hey` can send mail. `mail/hey_cli.py` is the only module that may invoke it, and it holds a frozen
allow-list, exactly as `git/binary.py` does:

```text
ALLOWED   = {"search", "box", "thread", "--version"}
FORBIDDEN = {"compose", "reply", "event", "setup", "tui", "watch"}   # never reachable
```

`compose` and `reply` are excluded because they write. `setup` is excluded because it changes the user's
configuration. `tui` and `watch` are excluded because they do not terminate. Anything not on the list raises
`HeyCommandNotAllowedError` rather than running — so a future author cannot reach `compose` without editing
the one file a reviewer checks.

**`thread read` is on the allow-list but is not used**, and that is a deliberate tension worth stating: it
renders whole threads as Markdown, **bodies included**. It is listed only because reading a thread is
legitimately read-only. If the connector ever needs it, FR-023 for Hey drops from *cannot receive a body* to
*must not store one* — a real weakening that must be argued for, not slipped in. See the unverified
assumption in [research R1](../research.md).

**If `hey` is absent, out of date, or not signed in**: that account reports it by name, with the command to
fix it, and every other source still ingests (FR-017). The binary is never assumed present — the same
treatment `git` gets.

---

## Exported archive — `mail/mbox.py`

| | |
|---|---|
| **Destinations** | none — a local file |
| **Credential** | none |
| **Read** | The file is opened **read-only**. It is never written, moved, renamed or truncated. |
| **Fields taken** | The same six headers, parsed with `email` |
| **Incremental** | None. Every run re-reads the file; the store deduplicates by `source_id`, so re-reading records zero new activities. |
| **Retention** | The file is the user's; the tool neither copies nor deletes it |

**Only the header block is parsed.** The body is present in the file and is never read into memory as
content — the reader takes the message's headers and moves to the next.

**Records from an archive are never withdrawable.** An export is one snapshot at one moment; exporting a
narrower range next month would make every message outside it look deleted. The payload therefore carries
`withdrawable: false`, which the store already honours — the same protection git branch creations needed,
for the same reason ([research R13](../research.md)).

**A fallback for every provider.** It is how mail older than a provider's history window is brought in,
and the route to take if a work tenant refuses Graph or if re-authorising Gmail weekly becomes tiresome.

---

## Rules every provider obeys

| Rule | How it is enforced |
|---|---|
| No write of any kind reaches a mail account | `SourceReader` has no write operation to call — Principle II at the type level, from `0002`. For Hey, additionally: the mutating subcommands are not on the allow-list. |
| No message is marked read | Neither scope grants it, and no endpoint used has that effect |
| No destination other than a configured account | Every request goes through `net/http.py`; an import test asserts nothing else opens a socket, and that `mail/hey_cli.py` is the only module importing `subprocess` |
| Rate limits respected | `net/http.py` honours `Retry-After` on 429/503, backs off from 1s, gives up after 5 attempts and fails that account only |
| A credential never reaches a log | `credentials/redaction.py`, and `net/http.py` never logs a header block |
| One account's failure never stops another | `0002`'s per-source isolation, unchanged |

## `net/http.py` — the only door

Every outbound request in this feature goes through one module, which:

- accepts a URL, a method restricted to `GET` and `POST`, headers, and an optional body;
- **refuses any host not on an allow-list** built from the configured accounts' kinds;
- logs the host and status, never the URL's query, never a header, never a response body;
- applies the retry policy above.

This mirrors `git/binary.py` from `0003`, where an allow-list of subcommands made "read-only" checkable by
review rather than promised by convention. A reviewer here needs to read one file to know every place this
tool can reach.
