# Contract: The portable correction file

**Format**: JSON Lines, UTF-8, one correction per line (FR-018, research [R9](../research.md)).

This is the only path between machines, carrying the only data in the store that no source can supply
again. It is also the only file this feature produces that another program is expected to read.

## A line

```json
{"v":1,"source":"work-mail","source_id":"AAMkAGI2…","project":"acme-migration","note":"kickoff, not billable","made_at":"2026-09-02T14:31:07Z"}
```

| Field | Type | Notes |
|-------|------|-------|
| `v` | integer | Per-line format version, so a future reader can handle old exports |
| `source` | string | The source name |
| `source_id` | string | The source's own id for the record |
| `project` | string or null | `null` means "explicitly not attributable" — a real correction, not a gap |
| `note` | string or null | |
| `made_at` | string | ISO-8601, **always UTC with a `Z`** |

## Two deliberate choices

**Identity is `(source, source_id)`, never an internal row id.** The target store's internal ids are
different — after a delete-and-rebuild even the *source* store's ids are different. Keying by what the
source calls the record is what makes FR-017 (corrections survive a full rebuild) and FR-018's pending
case work at all.

**`made_at` is always UTC.** It is used to compare corrections made on different machines (FR-033), and
two machines in different zones must order them consistently. Local time here would produce a merge that
depends on where you were sitting.

## Import algorithm (FR-033, FR-034)

For each line, matched against the local store by `(source, source_id)`:

| Local state | Action | Reported as |
|-------------|--------|-------------|
| No local correction, record present | Insert | `new` |
| No local correction, record absent | Insert with `pending = 1` (FR-018) | `pending` |
| Local correction, imported `made_at` is later | Replace | `replaced` — both versions named |
| Local correction, imported `made_at` is earlier | Keep local | `declined` — both versions named |
| Local correction, `made_at` equal | Keep local (FR-033 tie-break) | `declined` |

The whole import is one transaction: it applies fully or not at all.

## Every change is named

FR-034 requires each replacement **and** each declined replacement to be reported with the record and
both versions. This is not a convenience — it is the mitigation for the conflict rule itself.

Newest-wins is only as trustworthy as the clocks involved. A machine with a wrong clock produces
corrections that look newer than they are and win when they should not. Nothing detects that
automatically, so the guarantee this contract can actually make is the weaker but honest one: **no
correction is ever replaced silently.** The spec's edge-case list names the wrong-clock case, and
`--dry-run` exists so a user can see the merge before it happens.

## Round-trip guarantee

Exporting a store's corrections and importing them into an empty store must produce an identical
correction set, including `pending` ones and their `made_at` values. This is the test that keeps the
format honest, and it is the one in [quickstart.md](../quickstart.md) Scenario 6.
