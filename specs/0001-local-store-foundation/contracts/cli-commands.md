# Contract: CLI commands

Console script `ikwyd`, also `python -m iknowwhatyoudid`. Every command writes results to **stdout**,
diagnostics to **stderr**, offers `--json`, and exits non-zero on failure (Principle VI).

## Global options

| Option | Effect |
|--------|--------|
| `--store PATH` | Use this store instead of the default (FR-004) |
| `--json` | Machine-readable form on stdout |
| `-v`, `--verbose` | More diagnostics on stderr; never changes stdout |

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | The operation failed — corrupt store, failed migration, import conflicts left unresolved |
| `2` | Usage error, or the store was written by a newer version and every command must refuse (FR-022) |

## Store location (FR-001, FR-004)

| Platform | Default |
|----------|---------|
| Windows | `%LOCALAPPDATA%\iknowwhatyoudid\store.db` |
| macOS | `~/Library/Application Support/iknowwhatyoudid/store.db` |
| Linux | `$XDG_DATA_HOME/iknowwhatyoudid/store.db`, else `~/.local/share/…` |

`LOCALAPPDATA` rather than `APPDATA` on Windows: the store is a large, rebuildable, machine-local cache
and has no business roaming. Note this differs from `0002`'s **configuration** file, which is
hand-authored and does belong in roaming `APPDATA`.

---

## `ikwyd store info`

Location, structure version, and per-source counts, time span, and last ingestion (FR-003).

```console
$ ikwyd store info
Store: C:\Users\ods\AppData\Local\iknowwhatyoudid\store.db  (schema v1, 84.2 MB)

SOURCE          RECORDS  WITHDRAWN  FUTURE-DATED  EARLIEST     LATEST       LAST INGESTED
work-mail        41,203        118             0  2026-01-02   2026-09-08   2026-09-09 08:14
work-calendar     2,940          6            37  2026-01-02   2026-11-14   2026-09-09 08:14
work-repos       11,882          0             0  2026-01-02   2026-09-09   2026-09-09 08:15

56,025 records · 124 withdrawn · 37 future-dated · 1,204 corrections
```

`FUTURE-DATED` is FR-038: 37 for a calendar is ordinary (next term's meetings); 37 for mail means a clock
is wrong somewhere, and this column is where that becomes visible instead of merely absent from the
numbers.

Must complete in under 5 seconds on a year of records (SC-008). Opens no socket (FR-023).

---

## `ikwyd store check`

Full `PRAGMA integrity_check` (FR-026). Separate from `info` because it is O(database) and would blow
`info`'s budget; `info` runs the cheap `quick_check` on open.

A store that fails is reported **with its path and a stated recovery step**, and is never deleted or
overwritten by the tool on its own initiative — a corrupt store may still be the only copy of a year's
withdrawn records and corrections.

---

## `ikwyd store migrate [--dry-run]`

Applies pending migrations (FR-020). Runs automatically when any command opens an older store; this
command exists to do it deliberately and to preview.

```console
$ ikwyd store migrate
Store at schema v1; migrations available to v3.
  v2  add participant index ......... ok
  v3  split payload envelope ........ FAILED: disk full

Migration failed. Store left at schema v1, fully usable. 56,025 records, 1,204 corrections — unchanged.
Snapshot retained: store.db.pre-v1  (delete once you are satisfied)
$ echo $?
1
```

FR-021 in one transaction: DDL is transactional and `user_version` rolls back with it (verified), so the
store is byte-equivalent to its previous state. The snapshot is the second safety net, not the first.

A store written by a newer version refuses every command with exit `2` and changes nothing (FR-022).

---

## `ikwyd store protection`

At-rest protection state (FR-031). Three-valued; never collapses unknown into safe.

```console
$ ikwyd store protection
Store: C:\Users\ods\AppData\Local\iknowwhatyoudid\store.db

  file permissions   OWNER_ONLY    only ch\ODS, SYSTEM and Administrators can read
  disk encryption    UNVERIFIED    reading BitLocker status requires administrator rights

  To check disk encryption yourself, in an elevated PowerShell:
      Get-BitLockerVolume -MountPoint C:
```

**`UNVERIFIED` is the normal answer on Windows for an unelevated run** — verified, all three available
probes return access-denied (research [R10](../research.md)). The elevated command is printed so the
report is actionable rather than a dead end. macOS uses `fdesetup status` and Linux inspects the backing
device, both readable without elevation.

---

## `ikwyd corrections export [--out FILE]`

Writes JSON Lines to stdout or a file — see [corrections-file.md](./corrections-file.md) (FR-018).

## `ikwyd corrections import FILE [--dry-run]`

Merges corrections, newest-wins by `made_at` (FR-033).

```console
$ ikwyd corrections import laptop-corrections.jsonl
1,180 corrections read.
  1,102 new
     61 replaced an older local correction
     14 declined — the local correction is newer
      3 kept as pending — no matching record in this store

Replaced (local → imported):
  work-mail / AAMkAGI2… "Acme rollout" → "Acme migration"   2026-08-14 → 2026-09-02
  … 60 more, see --json
$ echo $?
0
```

Every replacement and every declined replacement is named (FR-034) — the mitigation for newest-wins being
only as trustworthy as the clocks involved. `--dry-run` reports the same without writing.

## `ikwyd corrections list [--pending]`

Pending corrections are those imported for a record this store does not hold (FR-018). They are retained
indefinitely and stop being pending when the record arrives.

---

## `ikwyd records query --from DATE --to DATE [--source NAME] [--include-withdrawn]`

Reads records back by time range and source (FR-003, User Story 1).

Withdrawn records are excluded by default and included with the flag (FR-028). Records whose time has not
yet passed are excluded from elapsed-time totals but still listed, flagged (FR-036).

Columns: `WHEN`, `SOURCE`, `PROJECT`, `TITLE`, and a flag column. **`PROJECT` was added by `0003`** — every
record lands on a project, and an ad-hoc one is marked `(ad hoc)` here as in every other listing, so the
tool's guess never reads as the user's decision. The machine form carries `project` and `project_rule`.
A record with no attribution shows `—` and is counted in the summary line: it is a fault to be seen, not a
blank cell.

---

## `ikwyd derived discard`

Discards the derived region, leaving raw records and corrections untouched (FR-010). Re-derivation then
reads nothing from any source (FR-015).

There is deliberately **no** command that discards corrections alongside another region. The only
irreplaceable data does not share a code path with the two regenerable ones.

## Invariants every command upholds

| Invariant | Requirement |
|-----------|-------------|
| No socket is opened by any command | FR-023, SC-001 |
| Nothing is written outside the tool's own data directory | FR-001 |
| The store is never deleted or overwritten on the tool's initiative | FR-026 |
| No credential reaches the store or the log | FR-024, FR-041 |
| No record content reaches the log — only identifiers and counts | FR-041 |
| A second concurrent command waits, then fails clearly; it never corrupts or returns partial results | FR-025 |
