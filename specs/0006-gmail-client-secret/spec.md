# Feature Specification: Reading a Secret, and Saying What Went Wrong

**Feature Branch**: `006-gmail-client-secret`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "Gmail's token endpoint requires a `client_secret` that this tool never sends, so `ikwyd sources authorise` fails for every Gmail account with `invalid_request: client_secret is missing.` … This requires reading a credential VALUE for the first time."

## Why this feature exists

Gmail cannot be authorised at all today. Run against a real Google account on 2026-09-12:

```
Waiting for the redirect on http://127.0.0.1:52876/ …
authorisation was refused — oauth2.googleapis.com answered 400: {
  "error": "invalid_request",
  "error_description": "client_secret is missing."
}
```

The OAuth round-trip itself works — the browser redirect arrives, the code is received, the
loopback handler serves its page. What fails is the exchange of that code for a token, because
Google's `installed` application type is issued a client secret and its token endpoint requires
one, while this tool sends only `client_id` and `code_verifier`. That is correct for Microsoft,
where PKCE exists precisely so a public client holds no secret, and wrong for Google.

The narrower point, and the reason this is a feature rather than a patch: the tool has never
read a credential **value**. `CredentialStore` answers one question — is this name present? — and
says so in as many words:

> There is deliberately no method returning a value. A future feature that must actually
> authenticate adds one behind this boundary; until then the type cannot leak what it does
> not expose.

This is that feature. The boundary is the design question; sending one more form field is not.

### The three fixes that found this, and the tests they never got

Diagnosing the failure above required three changes to the error path, made while the user was
blocked and **without the tests the constitution requires of every behavioural change**. They
are in scope here because they are the same error path, and because leaving them untested would
mean this feature's own error messages rest on code nothing checks.

| Changed | Was | Consequence |
|---|---|---|
| `net/http.py` | The response body of a refused request was read and discarded; `HttpStatusError` was raised with no detail | Every marker in `_CONSENT_MARKERS` and `_EXPIRED_MARKERS` matched against the string `"host answered 400"` and could never fire. The whole classification in `flow.py` was dead code |
| `flow.py::_classify` | The fallback branch discarded the detail entirely | The one case where the tool cannot classify a refusal — and therefore the one case where the provider's own words are all the user has — produced `"authorisation was refused"` and nothing else |
| `cli/mail_commands.py` | `authorise` accumulated its narration and rendered it only in the final result | Nothing appeared during a wait of up to five minutes, and when the exchange raised, the entire account of what had happened was discarded with the result |

## Clarifications

### Session 2026-09-13

- Q: When the tool reads a secret out of the credentials file, should that be a method that can
  only ever return the client secret, or a general one that can return any value stored under a
  credential? (FR-001) → A: A general accessor taking a credential name and a key.

  **Consequence, recorded because it shifts where the guarantee lives.** A purpose-named
  accessor would have made "only the client secret can be extracted" true by construction. A
  general one cannot, so containment has to be enforced *inside* the accessor rather than
  implied by its narrowness: FR-004 now requires it to register every value it returns with the
  redaction filter before returning it, whatever key was asked for, so no caller can obtain an
  unregistered value even by accident. FR-004a adds the test that holds this in place.

- Q: Once the tool actually reads secrets out of the credentials file, should a world-readable
  file refuse everywhere, or only where a value is being read? (FR-003) → A: Refuse only when a
  value is read; the presence check keeps today's warning.

  This deliberately leaves the two files behaving differently on the same condition, and the
  difference is justified rather than accidental: `tokens.toml` refuses on every read because it
  contains nothing *but* secrets, while the credentials file is also consulted for a question —
  "is this name known?" — whose answer discloses nothing. Refusing that question would break
  `sources list` and `sources validate` for anyone whose file is loose today, while protecting
  nothing. FR-003a records the split so a later reader does not "fix" it into consistency.

- Q: If someone pastes a client secret into the credential entry of a Microsoft 365 account,
  where the tool will correctly refuse to send it, should the tool say something or ignore it
  silently? (FR-006) → A: Ignore it, and warn from `sources validate` naming the entry.

  A warning rather than an error, because the source itself is not broken — it signs in exactly
  as it should. What is broken is the user's model of what they just did, and that is repaired
  by saying so once (FR-006a, SC-010).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Authorising a Gmail account at all (Priority: P1)

A user with a Google OAuth client for a desktop application puts its client secret in the file
the tool already keeps secrets in, runs `ikwyd sources authorise`, signs in once, and the
account is authorised.

**Why this priority**: without it Gmail does not work. Every other part of the Gmail connector —
the reader, the metadata scope, the label handling, the de-duplication — was built in `0004` and
cannot be reached, because authorisation is the first step and it fails every time.

**Independent Test**: with a substituted token endpoint asserting what it received, run
`sources authorise` for a Gmail account whose credential carries a secret, and verify the
exchange carries it. Then assert the same request for a Microsoft account carries none.

**Acceptance Scenarios**:

1. **Given** a Gmail source whose credential entry carries a client secret, **When** the user
   completes sign-in, **Then** the token exchange includes that secret and the account is
   authorised
2. **Given** a Microsoft 365 source, **When** the user completes sign-in, **Then** the token
   exchange carries **no** secret, whether or not one happens to sit in the credential entry
3. **Given** a Gmail source whose credential entry carries **no** client secret, **When** the
   user runs `sources authorise`, **Then** the command names the file, the entry and the key to
   add, and no browser is opened
4. **Given** an authorised Gmail account whose access token has expired, **When** the tool
   refreshes, **Then** the refresh request carries the secret too

---

### User Story 2 - A secret that cannot leak (Priority: P1)

The value is read, used in one HTTP request, and is visible nowhere else — not on screen, not in
`--json`, not in the log, not in an error message, not in a traceback.

**Why this priority**: equal first with US1, and inseparable from it. Reading a credential value
is the thing this feature introduces, so the containment of that value is not a refinement of
the feature — it is the feature. Shipping US1 without US2 would be shipping the risk without the
control.

**Independent Test**: capture every stream and the log across every command that can touch a
Gmail credential, including failing ones, and assert a known secret value appears in none of
them.

**Acceptance Scenarios**:

1. **Given** a credential holding a known secret, **When** any command runs — succeeding or
   failing — **Then** that value appears in no line of stdout, stderr, the log, or `--json`
2. **Given** a provider that refuses with a body echoing part of the request, **When** the
   refusal is shown to the user, **Then** any known secret within it is masked
3. **Given** a credentials file readable by others, **When** the tool would read a value from
   it, **Then** it refuses and says so, rather than reading it anyway
4. **Given** an unexpected failure while a secret is in memory, **When** a traceback reaches the
   user, **Then** the value does not appear in it

---

### User Story 3 - Being told what the provider actually said (Priority: P2)

When a provider refuses, the user sees the provider's own words, and the tool's interpretation
when it has one.

**Why this priority**: below the two above because it is diagnosis rather than function — but it
is what turned a week of guessing into a definite answer, and without it US1 could not have been
specified correctly. The cost of omitting it is not a broken feature; it is every future
authorisation failure being un-diagnosable in the same way.

**Independent Test**: drive each refusal shape through the classifier — consent required,
expired grant, and an unrecognised one — and assert what the user is shown.

**Acceptance Scenarios**:

1. **Given** a provider refusing with a recognised consent marker, **When** the tool reports it,
   **Then** it says an administrator must approve, and that re-authorising will not help
2. **Given** a provider refusing with a recognised expiry marker, **When** the tool reports it,
   **Then** it says to sign in again
3. **Given** a provider refusing with anything else, **When** the tool reports it, **Then** the
   provider's own message is shown verbatim, because the tool has nothing better to offer
4. **Given** a command that blocks waiting for a browser, **When** it is waiting, **Then** the
   user has already been told what is being asked for and where the redirect will arrive

### Edge Cases

- A credential entry holding a secret for a **Microsoft** account: the value must be ignored,
  not sent — a secret that does not belong in a flow must not enter it because someone pasted it
  into the wrong entry — **and the user must be told it is being ignored** (FR-006a). Silence
  here would leave a real secret sitting on disk, unused, with no hint as to why nothing changed.
- A secret that is present but empty, or only whitespace: treated as absent, so the user gets
  the message naming what to add rather than a 400 from Google.
- A credentials file that is unreadable or malformed **at the moment of the exchange**, having
  been readable when the source was validated.
- A provider response body that is very large, or is HTML rather than JSON: the user must get
  something bounded and legible, not a page of markup.
- A provider response body that contains **no** recognisable error at all — for instance an
  empty body with a 400.
- A refresh that fails for an account authorised before this feature existed, whose stored token
  predates any secret being recorded.

## Requirements *(mandatory)*

### Functional Requirements

**Reading the value**

- **FR-001**: The tool MUST be able to read a value stored under a named credential, addressed
  by credential name and key. One accessor serves every key, so a second secret later needs no
  second method.
- **FR-001a**: That accessor MUST be the **only** way any credential value can be obtained. No
  other path may return one, and no caller may reach the parsed file directly.
- **FR-002**: A client secret MUST live in the credentials file, inside the credential entry the
  source already names. It MUST NOT be accepted in the configuration file.
- **FR-003**: The permission of the credentials file MUST be checked **before** any value is
  read from it, and a file readable by others MUST cause a refusal rather than a read.
- **FR-003a**: That refusal applies to reading a **value** only. Checking whether a credential
  name is present MUST keep today's behaviour — a warning naming the file and what to do —
  because the presence check reveals nothing, and a command that works today must not stop
  working because a different command now reads more.
- **FR-003b**: The refusal MUST name the file and the remedy, and MUST occur before any network
  request is made, so a file nobody has restricted yet never reaches a provider.
- **FR-004**: Every value the accessor returns MUST be registered with the redaction filter
  **before it is returned**, whatever key was requested. Registration is the accessor's own
  responsibility, never the caller's: a general accessor cannot rely on its narrowness to keep
  values contained, so it has to do the containing itself.
- **FR-004a**: A value obtained under **any** key — not only the client secret — MUST be masked
  wherever it would otherwise be shown, asserted for a key this feature does not itself use.
- **FR-005**: A value that is absent, empty, or only whitespace MUST be treated identically to
  one that was never there.

**Using it**

- **FR-006**: The client secret MUST be sent in the token exchange and in the refresh request
  for Gmail accounts, and MUST NOT be sent for Microsoft 365 accounts under any circumstance,
  including when one is present in the credential entry.
- **FR-006a**: A client secret present in the credential entry of a source kind that never sends
  one MUST produce a **warning** naming the entry and saying the value is not used for that kind.
  It MUST NOT be an error: the source signs in correctly, so refusing to run would be
  disproportionate to a mistake that costs nothing but the user's understanding.
- **FR-007**: A Gmail account with no client secret MUST fail **before** a browser is opened,
  naming the file, the entry, and the key to add.
- **FR-008**: No other request made by the tool may carry the secret. It belongs to the token
  endpoint and nowhere else.

**Containment**

- **FR-009**: No credential value may appear in stdout, stderr, the machine-readable form, the
  log, an error message, or a traceback.
- **FR-010**: The log's existing contract — host, method and status, and nothing else — MUST NOT
  change. In particular, response bodies MUST NOT be logged.
- **FR-011**: Any provider message shown to the user MUST pass through the redaction filter
  first.

**Saying what happened**

- **FR-012**: When a provider refuses a request, its own response MUST be available to whatever
  reports the refusal to the user.
- **FR-013**: The provider's response MUST be bounded in length before being shown.
- **FR-014**: A refusal the tool cannot classify MUST show the provider's own message rather
  than a generic one.
- **FR-015**: A refusal the tool **can** classify MUST continue to say what to do about it —
  administrator consent, or signing in again — as it does today.
- **FR-016**: A command that blocks waiting for a person MUST print what it is doing **before**
  it blocks, and that account MUST survive a subsequent failure rather than being discarded with
  the result.

**The debt this feature settles**

- **FR-017**: Each of the three changes listed in *Why this feature exists* MUST gain the test
  that should have accompanied it, including one asserting that a known credential value reaches
  no log line and no error message.

### Key Entities

- **Credential entry**: a named table in the credentials file. Today it establishes only that a
  name is known; this feature gives it one readable value, the client secret, while leaving the
  presence check that every source kind already relies on unchanged.
- **Provider refusal**: a status and the provider's own words. Previously the words were
  discarded and only the status survived; both are needed, because a single status covers
  several unrelated causes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with a Google desktop OAuth client can authorise a Gmail account, from a
  fresh configuration, without editing any file the tool did not tell them to edit.
- **SC-002**: 0 requests to any Microsoft endpoint carry a client secret, asserted over the
  request actually made rather than over the code that makes it.
- **SC-003**: 0 occurrences of a known credential value across stdout, stderr, the log and the
  machine-readable form, measured over every command in the tool, including failing ones.
- **SC-004**: A Gmail account missing its secret is told what to add, where, and under which
  entry — in one message, before any browser opens.
- **SC-005**: 100% of provider refusals reach the user carrying either the tool's interpretation
  or the provider's own words; 0 produce a message that carries neither.
- **SC-006**: A user waiting on a browser sees what is being requested and where the redirect
  will arrive **before** the wait begins, not after it ends.
- **SC-007**: Each of the three untested changes has a test that fails if the change is reverted.
- **SC-008**: 0 network destinations are added. The feature contacts exactly what `0004` already
  declared.
- **SC-009**: The credentials file is never written by this feature — 0 commands modify it.
- **SC-010**: A secret placed in an entry whose source kind never sends one is reported exactly
  once, as a warning, and the source still validates as ready.
- **SC-011**: A credentials file readable by other accounts stops a value from being read, and
  does so before any request leaves the machine — while leaving every command that only checks
  for a name working as it does today.

## Assumptions

- **Google's requirement is settled, not guessed.** `client_secret is missing.` was returned by
  `oauth2.googleapis.com` for this exact flow on 2026-09-12, with a client registered as
  `installed`. This feature is built against an observed response, not a reading of the
  documentation.
- **The loopback host question is answered.** The registered redirect was `http://localhost`
  while the tool used `http://127.0.0.1:<port>`, and the exchange was reached, so Google treats
  them as equivalent for this client type. No redirect change is needed, and the uncertainty
  recorded when Gmail was first configured can be closed.
- **Microsoft needs no secret and must not be given one.** Its flow works as shipped; this
  feature's Microsoft-facing requirement is entirely negative.
- **One secret, one provider.** Only Gmail needs this. The design should not generalise to a
  credential store that hands out arbitrary values, because the only thing keeping values
  contained today is that there is no way to get one.
- **The user obtains the secret themselves.** The tool never requests, generates, or displays
  one, and continues not to create the credentials file's contents.

## Out of Scope

- **Google's 7-day refresh-token expiry** for applications in Testing consent status. Recorded
  in `0004` research R4 as a policy matter that no implementation resolves; a user who would
  rather not re-authorise weekly exports instead.
- **Any change to the Microsoft 365 flow**, beyond asserting that it continues to send no secret.
- **A command that opens the credentials file in an editor.** `0005` FR-027 refused this
  deliberately and nothing here changes the reasoning; handing a file of secrets to whatever
  `$EDITOR` names is still a risk with no matching benefit.
- **Storing the secret anywhere new.** It goes in the file that already holds secrets, is
  already permission-checked, and is already excluded from version control.
