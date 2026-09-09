# Phase 0 Research: Local Store Foundation

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-09-09

Findings marked **verified** were checked by running code on the target machine (Windows 11, CPython
3.11.5 ambient / 3.12.11 via `uv`, SQLite 3.42.0) rather than recalled.

---

## R1. Storage engine — SQLite

**Decision**: SQLite, via the standard library's `sqlite3`. One file, in the tool's own data directory.

**This is the project-wide decision** the constitution requires to be made once, here, and never varied
per connector.

**Rationale**:

1. **Zero dependency.** `sqlite3` is in the standard library; DuckDB is a third-party package the
   constitution would require justifying. For the store that every other feature depends on, a dependency
   is one that can never later be removed.
2. **Format stability measured in decades.** SQLite commits to backward compatibility of its file format
   through at least 2050. This store is meant to accumulate years of records and be migrated in place; an
   engine whose on-disk format may change under a version bump is the wrong shape of risk for the one
   artifact the user cannot re-download.
3. **Every durability requirement maps onto a verified primitive**, rather than onto code we would write:

   | Requirement | Primitive | Verified |
   |---|---|---|
   | FR-013 batch is all-or-nothing | `BEGIN IMMEDIATE` … `COMMIT` | yes |
   | FR-020 structure version | `PRAGMA user_version` | yes — returns 3 after set |
   | FR-021 failed migration leaves the store at its previous version | transactional DDL **and** `user_version` participating in rollback | yes — a rolled-back `CREATE TABLE` leaves no table, and `user_version` reverted 99 → 1 |
   | FR-025 concurrent use waits or fails clearly | `busy_timeout` then `OperationalError: database is locked` | yes — second writer blocked 0.59s then raised |
   | FR-026 a store that cannot be read is reported | `PRAGMA integrity_check` / `quick_check` | yes — returns `ok` |
   | FR-011 re-ingesting does not duplicate | `INSERT … ON CONFLICT DO UPDATE` | yes |
   | FR-006 unmodified source payload | JSON1 + generated columns over a `TEXT` payload | yes |
   | FR-021 pre-migration snapshot | online backup API (`Connection.backup`) | yes — present |

   The `user_version` rollback behaviour is the load-bearing one: it means "migrate atomically or leave
   the store exactly as it was" needs no bespoke journal of our own.
4. **`STRICT` tables** (SQLite 3.37+) give real type enforcement, which matters in a schema that must
   stay coherent across migrations and years. Verified working alongside generated columns and JSON1.
5. **Scale is not close to the crossover.** A year across mail, calendar, git, browser and SharePoint is
   estimated at 10⁵–10⁶ rows. Columnar storage starts to pay at two to three orders of magnitude beyond
   that. SC-008's five-second budget for store info is an index question, not an engine question.

**Alternatives considered**:

- **DuckDB** — genuinely better for the analytical queries the future dashboard will run: columnar scans,
  fast group-by over date ranges. Rejected for now on three grounds: it is a third-party dependency where
  the constitution defaults to the standard library; its write model is built around bulk analytical
  loads rather than the small, frequent, interruptible transactions FR-013 describes; and its storage
  format history is shorter and less conservative than SQLite's, which is the wrong trade for the
  irreplaceable artifact. **Crucially, this choice does not foreclose DuckDB** — it can attach and query
  SQLite files directly, so a later dashboard feature can use DuckDB as a read engine over this store
  without migrating anything. That asymmetry (SQLite now keeps DuckDB available; DuckDB now would not
  keep SQLite available) is what makes SQLite the low-regret option.
- **Plain files — JSON Lines or Parquet per source per day** — no engine, trivially inspectable.
  Rejected: FR-011 (no duplicates on re-ingest), FR-013 (atomic batches), and FR-025 (concurrency) all
  become code we write and get wrong, and the constitution asks for a database.
- **An embedded key-value store (`dbm`, LMDB)** — rejected: FR-003 and FR-038 need aggregate queries over
  time ranges and per-source groupings, which is a query engine's job.

**Consequences**: minimum SQLite 3.37 for `STRICT`; the tool checks `sqlite3.sqlite_version` at startup
and refuses clearly below that rather than failing obscurely on the first DDL.

---

## R2. Three separately discardable regions (FR-010)

**Decision**: One database file, three table-name regions — `raw_*`, `derived_*`, `user_*` — with a
documented discard operation per region. No foreign keys from `raw_` into `derived_` or `user_`; the
dependent direction only.

**Rationale**: FR-010 requires that any one region be discardable without altering the others, and
Principle IV requires re-derivation to cost nothing but compute. Discarding `derived_*` is then a
`DELETE FROM` over three tables inside one transaction, and discarding it cannot cascade into raw records
or corrections because nothing points that way. Corrections reference records by `(source, source_id)` —
the source's own identity — rather than by internal row id, which is what lets FR-017 hold across a full
delete-and-rebuild where every internal id is different.

**Alternatives considered**:

- **Three separate database files** — cleanest possible separation, and discarding a region becomes
  deleting a file. Rejected: the constitution says "a single embedded, file-based database … The database
  file MUST live in the tool's own data directory", singular; and three files means three-file atomicity
  for operations that touch more than one, which SQLite gives us for free inside one file.
- **Schemas via `ATTACH`** — closer to the constitution's letter than three independent stores, and still
  one logical store. Rejected as complexity without benefit: attached databases do not share a
  transaction journal in the way a single file does, which weakens FR-013.

---

## R3. Migration mechanism (FR-020 to FR-022)

**Decision**: `PRAGMA user_version` as the structure version. Ordered migration modules
(`m0001_initial.py`, …), each exposing a target version and an `upgrade(conn)`. The runner takes a file
snapshot, then applies each pending migration inside a single `BEGIN IMMEDIATE` that also sets
`user_version`. A store whose `user_version` exceeds the highest known migration is refused (FR-022).

**Rationale**: verified above — because DDL is transactional and `user_version` rolls back with it, a
failed migration leaves the store byte-equivalent to its previous state with no cleanup code. The file
snapshot is therefore **not** the rollback mechanism; it is a recovery path for the case transactions
cannot cover, such as the process being killed mid-`COMMIT` or the disk filling. Keeping that distinction
explicit stops the snapshot from being treated as the safety net when it is the second one.

Migrations are forward-only. Downgrade migrations are not written, because FR-022 already requires
refusing a newer store, which is the situation a downgrade would otherwise serve.

**Alternatives considered**:

- **A `schema_version` table instead of `user_version`** — more conventional, and allows a migration
  history with timestamps. Rejected as redundant: `user_version` is a single atomic integer in the file
  header that participates in transactions, and the history it lacks is better served by the log (R11).
- **Alembic or another migration framework** — rejected: a dependency, oriented around ORMs this project
  does not use, for a handful of hand-written migrations.

---

## R4. Stable identity for sources that supply none (FR-009)

**Decision**: When a source provides no identifier of its own, derive one as a BLAKE2b-160 digest over a
canonical serialisation of `(source_name, occurred_utc, title, payload)`, prefixed `derived:` so it is
never mistaken for a source-issued id. Canonical means JSON with sorted keys, no insignificant
whitespace, UTF-8.

**Rationale**: FR-009 exists so that FR-011 (re-ingesting does not duplicate) still holds for such
sources, which requires the identifier to be a deterministic function of content and nothing else — not
of insertion order, wall-clock time, or dictionary iteration order. `hashlib.blake2b` is stdlib, fast,
and lets the digest size be set explicitly. The `derived:` prefix matters because FR-014 treats a
changed-content record as the *same* record: for source-issued ids that is right, but for content-derived
ids a content change necessarily produces a different id, so the two cases must be distinguishable rather
than silently conflated.

**Alternatives considered**:

- **SHA-256** — equally correct; BLAKE2b chosen for configurable digest length and speed. Either is fine
  and the choice is not load-bearing.
- **A random UUID assigned on first sight** — rejected outright: it would make re-ingestion produce
  duplicates, breaking FR-011 for exactly the sources FR-009 exists to serve.

**Consequence**: recorded in [contracts/record-shape.md](./contracts/record-shape.md) — a source that
supplies no id and whose content changes will present as a new record. That is unavoidable and must be
stated, not discovered.

---

## R5. Storing time so instant and zone are both recoverable (FR-007)

**Decision**: Three columns — `occurred_utc` (INTEGER, microseconds since the Unix epoch),
`occurred_offset_minutes` (INTEGER, the UTC offset as the source expressed it), and `occurred_zone` (TEXT
or NULL, the IANA zone name when the source gives one).

**Rationale**: FR-007 requires both the original instant and the zone it was expressed in to be
recoverable. An integer instant sorts and ranges correctly with no string comparison pitfalls, which is
what SC-008's query budget rests on. The offset preserves what the source actually said — needed to
answer "was this 9am for them?" — and the zone name, where available, is what survives a daylight-saving
transition correctly, since an offset alone cannot distinguish two moments in a repeated hour.

Storing all three costs 16 bytes per record and removes a whole class of ambiguity permanently. The spec's
edge-case list names daylight-saving transitions explicitly; the zone name is the only thing that answers
it.

**Alternatives considered**:

- **ISO-8601 text with offset** — human-readable in a database browser. Rejected: lexical ordering is
  wrong across differing offsets unless normalised, and range queries then need conversion per row.
- **UTC instant only** — smallest. Rejected: discards the zone, failing FR-007 outright.

---

## R6. Withdrawal detection needs a run mode (FR-027 to FR-029)

**Decision**: Every ingestion run declares a `RunMode` — `INCREMENTAL` or `SWEEP` — and the time range it
covered. **Only a `SWEEP` may mark records withdrawn**, and only within the range it covered and the
source it read. A sweep supplies the set of source-side identifiers it saw; stored records in that
window not in that set are marked withdrawn with the sweep's date. A record reappearing in a later run
has its withdrawal cleared rather than being inserted again (FR-029).

**Rationale**: this is the finding that most changed the design. FR-027 says a record no longer present
at the source must be marked withdrawn — but an incremental run, by definition, asks the source only for
what is new. It sees nothing of the old records and so cannot distinguish "deleted" from "not asked
about". Implementing FR-027 without this distinction would mark **every** record outside the incremental
window as withdrawn on every run, turning a safety requirement into a data-destruction bug.

Making the mode part of the record contract rather than an internal detail also puts the obligation where
it belongs: a connector author must state whether their read was exhaustive, and cannot accidentally
trigger withdrawal by writing an ordinary incremental fetch.

**Alternatives considered**:

- **Withdraw on any run** — rejected on the bug above.
- **Infer exhaustiveness from the range covered** — rejected: a run covering a wide range incrementally
  looks identical to a sweep from the store's side. The connector knows; the store cannot.
- **Never withdraw automatically; require an explicit user command** — safe, and considered seriously.
  Rejected because FR-027 describes withdrawal as something ingestion does, and a user who must remember
  to run a reconciliation command will not.

---

## R7. "Future-dated" is two questions, not one (FR-035 to FR-038)

**Decision**: Store no flag. Derive two distinct properties:

- **`was_future_at_ingestion`** — `occurred_utc > ingestion_run.started_at`. A permanent, immutable
  data-quality signal about a possibly-wrong source clock. This is what FR-038's per-source count reports.
- **`not_yet_elapsed`** — `occurred_utc > now()`. Evaluated at query time; this is what excludes a record
  from elapsed-time summaries (FR-036) and what stops excluding it once the moment passes (FR-037).

**Rationale**: FR-036 defines future-dated by comparison with the ingestion run, while FR-037 requires a
record to become ordinary once its time has passed *without re-ingestion*. Those two cannot both hold if a
single stored flag is used — the flag would be computed at ingestion and go stale. Separating the
data-quality question from the arithmetic question satisfies FR-036, FR-037, and FR-038 simultaneously,
and stores nothing that can drift out of date.

A calendar entry for next week is legitimately future-dated at ingestion and is correctly excluded from
elapsed time until next week arrives; an email dated 2027 by a broken clock is also correctly excluded,
and additionally shows up in FR-038's per-source count where a wrong clock becomes visible.

**Alternatives considered**:

- **A stored boolean flag** — rejected on the staleness argument above; FR-037 would require a periodic
  sweep to clear flags, which is machinery in place of a comparison.
- **Clamping future timestamps to ingestion time** — rejected by FR-035, which requires storing the time
  unmodified, and rightly: rewriting what the source said destroys the evidence that the clock is wrong.

---

## R8. Concurrency and corruption (FR-025, FR-026)

**Decision**: WAL journal mode. Writers take `BEGIN IMMEDIATE` with a `busy_timeout` (default 5s,
configurable), so a second command waits and then fails with a message naming the store and saying
another command is using it. On open, run `PRAGMA quick_check`; the full `integrity_check` is available
behind an explicit `store check` command. A store that fails either is reported with its path and a
stated recovery step, and is never deleted or overwritten by the tool.

**Rationale**: **verified** — a second writer blocked for the timeout and then raised
`OperationalError: database is locked`, which is precisely FR-025's "wait for the holder or fail with a
clear message". `BEGIN IMMEDIATE` rather than the default deferred transaction is what makes the wait
happen at the start of the write rather than at commit, when partial work has already been done.

`quick_check` on open rather than `integrity_check` is a deliberate trade: the full check is O(database)
and would blow SC-008's five-second budget on a year of records, while `quick_check` catches the common
corruption without reading every index.

**Alternatives considered**:

- **A separate lock file** — rejected: SQLite already provides the lock, and a second mechanism can
  disagree with the first.
- **`integrity_check` on every open** — rejected on the performance budget.

---

## R9. Portable correction export (FR-018, FR-032 to FR-034)

**Decision**: JSON Lines — one correction per line, UTF-8, stdlib `json`. Each line carries a format
version, the record's identity as `(source, source_id)` rather than any internal id, the correction's
content, and `made_at` as an ISO-8601 UTC instant. Import resolves conflicts newest-wins by `made_at`,
ties keeping the local correction, and reports every replacement and every declined replacement.

**Rationale**: FR-018 calls for a *portable* file, which means it must survive the target store having
entirely different internal identifiers — hence identity by source-side keys, which is also what lets
FR-018's "no matching record → retained as pending" case work at all. JSON Lines is append-friendly,
diff-friendly, streamable without loading the whole file, and needs no dependency. A per-line format
version is what makes the file readable by a future version that has changed the correction model.

`made_at` is stored and exported as UTC rather than local time because it is used for cross-machine
comparison (FR-033), and two machines in different zones must order corrections consistently.

**Alternatives considered**:

- **CSV** — rejected: correction content is structured and would need escaping conventions that JSON
  already defines.
- **A SQLite file as the exchange format** — rejected: not inspectable in a text editor, and version
  coupling between the two stores is exactly what a portable format should avoid.

**Known limitation, recorded**: newest-wins by `made_at` (the user's clarification answer) is only as good
as the clocks involved. A machine with a wrong clock can produce a correction that wins when it should
not. FR-034's mandatory reporting of every replacement is the mitigation — nothing is replaced silently —
and the spec's edge-case list now names this case.

---

## R10. At-rest protection reporting (FR-031)

**Decision**: Three-valued reporting for both halves, never collapsing "unknown" into "safe".

- **File permissions** — POSIX: `stat.S_IMODE`, warn if group or other can read. Windows: read the DACL
  as SDDL through `ctypes` into `advapi32.GetNamedSecurityInfoW` and
  `ConvertSecurityDescriptorToStringSecurityDescriptorW`, accepting only the owner, `SY`, and `BA`.
- **Disk encryption** — best-effort probe per platform, defaulting to `UNVERIFIED`.

**Rationale**: **verified — on Windows, disk-encryption status cannot be read without administrator
rights.** All three available probes failed on this machine as a normal user:

| Probe | Result |
|---|---|
| `manage-bde -status C:` | `FEHLER: Der Zugriff auf eine erforderliche Ressource wurde verweigert` |
| `Get-BitLockerVolume -MountPoint C:` | `Zugriff verweigert` |
| `Get-CimInstance … Win32_EncryptableVolume` | `Zugriff verweigert` |

So on Windows the honest answer for an unelevated run is `UNVERIFIED`, and FR-031's "report it as
unverified rather than implying protection it has not confirmed" is not an edge case but the normal path.
The report therefore includes the elevated command the user can run themselves, which turns a dead end
into an action.

**Verified separately**: Windows file permissions *are* readable unelevated, and the SDDL form is
locale-independent — `O:S-1-5-21-…D:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;S-1-5-21-…)` — whereas
`icacls` returns localised principal names (German on this machine), which no parser should depend on.
So the permissions half of FR-031 is answerable and the encryption half usually is not.

macOS uses `fdesetup status`, readable without elevation. Linux checks whether the backing device is a
dm-crypt mapping via `/sys/block`. Both degrade to `UNVERIFIED` rather than guessing.

**Alternatives considered**:

- **`pywin32`** — rejected: a large dependency on one platform; `ctypes` reaches the same two Win32 calls
  with none.
- **Parsing `icacls`** — rejected on the verified localisation problem.
- **Requiring elevation to run the tool** — rejected: a daily-use tool that demands administrator rights
  to report a status line is a worse trade than an honest "unverified".
- **Assuming encryption is on** (BitLocker and FileVault are default-on for modern installs) — rejected
  outright; it is precisely the "implying protection it has not confirmed" the spec forbids.

---

## R11. Logging (FR-039 to FR-043)

**Decision**: stdlib `logging` with `RotatingFileHandler` (bounded size and backup count, satisfying
FR-042), writing to a file in the tool's data directory created with owner-only permissions. Crucially,
`obs/logging.py` exposes **only** functions whose parameters are identifiers, counts, and durations —
there is no code path through which a record object or a payload reaches the logger.

**Rationale**: FR-041 forbids record content in the log. A redaction filter inspecting formatted strings
would be guesswork, and a convention that authors must remember decays. Restricting the logging API's
*parameters* makes the requirement structural: to log a record's title, a future author would have to add
a new function that takes one, which is a visible change a reviewer can catch.

FR-043 (a log that cannot be written must not fail the operation) is handled by installing the file
handler defensively and falling back to stderr-only with a single reported warning.

**Alternatives considered**:

- **A regex filter over formatted log lines** — rejected: it cannot distinguish a subject line from an
  identifier, so it either leaks or mangles.
- **`TimedRotatingFileHandler`** — rejected: FR-042 bounds *size*, and a time-based rotation on a machine
  ingesting a heavy backlog can still produce an unbounded file.
- **No log at all** — rejected by the user's clarification, and it would leave a failed overnight
  ingestion undiagnosable.

---

## R12. Development dependencies

**Decision**: `pytest` and `mypy`, dev-only. Runtime dependencies remain empty.

**Rationale**: `mypy` is mandated by the constitution. `pytest` is justified by the shape of this test
suite specifically: migrations must be tested against both an empty and a populated store, and the
durability suite runs the same assertions across three different paths (re-derivation, migration, full
rebuild). Parameterised fixtures express that directly; `unittest` expresses it as inheritance. Neither
package ships to the user.

---

## R13. `tzdata` on Windows — a runtime dependency

**Decision**: `dependencies = ["tzdata; sys_platform == 'win32'"]`.

**Rationale**: **verified during implementation** — Windows ships no system IANA time zone database, so
`zoneinfo.ZoneInfo("Europe/Zurich")` raises `ZoneInfoNotFoundError`. FR-007 requires the zone name to be
recoverable, and the zone name is the *only* thing that resolves a moment inside a daylight-saving
repeated hour — an offset cannot. On the project's primary platform this is a correctness requirement,
not a convenience. The package contains data, no code, and is not installed on Linux or macOS.

**Alternatives considered**:

- **Degrade silently to the stored UTC offset.** The code already falls back this way, so the store keeps
  working — but the DST case FR-007 exists for would fail on Windows and nowhere else, which is the worst
  shape of bug: platform-specific, silent, and in the timestamps a timesheet is computed from.
- **Store the offset only and drop zone names.** Rejected: it fails FR-007 outright.
- **Vendor a minimal tz database.** Rejected: maintaining a copy of data that changes several times a
  year, to avoid a dependency that exists precisely to distribute it.

**Consequence**: the "zero runtime dependencies" claim is retired. Per the constitution, a pull request
introducing this must call out the new runtime dependency explicitly.

---

## Open items carried into implementation

None blocking. Two consequences recorded so they are not rediscovered:

1. **`0002`'s plan and tasks need adjusting** — it assumed it would create `errors.py`, `cli/main.py`,
   `cli/render.py`, and its own permission check, all of which this feature owns. The specifics are listed
   in [plan.md](./plan.md) under "Correction to feature 0002's plan".
2. **`RunMode` (R6) is an addition to the record contract** that `0002`'s `SourceReader` protocol does not
   yet carry. Whichever feature builds a real connector must supply it, and
   [contracts/record-shape.md](./contracts/record-shape.md) states the obligation.
