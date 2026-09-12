# Contract: the credentials file, and what may be read from it

Extends `0002`'s credentials file. The file's location, permissions and exclusion from version
control are unchanged; what changes is that one key inside an entry now has a value the tool
reads.

## Location

Beside `config.toml`, as before — so `--config` selects a whole configuration rather than a file
whose secrets come from somewhere else.

## Shape

```toml
# Sent to Google's token endpoint when authorising and refreshing a Gmail account.
# Obtained from the Google Cloud console; it is NOT the same thing as client_id,
# which is public and lives in config.toml.
[credential.gmail-credentials]
client_secret = "GOCSPX-REPLACE-with-the-secret-from-your-OAuth-client"

# Microsoft 365 needs no secret. The entry must still exist, because a source
# names it and `sources validate` checks that the name is known.
[credential.ebp-credentials]
```

An entry with **no keys at all** remains valid. Presence of the name is what the existing
readiness check asks about, and that question is unchanged.

## Which kinds send it

| Kind | Sends `client_secret` | Why |
|---|---|---|
| `mail.gmail` | **Yes** | Google issues one to an `installed` client and its token endpoint requires it — observed, see [research R1](../research.md) |
| `mail.outlook` | **No** | PKCE exists so a public client holds no secret. Sending one would be a regression, and is asserted against |
| `mail.hey`, `mail.mbox` | **No** | No authorisation at all; they read a file |
| `git.local` | **No** | No authorisation at all |

This table is **declared on the source kind**, not written into the validator. `sources kinds`
prints it, `sources validate` checks against it, and the token exchange obeys it — one fact, one
place.

## Reading a value

| Rule | Behaviour |
|---|---|
| Addressing | By credential name and key |
| Registration | The value is registered for redaction **before** it is returned. Not the caller's job |
| Exclusivity | This is the only way to obtain a value from the file |
| Missing name, missing key, empty, whitespace-only | All indistinguishable — one "not there" outcome |
| File readable by other accounts | **Refused.** The message names the file and the remedy, and nothing is returned |
| Value below the redaction minimum (6 characters) | Returned, but not registered. A documented limit; no real OAuth secret is that short |

### Why reading a value refuses where checking a name only warns

The two questions disclose different things, so they are guarded differently — deliberately, and
recorded here so it is not "corrected" into consistency later:

| Question | File readable by others | Rationale |
|---|---|---|
| "Is this name known?" | Warning, as today | The answer reveals nothing. Refusing would break `sources list` and `sources validate` for anyone whose file is loose, and protect nothing |
| "What is this value?" | **Refusal** | Handing a secret out of a file that was just established to be world-readable is the one case where continuing makes things worse |

`tokens.toml` refuses on every read because it contains nothing but secrets. `credentials.toml`
answers both kinds of question, so it gets both kinds of answer.

## What the user is told

**A Gmail account with no secret** — before any browser opens (FR-007):

```
gmail-oderbolz needs a client secret

Add it to C:\Users\…\credentials.toml under [credential.gmail-credentials]:

    client_secret = "…"

Google issues one with the OAuth client. It is not the client_id, which is
already in your configuration.
```

**A secret where it will never be used** — a warning from `sources validate` (FR-006a):

```
WARN  credential.ebp-credentials  `mail.outlook` never sends a client secret
       → The value is ignored. Microsoft accounts sign in without one; you can remove it.
```

A warning, not an error: the source signs in correctly. What is wrong is the user's picture of
what they just did, and that is repaired by saying so once.

## What is never done

- The file is **never written** by this tool. `ikwyd init` creates it when absent, from a
  template of placeholders, and that is the whole of it (`0005`).
- There is **no command that opens it in an editor** (`0005` FR-027), and this feature does not
  change that reasoning.
- No value is ever printed, logged, returned in `--json`, or included in an error message.
- `config.toml` never holds a secret. The configuration validator already rejects an unknown
  setting, so `client_secret` there is an error, not a silent no-op.
