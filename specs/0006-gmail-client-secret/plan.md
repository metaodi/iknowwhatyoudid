# Implementation Plan: Reading a Secret, and Saying What Went Wrong

**Branch**: `0006-gmail-client-secret` | **Date**: 2026-09-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/0006-gmail-client-secret/spec.md`

## Summary

Gmail cannot be authorised at all: Google's token endpoint refuses the exchange without a
`client_secret`, which this tool has never sent. Fixing that means reading a credential **value**
for the first time — the credential store has only ever answered "is this name present?" — so the
work is almost entirely about where that new opening sits and what stops anything escaping
through it.

The approach, in one line each:

1. `CredentialStore` gains one general accessor, `value(name, key)`, which registers whatever it
   returns with the redaction filter **before** returning it (clarification Q1).
2. The Gmail token exchange and refresh send the secret; Microsoft's send nothing, asserted over
   the request actually made.
3. A credentials file others can read refuses a **value** read while leaving the presence check's
   warning exactly as it is (clarification Q2).
4. A secret in an entry whose kind never sends one produces a warning, driven by a declarative
   flag on `SourceKind` rather than a provider name in the validator (clarification Q3, research R6).
5. The three untested changes from the diagnosis get their tests, and the two `print` sites that
   bypass the redaction chokepoint get routed through it (research R4).

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: none added. Standard library only — `tomllib`, `urllib.request`

**Storage**: not touched. This feature opens no database

**Testing**: `pytest`, against fixtures and a substituted token endpoint. No test performs a live
sign-in, and none reads the developer's own mail

**Target Platform**: Windows, macOS, Linux

**Project Type**: single project — CLI

**Performance Goals**: not applicable. One extra dictionary lookup on a path that already makes an
HTTPS request

**Constraints**: no new network destination; no new dependency; no schema change; the log's
existing contract (host, method, status) unchanged

**Scale/Scope**: one accessor, one form field, one validator rule, two redaction fixes, and the
tests for all of it plus the three changes that arrived without any

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design. Both passes below.*

| Principle | How this feature satisfies it | Gate |
|---|---|---|
| **I. Local-First and Private by Default** (NON-NEGOTIABLE) | No new destination. `oauth2.googleapis.com` was declared by `0004` and is already in the allow-list; what changes is one field *sent to* it, not where anything goes. Nothing is sent anywhere else, and the secret reaches exactly one endpoint (FR-008). | **PASS** |
| **II. Read-Only at the Source** (NON-NEGOTIABLE) | No source is read or written differently. A client secret authenticates the *application*, not the user: the granted scope stays `gmail.metadata`, which cannot send, delete or modify. The feature widens no grant. | **PASS** |
| **III. Spec-Driven Development** (NON-NEGOTIABLE) | Specified, clarified (3 questions), planned here. **One debt is called out rather than hidden**: three behavioural changes were made during diagnosis without tests. FR-017 brings them under the rule instead of leaving them outside it. | **PASS, with a debt being settled** |
| **IV. Rebuildable Local Store** | Untouched. No schema change, no migration, no store access. | **PASS — not applicable** |
| **V. Transparent, Correctable Attribution** | Untouched. No attribution is made or changed. | **PASS — not applicable** |
| **VI. CLI-First with a Local Dashboard** | No new command. Two existing ones — `sources authorise` and `sources validate` — say more than they did. Both keep `--json`; the warning appears in the machine form as a finding like every other. | **PASS** |

### Technology and Data Constraints

| Constraint | Compliance |
|---|---|
| Python ≥ 3.12, `uv`, `mypy` clean | Unchanged |
| Single embedded database | Untouched — this feature does not open it |
| Connector behind a common interface | No connector added. The reader gains an injected dependency, matching the `use_config_path` setter it already has (research R3) |
| Standard library is the default; each dependency justified | **No dependency added** |
| **Credentials MUST NOT be committed, logged, printed, or written into the database** | The centre of the feature. FR-009 enumerates the six paths; research R4 found two that were genuinely unguarded and this plan closes them |
| Committed templates contain placeholders only | `credentials.toml.template` gains a commented `client_secret` line, placeholder only |
| No abstraction for a single anticipated caller | One accessor, one flag on an existing dataclass, no framework. The accessor is general **by the user's explicit decision** (Q1), with the compensating control written into FR-004 rather than left implied |

### Things a reviewer must be told about

The constitution requires a pull request to call these out explicitly:

1. **A credential value becomes readable in code for the first time.** This is the whole feature.
   `CredentialStore` has said since `0002` that it exposes no such method; it now does.
2. **A secret is sent to a network destination.** To `oauth2.googleapis.com` only, in the token
   exchange and refresh, for Gmail accounts only.
3. **No new destination, no new dependency, no schema migration, no write outside the tool's own
   directories.**
4. **A widened credential scope? No.** Explicitly checked: the OAuth scope is unchanged.

### The debt this settles

Three changes were made to the error path while the user was blocked, without the tests the
constitution requires of every behavioural change:

| Change | Test that must now exist |
|---|---|
| `net/http.py` carries the response body into `HttpStatusError` | A refusal's body reaches the caller; the log still records only host, method and status |
| `flow.py::_classify` includes that detail in its fallback | Each of the three refusal shapes produces the right message; the unclassified one shows the provider's words |
| `sources authorise` prints narration as it happens | The narration reaches stderr *before* the blocking call, and survives a failure in the exchange |

Recording them here rather than quietly writing the tests: the point of the rule is that the gap
was visible, and a plan that pretended the tests had always been there would defeat it.

## Project Structure

### Documentation (this feature)

```text
specs/0006-gmail-client-secret/
├── plan.md              # This file
├── research.md          # Phase 0 — R1 to R8
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── credential-file.md    # the shape of a credential entry, and what may be read from it
│   └── refusals.md           # what the user is shown when a provider says no
├── checklists/
│   └── requirements.md  # from /speckit-specify, 16/16
└── tasks.md             # NOT created by /speckit-plan
```

### Source Code (repository root)

```text
src/iknowwhatyoudid/
├── credentials/
│   ├── store.py              # CHANGED — gains value(name, key); presence check unchanged
│   └── redaction.py          # unchanged
├── auth/
│   └── flow.py               # CHANGED — client_secret in exchange and refresh; _classify tested
├── mail/
│   └── reader.py             # CHANGED — credential store injected, secret resolved for refresh
├── net/
│   └── http.py               # CHANGED — _refusal() now tested rather than merely written
├── kinds/
│   └── mail.py               # CHANGED — a declarative flag saying which kinds send a secret
├── config/
│   └── validate.py           # CHANGED — the unused-secret warning (FR-006a)
├── cli/
│   ├── mail_commands.py      # CHANGED — narration through redact(); secret resolved for exchange
│   ├── setup_commands.py     # CHANGED — the editor line through redact()
│   └── render.py             # unchanged — it is already the chokepoint
└── templates/
    └── credentials.toml.template   # CHANGED — a commented placeholder line

tests/
├── unit/
│   ├── test_credential_value.py    # NEW — the accessor, registration, and its limits
│   └── test_refusals.py            # NEW — classification of each refusal shape
└── integration/
    ├── test_gmail_authorise.py     # NEW — what the exchange carries, for both providers
    └── test_secret_containment.py  # NEW — the six paths, over every command
```

**Structure Decision**: the existing single-project layout, unchanged. Every file above already
exists except the four test files; this feature adds no module, because the thing it introduces is
a method on a class that is already the right home for it.

## Complexity Tracking

> Filled only where the Constitution Check needed a justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| A general `value(name, key)` accessor rather than a purpose-named one, against "no abstraction for a single anticipated caller" | The user chose it deliberately (clarification Q1) so a second secret later needs no second method | A purpose-named `client_secret(name)` would make the guarantee true by construction, which is why it was recommended. Since it was not chosen, the guarantee moves **inside** the accessor: FR-004 makes registration its own responsibility, FR-001a makes it the only path to a value, and FR-004a tests it with a key this feature never uses. The control is not weaker, it is just explicit rather than structural |

## Post-Design Constitution Re-check

Re-evaluated after Phase 1. No gate changed, and the design surfaced one thing worth recording:

**Research R4 found the constitution's own credential rule already had two unguarded exits** —
`print(..., file=sys.stderr)` in `cli/setup_commands.py` and `cli/mail_commands.py`, both added
within the last two days, neither passing through `render.py`. Neither prints a secret today, so
nothing has leaked. But this feature introduces the first value that must never be printed, and
adding it while leaving two unguarded exits open would be the wrong order. Closing them is
therefore part of this feature rather than a follow-up, and a boundary test keeps them closed.
