# Phase 1 Data Model: Configurable Sources

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

All types are frozen dataclasses unless noted. Nothing here is persisted by this feature — the
configuration is read from a file on every invocation, and the only durable state is reached through
[contracts/source-state.md](./contracts/source-state.md).

---

## SourceConfiguration

The whole configuration file, parsed. Corresponds to the spec's *Source Configuration* entity.

| Field | Type | Notes |
|-------|------|-------|
| `path` | `Path` | Where it was read from — reported in diagnostics, never assumed to be the default. |
| `raw_text` | `str` | Retained for the best-effort line locator (D2). Never re-parsed, never written back. |
| `sources` | `tuple[ConfiguredSource, ...]` | In file order; order is preserved in all output so it matches what the user sees in their editor. |
| `permission_status` | `PermissionStatus` | Result of the FR-006 check on this file. |

**Validation rules**

- Unknown top-level keys are a **blocking** finding, not a warning — a misspelled section is a source the
  user believes is configured and that would be silently skipped (spec Assumptions: refuse rather than
  ignore).
- A top-level key named `projects`, `attribution`, or `mapping` is a **blocking** finding naming FR-041
  explicitly: project mapping does not live here.
- Zero sources is valid and reports an empty list (FR-005).

---

## ConfiguredSource

One declared source. Corresponds to the spec's *Configured Source* entity.

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | User-assigned. Unique within the file (FR-007) and the source's identity in the store (FR-008). |
| `kind` | `str` | A registered kind name, e.g. `git.local`, `mail.gmail`, `fixture`. |
| `enabled` | `bool` | Defaults to `true`. |
| `since` | `datetime \| None` | Earliest point to read from (FR-038). Timezone-aware; TOML parses this natively. |
| `credential` | `CredentialReference \| None` | Present only if the kind requires one. |
| `settings` | `Mapping[str, object]` | Kind-specific, validated against that kind's `SettingSpec` sequence. |
| `index` | `int` | Position in the file, for key paths like `source[2]`. |

**Validation rules**

| Rule | Severity | Requirement |
|------|----------|-------------|
| `name` non-empty, and matches `[A-Za-z0-9][A-Za-z0-9._-]*` | blocking | FR-007, FR-008 — the name becomes a store identifier, so it must be usable as one |
| `name` unique across the file | blocking | FR-007 |
| `kind` is registered | blocking, but **non-fatal for other sources** | FR-029 — remaining sources still validate |
| `since` is timezone-aware and not in the future | blocking / warning | Naive datetime blocks; a future date warns |
| Every required `SettingSpec` present | blocking | FR-027 |
| No setting outside the kind's declaration | blocking | Refuse rather than ignore |
| Each setting's value matches its declared type | blocking | FR-027 |
| `credential` present iff the kind declares one | blocking | FR-020 |
| No value looks like an inline secret | warning | FR-023, D8 |

**Derived, not stored**: `ready` is computed per run from the source's findings, its credential presence,
and its kind's reading availability. It is never written to the configuration.

---

## SourceKind

A category of source. Corresponds to the spec's *Source Kind* entity, and is the extension boundary
(FR-026 to FR-032). Full contract in [contracts/source-kind.md](./contracts/source-kind.md).

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | Dotted, e.g. `mail.outlook`. Stable; it appears in users' files. |
| `summary` | `str` | One line, shown by `sources kinds`. |
| `settings` | `tuple[SettingSpec, ...]` | The declaration. Enumerable and printable (FR-028, FR-032). |
| `credential_required` | `bool` | |
| `required_access` | `tuple[str, ...]` | Human-readable scope statements, shown before the user grants anything (FR-025). |
| `destinations` | `tuple[str, ...]` | Every network destination this kind may contact; `()` for purely local kinds. Drives `sources destinations` (FR-045, SC-010). |
| `reading` | `ReadingAvailability` | `AVAILABLE` or `NOT_YET_IMPLEMENTED`. |

**Why `reading` exists**: under FR-033 this feature ships `git.local`, `mail.*`, and `calendar.*` as
declarations with no reader. Without this field the tool would either hide those kinds (breaking FR-035 to
FR-037, which require the configuration to express them) or claim a source is ready and then fail at
ingest. The field lets validation say *"configuration valid; reading arrives in a later release"* — a
distinction the spec's bias toward reporting gaps requires.

---

## SettingSpec

One accepted setting within a kind's declaration.

| Field | Type | Notes |
|-------|------|-------|
| `key` | `str` | Dotted path within the source block, e.g. `folders.include`. |
| `type` | `SettingType` | `STRING`, `BOOL`, `INTEGER`, `DATETIME`, `STRING_LIST`, `PATH_LIST`, `IDENTITY_LIST`. |
| `required` | `bool` | |
| `default` | `object \| None` | |
| `help` | `str` | Shown by `sources kinds`; this is the user-facing documentation of the setting. |

`PATH_LIST` and `IDENTITY_LIST` are distinct from `STRING_LIST` because validation differs: paths are
expanded (`~`, globs) and checked for existence, identities are normalised for comparison. The semantic
tag lives in the declaration rather than in the validator, which is what lets a future external kind get
the same treatment without the validator knowing about it (FR-032).

---

## CredentialReference

Corresponds to the spec's *Credential Reference* entity. **Carries a name, never a value** — the type has
no field capable of holding a secret, so a credential cannot leak through it by mistake.

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | The key looked up in the credential store. |

Resolved to a `CredentialPresence` — `PRESENT`, `ABSENT`, or `UNREADABLE` — and nothing else (D6, FR-021).

---

## Finding

Corresponds to the spec's *Validation Finding* entity. The single output type of validation.

| Field | Type | Notes |
|-------|------|-------|
| `severity` | `Severity` | `BLOCKING` or `WARNING` (FR-017). |
| `code` | `str` | Stable, e.g. `duplicate-source-name`, `unknown-kind`, `inline-secret`. Tests and `--json` consumers key on this, never on message text. |
| `source_name` | `str \| None` | `None` for file-level findings. |
| `key_path` | `str \| None` | e.g. `source[2].folders.include` (FR-016, D2). |
| `line` | `int \| None` | Best-effort (D2). Never asserted on in tests. |
| `message` | `str` | Plain statement of what is wrong. |
| `remedy` | `str \| None` | What to do about it — how to supply a missing credential, which kinds exist. |

**Ordering**: file-level findings first, then per source in file order, blocking before warning within
each group. Deterministic, so output is diffable across runs.

---

## SourceStatus

The per-source result of validation — what `sources list` and `sources validate` report (FR-015).

| Field | Type | Notes |
|-------|------|-------|
| `name`, `kind`, `enabled` | | From the configuration. |
| `readiness` | `Readiness` | See states below. |
| `credential` | `CredentialPresence \| None` | |
| `findings` | `tuple[Finding, ...]` | Those scoped to this source. |
| `destinations` | `tuple[str, ...]` | From the kind. |

### Readiness states

```text
                    ┌────────────────────────────────────────────┐
                    │ configuration parsed                        │
                    └────────────────────┬───────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              │                          │                          │
        blocking finding           kind unknown              no blocking finding
              │                          │                          │
              ▼                          ▼                          │
        ┌───────────┐            ┌──────────────┐                   │
        │  INVALID  │            │UNKNOWN_KIND  │                   │
        └───────────┘            └──────────────┘                   │
                                                                    │
                          ┌─────────────────────────────────────────┤
                          │                                         │
                    enabled = false                           enabled = true
                          │                                         │
                          ▼                     ┌───────────────────┼───────────────────┐
                   ┌────────────┐               │                   │                   │
                   │  DISABLED  │      credential ABSENT    reading NOT_YET       otherwise
                   └────────────┘               │            IMPLEMENTED               │
                                                ▼                   ▼                   ▼
                                     ┌────────────────────┐ ┌──────────────┐    ┌─────────┐
                                     │ CREDENTIAL_MISSING │ │ NOT_READABLE │    │  READY  │
                                     └────────────────────┘ └──────────────┘    └─────────┘
```

`DISABLED` is evaluated *after* validity, so a disabled source with a broken configuration still reports
`INVALID` — a user re-enabling it should not be ambushed by faults that were there all along.

Only `READY` participates in ingestion. `NOT_READABLE` is the honest state for the three declared-only
kinds and disappears as `0003`–`0005` land.

---

## SourceRunOutcome

Corresponds to the spec's *Source Run Outcome* entity (FR-043, FR-044).

| Field | Type | Notes |
|-------|------|-------|
| `source_name` | `str` | |
| `result` | `RunResult` | `SUCCEEDED`, `SKIPPED`, or `FAILED`. |
| `failure` | `FailureCategory \| None` | `CONFIGURATION`, `CREDENTIAL`, `UNREACHABLE`, or `SOURCE_ERROR` (the spec's four categories). |
| `detail` | `str \| None` | Redacted at render (D7). |
| `records_ingested` | `int` | |

A run reports one outcome per configured source, including skipped ones — a source that silently
contributes nothing must still be visible in the report.

---

## PermissionStatus

Result of the FR-006 check (D3). Deliberately three-valued.

| Value | Meaning |
|-------|---------|
| `OWNER_ONLY` | Verified: only the owner (and, on Windows, SYSTEM and Administrators) can read. |
| `OTHERS_CAN_READ` | Verified exposed → warning finding. |
| `UNVERIFIED` | The check could not run → warning finding saying so. **Never silently treated as safe.** |

---

## SourceStateStore (port)

Not a data model this feature owns — the boundary onto `0001`'s store. Four operations, defined in
[contracts/source-state.md](./contracts/source-state.md). Listed here because `SourceStatus` and
`SourceRunOutcome` are assembled partly from it: resumption points (FR-010), and the set of source names
holding records but absent from the configuration (FR-012).

---

## Entity coverage against the spec

| Spec entity | Model type |
|-------------|-----------|
| Source Configuration | `SourceConfiguration` |
| Configured Source | `ConfiguredSource` (+ `SourceStatus` for its computed state) |
| Source Kind | `SourceKind`, `SettingSpec` |
| Credential Reference | `CredentialReference`, `CredentialPresence` |
| Validation Finding | `Finding`, `Severity` |
| Source Run Outcome | `SourceRunOutcome`, `RunResult`, `FailureCategory` |
