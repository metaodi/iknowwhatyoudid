# Quickstart: validating Configurable Sources

How to prove this feature works end to end once it is implemented. Every scenario runs against fixtures —
no git repository, no mail account, no calendar is involved (SC-012).

## Prerequisites

```bash
uv sync                                  # provisions CPython 3.12, installs dev deps
uv run mypy src tests                    # must be clean (constitution)
uv run pytest                            # must be green
```

`uv` 0.7.15 and CPython 3.12.11 are confirmed available on the development machine. The ambient
interpreter is 3.11.5, so **run everything through `uv run`** — a bare `python` gets the wrong version.

## Scenario 1 — nothing configured (User Story 1)

```bash
uv run ikwyd sources list --config /nonexistent/config.toml
```

Expected: reports that no configuration exists, prints the exact path it looked at, exits `0`, creates
nothing (FR-002). Verify afterwards that the path still does not exist.

## Scenario 2 — a valid configuration validates offline (US1)

```bash
uv run ikwyd sources validate --config tests/fixtures/configs/valid.toml
uv run ikwyd sources list     --config tests/fixtures/configs/valid.toml --json | jq .
```

Expected: every source listed with name, kind, enabled, readiness (FR-015); exit `0`. The three
declared-only kinds report `not_readable`, the fixture kind reports `ready`.

**The load-bearing assertion is negative**: no network connection is opened. Assert it by running with
outbound traffic blocked, or by asserting no socket is created — a test that only checks the output would
pass even if the tool phoned home.

## Scenario 3 — every fault reported at once (US1, SC-003, SC-004)

```bash
uv run ikwyd sources validate --config tests/fixtures/configs/many-faults.toml
```

The fixture contains a duplicate name, an unknown kind, a missing required setting, an undeclared setting,
and an inline secret. Expected: **all five** reported in one run, each naming the source and the setting,
blocking separated from warning, exit `1`.

Assert on finding `code`s, never on message text ([json-output.md](./contracts/json-output.md)).

## Scenario 4 — a broken file is fatal and distinguishable (US1)

```bash
uv run ikwyd sources validate --config tests/fixtures/configs/broken.toml; echo "exit=$?"
```

Expected: `parse-error` with a line and column from `tomllib`, exit **`2`** — not `1`. A broken file and a
valid file describing a broken source are different problems.

## Scenario 5 — per-source lifecycle in isolation (US2, SC-005, SC-006)

The most valuable test in the feature, because it protects the property that makes the file safe to edit.

1. Populate an `InMemorySourceStateStore` with resumption points and record counts for four sources.
2. Snapshot every source's state.
3. Add a fifth source, disable the second, remove the third, rename the fourth.
4. Re-run validation and ingestion.

Expected:

| Assertion | Requirement |
|-----------|-------------|
| Untouched sources' resumption points and record counts are identical to the snapshot | FR-011, SC-005 |
| The disabled source is skipped but its records remain queryable | FR-009 |
| Re-enabling it resumes from its stored point — zero records re-read | FR-010, SC-006 |
| The removed source appears in `unconfigured_with_records`, records not deleted | FR-012 |
| The renamed source produces a `source-renamed` warning | FR-013 |

## Scenario 6 — secrets never surface (US3, SC-007)

```bash
uv run pytest tests/integration/test_secrets.py -v
```

The test plants known sentinel values in the credentials file, runs **every** command in both human and
`--json` form, then searches stdout, stderr, the log file, and the in-memory store for each sentinel.

Expected: zero occurrences. This is a whole-surface assertion, not a per-command one — that is what makes
the single render chokepoint (research D7) worth having.

Also assert: a source with a missing credential reports `credential-missing` naming the credential and how
to supply it (FR-021), and a configuration with `password = "…"` produces an `inline-secret` **warning**
that does not block (FR-023, FR-017).

## Scenario 7 — file permissions (US3, FR-006)

```bash
uv run pytest tests/unit/test_permissions.py -v
```

Platform-split by necessity (research D3):

- **POSIX**: `chmod 0644` a temp file → `OTHERS_CAN_READ`; `chmod 0600` → `OWNER_ONLY`.
- **Windows**: parse captured SDDL strings. `O:<owner>D:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;<owner>)`
  → `OWNER_ONLY`; the same with an added `(A;;FR;;;WD)` (Everyone) → `OTHERS_CAN_READ`. A separate smoke
  test exercises the real `ctypes` call against a temp file.
- **Both**: when the check raises, the result is `UNVERIFIED` and a warning is emitted — assert it is
  **never** silently `OWNER_ONLY`.

## Scenario 8 — a new kind changes nothing else (US4, SC-008)

```bash
uv run pytest tests/integration/test_new_kind.py -v
```

Register a second fixture kind that no other module knows about, configure an instance, and drive it
through `validate`, `list`, `kinds`, enable/disable, and `ingest`.

Expected: it behaves exactly like a shipped kind, and — the actual assertion — **no existing kind module
and no existing configuration fixture was modified** to make that true (FR-030).

Also assert FR-031: a `SourceKind` offered from outside `iknowwhatyoudid.kinds` is not loaded and not
listed.

## Scenario 9 — one source failing does not stop the rest (SC-009)

```bash
uv run ikwyd ingest --config tests/fixtures/configs/one-failing.toml; echo "exit=$?"
```

Expected: healthy sources complete, the failing one is named with a `failure` category, every configured
source appears in the report including skipped ones, exit `1` (FR-043, FR-044).

## Scenario 10 — the egress surface is inspectable (SC-010)

```bash
uv run ikwyd sources destinations --config tests/fixtures/configs/valid.toml
```

Expected: every destination the configuration could reach, listed **before** anything is contacted. Assert
this list is exactly the set of destinations a subsequent `ingest` attempts — the strongest available test
of Principle I.

## Scenario 11 — attribution is refused (FR-041)

```bash
uv run ikwyd sources validate --config tests/fixtures/configs/with-attribution.toml
```

Expected: `attribution-not-allowed`, **blocking** — rejected rather than ignored, so a user who writes a
project mapping here is told, not silently disappointed.

## Known gaps at the end of this feature

One gap, intended and stated by the tool rather than left to be discovered:

- **Nothing real is read.** `git.local`, `mail.*` and `calendar.*` are declarations; only `fixture` has a
  reader. This is FR-033 — the connectors are `0003`, `0004`, `0005`.

Source state *is* durable: `0001` ships the SQLite-backed `SourceStateStore`.
