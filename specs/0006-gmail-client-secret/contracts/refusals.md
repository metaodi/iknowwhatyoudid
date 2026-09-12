# Contract: what the user is shown when a provider says no

Amends `0004`, which specified this classification but shipped it unreachable: the response body
was read and discarded, so every marker matched against the string `"host answered 400"` and none
could ever fire. This contract is what that one was meant to be.

## The rule

A refusal reaches the user carrying **either** the tool's interpretation **or** the provider's own
words. Never neither (SC-005).

| The provider said | The user is told | Exit |
|---|---|---|
| A recognised consent marker (`AADSTS65001`, `admin_consent_required`, …) | An administrator must approve this application; re-authorising will not help | non-zero |
| A recognised expiry marker (`invalid_grant`, `AADSTS70008`, …) | The stored authorisation was rejected; sign in again | non-zero |
| Anything else | `authorisation was refused — <the provider's own message>` | non-zero |
| Nothing — an empty body | `authorisation was refused — <host> answered <status>` | non-zero |

The third row is the one that matters most, and is the one that was missing. It is reached exactly
when the tool does **not** understand the refusal, which makes it the case where swallowing the
provider's words leaves the user with nothing — and leaves the next maintainer with no marker to
add.

Worked example, from the failure that produced this feature:

```
authorisation was refused — oauth2.googleapis.com answered 400: {
  "error": "invalid_request",
  "error_description": "client_secret is missing."
}

The text above is the provider's own. If it names a missing parameter, the
application registration and this tool disagree about the flow; if it names
the grant, run `ikwyd sources authorise NAME` to sign in again.
```

## Bounds

| Rule | Value |
|---|---|
| Maximum length of a provider message shown | 500 characters, as a named constant |
| Decoding | UTF-8, replacing anything undecodable. A provider that answers in something else must not produce a crash |
| Body unreadable | Treated as empty. The status still says something |

500 because an OAuth error body is a short JSON object — the one above is 78 characters. Anything
appreciably longer is an HTML error page, and a page of markup in a terminal helps nobody.

## What the log records

**Unchanged, and this is a requirement rather than an accident** (FR-010):

```
2026-09-12 16:22:44,075 INFO  http host=oauth2.googleapis.com method=POST status=400
```

Host, method, status. **Never the body**, never the query, never a header. The body now reaches
the *user*, through the redaction chokepoint; it does not reach the log, which is a file that
persists and which nobody re-reads before sharing.

## Redaction

Every provider message shown to the user passes through the redaction filter first (FR-011). A
provider that echoes part of the request back — some do, in validation errors — cannot thereby
print a secret, because the secret was registered when it was read, before it was ever sent.

This is why registration happens at **read** time rather than at **send** time: by the time a
response is being rendered, the code that sent the request is long gone.

## Narration before a blocking call

`sources authorise` waits up to five minutes for a browser round-trip. What it is doing is printed
to stderr **before** the wait begins (FR-016), not gathered into the final result:

```
Signing in to Gmail for gmail-oderbolz.
  Requesting: gmail.metadata — read message headers and labels, never a body or an attachment.
  Requesting: This grant cannot send, delete, or modify anything.
Waiting for the redirect on http://127.0.0.1:52876/ …
```

Held back to the end, this arrives after the wait it was describing, and is discarded entirely if
the exchange then fails — leaving an error with no account of what led to it. That is exactly what
happened while diagnosing this feature's own bug.

Like every other user-facing stream, it goes through redaction. The sign-in URL carries the
`client_id`, which is public by construction — but the guarantee is that the chokepoint has no
bypasses, not that each individual bypass happens to be harmless today.
