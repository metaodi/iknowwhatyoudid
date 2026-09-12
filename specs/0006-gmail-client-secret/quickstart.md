# Quickstart: validating the client secret and the refusal path

How to prove this feature works. **No test performs a live sign-in**, reads the developer's mail,
or contacts a provider. The token endpoint is substituted and what it received is asserted, which
is the only way to check "Microsoft carries no secret" at all — you cannot prove absence by
watching a request succeed.

## Prerequisites

```bash
uv sync
uv run mypy src tests      # must be clean
uv run pytest              # must be green
```

---

## Scenario 1 — the accessor, and what it registers (US1, FR-001, FR-004, FR-005)

```bash
uv run pytest tests/unit/test_credential_value.py -v
```

| Assertion | Requirement |
|---|---|
| A value is returned by credential name and key | FR-001 |
| It is registered for redaction **before** it is returned — asserted by observing the order, not the end state | FR-004 |
| A value under a key this feature never uses is registered too | FR-004a |
| Missing name, missing key, empty, and whitespace-only produce one identical outcome | FR-005 |
| A value below the redaction minimum is returned but not registered, and the contract says so | research R5 |
| No other method on the store returns a value — walked over the public surface | FR-001a |

The order assertion is the one worth writing carefully. Registering before returning and
registering after returning look identical from outside; what differs is whether a caller can
obtain a value that is not yet maskable. Same shape as `0005`'s permissions-before-content test.

## Scenario 2 — a file others can read (US2, FR-003, SC-011)

```bash
uv run pytest tests/unit/test_credential_value.py -k permission -v
```

| Given | Expected |
|---|---|
| A world-readable credentials file, reading a **value** | Refused, naming the file and the remedy, before any network request |
| The same file, checking a **name** | Today's warning, unchanged — `sources list` and `sources validate` still work |

The second row is a regression test for a deliberate inconsistency ([contracts/credential-file.md](./contracts/credential-file.md)).
Without it, someone tidying the two paths into agreement would break `sources list` for every user
whose file is loose, and would look right doing it.

## Scenario 3 — what each provider's exchange carries (US1, FR-006, FR-008, SC-002)

```bash
uv run pytest tests/integration/test_gmail_authorise.py -v
```

| Given | Expected |
|---|---|
| A Gmail account with a secret | The exchange carries `client_secret` |
| A Gmail account with a secret | The **refresh** carries it too |
| A Microsoft account | The exchange carries **no** `client_secret` |
| A Microsoft account **whose entry holds one anyway** | Still none. A secret in the wrong entry must not enter the flow |
| Any request that is not to a token endpoint | Carries no secret |

Row four is the one that would be easy to leave out and is the reason SC-002 says "asserted over
the request actually made rather than over the code that makes it".

## Scenario 4 — a Gmail account with no secret (US1, FR-007, SC-004)

```bash
uv run pytest tests/integration/test_gmail_authorise.py -k missing -v
```

Fails **before a browser opens**, naming the file, the entry and the key. Asserted by observing
that the browser was never invoked, not merely that the command exited non-zero — a message that
arrives after a browser window has already appeared has not saved anyone anything.

## Scenario 5 — the secret reaches none of the six paths (US2, FR-009, SC-003)

```bash
uv run pytest tests/integration/test_secret_containment.py -v
```

A known value is placed in a credentials file and every command in the tool is run against it —
succeeding **and** failing — while stdout, stderr, the log file and the `--json` payload are
captured. The value appears in none of them.

| Path | Covered by |
|---|---|
| stdout | the capture |
| stderr | the capture |
| `--json` | the same run with `--json` |
| the log | reading the log file afterwards |
| an error message | a command forced to fail while the value is loaded |
| a traceback | an exception raised deliberately with the value in scope |

Plus the AST check from [research R4](./research.md): **no module under `cli/` may print to a
user-facing stream without going through the redaction chokepoint.** Two sites did when this
feature began, both added in the preceding two days, and the test is what stops a third appearing.

## Scenario 6 — refusals say something useful (US3, FR-012 to FR-015, SC-005)

```bash
uv run pytest tests/unit/test_refusals.py -v
```

| The provider says | The user is told |
|---|---|
| A consent marker | An administrator must approve; re-authorising will not help |
| An expiry marker | Sign in again |
| `{"error": "invalid_request", "error_description": "client_secret is missing."}` | That text, verbatim |
| Nothing at all | The host and status, which is still more than nothing |
| 900 characters of HTML | Truncated to 500 |

The third row uses the **actual response** that produced this feature, so the test fails if the
classification regresses to the state that made this bug take a day to find.

## Scenario 7 — the log still says only what it always said (FR-010)

```bash
uv run pytest tests/unit/test_refusals.py -k log -v
```

The body now reaches the user. It must **not** reach the log, which persists and gets shared. The
test asserts the log line is still `host=… method=… status=…` and contains no fragment of the
response.

## Scenario 8 — narration arrives before the wait (US3, FR-016, SC-006)

```bash
uv run pytest tests/integration/test_gmail_authorise.py -k narration -v
```

Asserted by **ordering**, not by presence: the narration must be on stderr before the blocking
call is entered, and must still be there after the exchange raises. Presence alone would pass
against the old behaviour, which printed everything at the end and discarded it on failure.

## Scenario 9 — a secret that will never be sent (FR-006a, SC-010)

```bash
uv run pytest tests/integration/test_gmail_authorise.py -k unused -v
```

A `client_secret` in a Microsoft entry produces exactly one warning naming the entry, and the
source **still validates as ready**. Both halves are the assertion: warning present, readiness
unaffected.

## Scenario 10 — by hand, against the real account

The only step that touches a live provider, run by a person and not by the suite:

```bash
ikwyd sources authorise gmail-oderbolz
ikwyd sources validate
ikwyd ingest --source gmail-oderbolz
```

Expected: sign-in completes, `tokens.toml` appears, `ingest` reads sent mail. The `ingest` is what
exercises the refresh path, which is the one thing [research R1](./research.md) could not verify
in advance.

---

## Known limits at the end of this feature

1. **Google's 7-day refresh-token expiry** while the consent screen is in Testing status. A policy
   matter no implementation fixes (`0004` research R4). Re-authorising weekly, or exporting
   instead, are the only two answers.
2. **The refresh's need for the secret is assumed, not observed.** Sending it is harmless if
   unnecessary; if Google wants something further, Scenario 10 is where that appears, and it will
   now appear in Google's own words.
3. **A secret shorter than six characters is not masked.** A documented limit of the redaction
   filter, not of this feature. No real OAuth secret is that short.
4. **`credentials.toml` still has no `edit` command.** Deliberate (`0005` FR-027); `init` prints
   the path and `sources validate` names the file whenever something is missing from it.
