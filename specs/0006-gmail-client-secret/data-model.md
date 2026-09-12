# Data Model: Reading a Secret, and Saying What Went Wrong

No database entity changes. Nothing here is stored; everything is read from a file, held in
memory for the length of one HTTP request, and discarded.

---

## Credential entry

A named table in `credentials.toml`. It has existed since `0002`, where it established only that
a name was known. This feature gives it one readable key.

| Field | Type | Required | Notes |
|---|---|---|---|
| *(the table name)* | string | yes | What a source's `credential` setting refers to |
| `client_secret` | string | no | Sent to the token endpoint for kinds that need one. Absent, empty or whitespace-only are all equivalent to "not there" (FR-005) |
| *(any other key)* | string | no | Readable through the same accessor, registered for redaction like any other. Nothing reads one today |

**Validation**

- A `client_secret` on a kind that never sends one is a **warning**, not an error (FR-006a). The
  source still validates as ready, because it is.
- The file's permission is checked before any value is read, and a file others can read refuses
  the read (FR-003). Checking a *name* keeps today's warning (FR-003a).

**State transitions**: none. The file is never written by this tool.

---

## Credential value access

Not an entity so much as the one doorway this feature cuts, described here because its contract
is the feature.

| Property | Rule |
|---|---|
| Addressing | By credential name and key |
| Registration | Every returned value is registered with the redaction filter **before** it is returned (FR-004). The caller cannot forget, because the caller is never given the chance |
| Exclusivity | It is the only way to obtain a value. No other path returns one, and no caller reaches the parsed document directly (FR-001a) |
| Absence | Absent name, absent key, empty value and whitespace-only value are one outcome, not four (FR-005) |
| Permission | Refuses when the file is readable by others, before returning anything (FR-003) |
| Known limit | A value shorter than the redaction filter's minimum is returned but **not** registered (research R5). No real OAuth secret is that short; the contract says registration is attempted, not that it is guaranteed |

---

## Source kind

Extended by one field so the validator need not know provider names (research R6).

| Field | Type | Notes |
|---|---|---|
| `sends_client_secret` | bool | Whether this kind's token exchange carries a client secret. `mail.gmail` only. Drives both FR-006 (what is sent) and FR-006a (the warning), so the two can never disagree |

Every other field is as `0004` left it.

---

## Provider refusal

What comes back when a token endpoint says no. Previously the status survived and the words were
discarded, which made the classification that depends on those words unreachable.

| Field | Type | Notes |
|---|---|---|
| `status` | int | As before |
| `host` | string | As before |
| `detail` | string | **New in practice** — the constructor always accepted it; nothing ever passed it. Bounded to 500 characters (research R7) |

**Classification**, unchanged in shape and now actually reachable:

| Input | Outcome |
|---|---|
| A recognised consent marker | An administrator must approve; re-authorising will not help |
| A recognised expiry marker | Sign in again |
| Anything else | The provider's own words, verbatim (FR-014) |

**What never enters this object**: the request. The refusal carries what the provider said, not
what was sent — so a secret cannot arrive here by that route. Should a provider echo one back in
its own message, the redaction filter masks it on the way out (FR-011), which is why registration
happens at read time rather than at send time.
