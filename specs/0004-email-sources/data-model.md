# Data Model: Email Sources and Correspondent Attribution

Phase 1 for [plan.md](./plan.md). Schema **v2 → v3**, migration `m0003_correspondents`.

Regions are `0001`'s: **RAW** is what a source said, **DERIVED** is what we concluded, **USER** is what the
person stated. Only USER data is irreplaceable.

---

## What already exists and does not change

| Table | Region | Why it is untouched |
|---|---|---|
| `raw_record` | RAW | A message is a record like any other. Its provider-specific detail lives in `payload`; its correspondents are lifted out into their own table (below) because they are queried, not just displayed. |
| `raw_source` | RAW | A mail account is a source. Resumption points already exist and carry the delta token. |
| `user_project` | USER | Unchanged from `0003`. A project may now be named by correspondents and subjects as well as repositories. |
| `derived_attribution` | DERIVED | Unchanged in **shape**. Gains three new values in `rule`. |
| `user_correction` | USER | Unchanged. A correction on a mail record works exactly as one on a commit. |

---

## New: `raw_correspondent`

One row per normalised address the user has corresponded with.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Stable identity; attributions and links point here, never at the text |
| `address` | TEXT UNIQUE | Normalised: trimmed, no display name, no angle brackets, lowercased (research R12) |
| `display_name` | TEXT | The most recently seen display name, for showing to a human. **Never** used for matching — a display name is attacker-controlled and changes freely. |
| `domain` | TEXT | The part after `@`, stored separately because domain rules and the ad-hoc fallback both key on it |
| `first_seen_utc` | INTEGER | When this address first appeared in any message |

**Why a table and not a JSON field.** FR-054 asks which correspondents contribute most to a project. That is
a group-by over addresses. Answering it by parsing every record's payload would be slow, untypable, and
would make an index impossible.

**Why the domain is a column.** FR-039's ad-hoc fallback counts recipient domains per message, and domain
rules match by suffix. Both are hot paths; neither should re-split a string per row.

---

## New: `raw_record_correspondent`

Which addresses appeared on which message, and how.

| Column | Type | Notes |
|---|---|---|
| `record_id` | INTEGER | → `raw_record(id)`, cascade on delete |
| `correspondent_id` | INTEGER | → `raw_correspondent(id)` |
| `role` | TEXT | `sender`, `to`, or `cc` |
| PRIMARY KEY | | (`record_id`, `correspondent_id`, `role`) |

A message with twenty recipients produces twenty-one rows. That is the point: FR-034's correspondent rule
matches when an address appears in **any** role, and truncating a recipient list would hide a broadcast.

**`bcc` is deliberately absent.** Graph and Gmail both return it for sent mail, and it is the most sensitive
field in a mail header — it names people the other recipients were not told about. It is not needed for
attribution, so it is never stored. Recorded here so that a future reader knows it was a decision.

---

## The message payload

Inside `raw_record.payload`, for a mail record:

| Key | Meaning |
|---|---|
| `kind` | Always `mail_sent` — the only kind this feature produces (FR-048) |
| `account` | The configured source name, so two accounts are never conflated (FR-030) |
| `provider` | `graph`, `gmail`, `hey` or `mbox` — for diagnostics only; nothing branches on it above `mail/reader.py` |
| `message_id` | The RFC 5322 `Message-ID`, normalised (research R10) |
| `message_id_is_derived` | True where the message had none and the provider's own id was used |
| `sent_by` | Which of the user's declared addresses sent it (FR-021) |
| `subject` | The subject line, verbatim |
| `recipient_count` | How many addresses were on it, so a broadcast is visible without a join |
| `recipients` | `[address, role]` pairs. Also in `raw_correspondent`, and kept here deliberately: `sources/run.py` is source-agnostic and sees only records, so a record must carry what the index is built from. Same argument `_record_repositories` makes for git — driving the index from the record means it cannot disagree with what was stored, and Principle IV's "delete and re-ingest" reproduces both |
| `display_names` | Address → the name seen on the header. Shown to a person, **never** matched on |
| `has_attachments` | Whether it had any. **Never** their names, sizes or content (FR-024). |
| `withdrawable` | `false` for records from an MBOX (research R13); absent otherwise |

**Never present**: any body or body preview, any attachment name or content, any `bcc`, any duration.
SC-004 asserts this by planting sentinel text in fixture bodies and searching the entire store for it.

`source_id` is `mail:<message-id>`, which makes re-reading the same message a no-op at the store level and
is what SC-006 rests on.

---

## Attribution rules

`derived_attribution.rule` gains three values alongside `0003`'s two:

| Rule | Meaning | Precedence |
|---|---|---|
| `mapping:subject` | A subject rule matched | 1 (highest) |
| `mapping:correspondent` | An address rule matched | 2 |
| `mapping:correspondent-domain` | A domain rule matched | 3 |
| `mapping:ad-hoc-domain` | Nothing matched; named for the recipients' domain | 4 (fallback) |
| `mapping:declared`, `mapping:ad-hoc` | `0003`'s repository rules | unchanged |

Within one level, the rule **declared first** in the mapping file wins (FR-036). An address rule always
beats a domain rule, whatever the declaration order, because otherwise a broad domain rule declared early
would make every precise rule below it unreachable.

`derived_attribution.evidence` carries what matched — the address, or the subject text — so FR-035 and
FR-037 are answerable without re-running the rules.

---

## The ad-hoc domain, precisely

FR-039, stated as an algorithm because "named after its recipients' domain" has no single answer when a
message went to two organisations:

1. Take every `to` and `cc` correspondent on the message.
2. Discard any whose domain is one of the account's own declared domains.
3. If any remain: count by domain; take the most frequent; break a tie by taking the alphabetically first.
4. If none remain — a message sent only to colleagues — use the account's own domain.

Steps 3 and 4 are what make SC-010b hold: the result depends only on the message, never on the order mail
was read in.

---

## State: what a mail source remembers between runs

Stored against the source in `raw_source`, as `0002` established:

| Provider | Resumption point | On loss |
|---|---|---|
| Microsoft 365 | The Graph `deltaLink` | Fall back to a date-bounded full read from the account's `since` |
| Gmail | The last `historyId` | Gmail expires old history; on `404` fall back to a full list of `SENT`, which the store deduplicates |
| Hey | The instant last searched through | No token to lose; a lost point costs one wider search, which the store deduplicates |
| Exported archive | Nothing | Every run re-reads the file; the store deduplicates by `source_id` |

**Losing a resumption point must never lose data.** Each fallback re-reads more than necessary and relies on
`source_id` deduplication, which `0001` already guarantees — the cost is time, never correctness.

---

## Migration `m0003_correspondents`

| Step | Reason |
|---|---|
| Create `raw_correspondent` and `raw_record_correspondent` | The two new entities |
| Backfill nothing | No mail exists before this feature; there is nothing to migrate |
| Leave `derived_attribution` untouched | New rule values are data, not schema |

Per-statement `execute()` inside the runner's single transaction — **never** `executescript()`, which issues
an implicit COMMIT and would defeat the rollback `0001`'s FR-021 rests on. This is written down because it
is the mistake `m0002` had to be corrected for.

Tested against an empty store and a populated one, as the constitution requires, plus a deliberately failing
migration that must leave the store at v2 with counts unchanged.
