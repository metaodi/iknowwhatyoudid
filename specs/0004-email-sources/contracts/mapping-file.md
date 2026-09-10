# Contract: correspondents and subjects in `projects.toml`

Extends [`0003`'s mapping contract](../../0003-git-source-projects/contracts/mapping-file.md). Location,
the rule that **the tool never writes this file**, and "an absent file is valid" are all unchanged.

## Grammar, extended

```text
projects     := version? project*
project      := "[[project]]" name repositories? correspondents? subjects? note?
name         := "name" "=" string                 # unique, case-insensitively
repositories := "repositories" "=" [string...]    # 0003, unchanged
correspondents := "correspondents" "=" [string...]  # NEW: addresses or domains
subjects     := "subjects" "=" [string...]        # NEW: subject text
note         := "note" "=" string
```

## Worked example

```toml
version = 1

[[project]]
name           = "acme-migration"
repositories   = ["acme-api", "acme-web"]
correspondents = ["anna@acme.example", "acme.example"]
subjects       = ["[ACME]", "Acme rollout"]
note           = "Everything for the Acme rollout"

[[project]]
name           = "admin"
subjects       = ["timesheet", "expenses"]
```

One project may be named by repositories, correspondents, subjects, or any combination. A project with none
of them is still valid — you have declared it exists, and it stays listed while empty.

## How a correspondent matches

An entry containing `@` is an **address rule**, compared whole after normalisation (lowercased, trimmed,
display name and angle brackets removed).

An entry with no `@` is a **domain rule**, matched by suffix on the address's domain:

| Rule | `anna@acme.example` | `bob@mail.acme.example` | `eve@notacme.example` |
|---|---|---|---|
| `acme.example` | matches | matches | **no** — suffix matching is on domain labels, not on characters |

A rule matches when the address appears in **any** role on the message — sender or any recipient (FR-034).
Since only sent mail is recorded, in practice this means the recipients.

## How a subject matches

**Case-insensitive substring.** `[ACME]` matches `Re: [ACME] rollout plan`. There is no wildcard syntax and
no regular expression support.

This is deliberate, and it is the one place this contract refuses a feature people will ask for. The
convention worth serving is the bracketed tag — `[ACME]`, `[INV-2231]` — and under glob matching `[ACME]`
is a **character class** meaning "any one of A, C, M, E", so the most natural rule anyone could write would
match nearly every subject and quietly mis-attribute a year of mail. Regular expressions avoid that trap and
introduce their own: an unanchored pattern that matches everything, and a rule that cannot be read back in
six months and understood. Attribution feeds a billing record; being explicable is worth more here than
being expressive. See [research R11](../research.md).

## Precedence

Evaluated in this order, first match wins:

| Order | Rule | Recorded as |
|---|---|---|
| 1 | A user correction | `0001`'s correction, overriding everything |
| 2 | Subject rule, in declaration order | `mapping:subject` |
| 3 | Address rule, in declaration order | `mapping:correspondent` |
| 4 | Domain rule, in declaration order | `mapping:correspondent-domain` |
| 5 | Nothing matched | `mapping:ad-hoc-domain` |

**A subject rule beats a correspondent rule** because a subject is a statement about *this message*, while a
correspondent is a statement about a person who may work on several things.

**An address rule beats a domain rule** regardless of declaration order. Any other choice would let a broad
domain rule declared early make every precise rule below it unreachable — the kind of silent shadowing that
is very hard to notice in a billing record.

Within a level, **declaration order** decides. Order is a property of the file's text, so the same mailbox
read twice in different orders attributes identically (SC-010b).

## Faults

| Fault | Severity | Why |
|---|---|---|
| Two projects claiming the same address | blocking | Genuinely ambiguous; the user must choose |
| Two projects claiming the same domain | blocking | As above |
| The same subject text in two projects | blocking | As above |
| A correspondent that appears in no stored mail | **warning** | Mapping a colleague before they mail you is reasonable (FR-046) |
| A subject rule that matches nothing | **warning** | As above |
| An empty string in `subjects` | blocking | It would match every message |
| A malformed address in `correspondents` | blocking | It can never match, so it is a typo, not an intention |

Every fault is reported in one pass, as `0002` and `0003` both require.

## What changing this file costs

Nothing is re-read. `ikwyd projects rederive` re-attributes stored mail from the mapping alone, contacting
no account and opening no socket — enforced structurally, because `projects/` cannot import `mail/`, `net/`
or `socket`, and a test asserts it. This is `0003`'s guarantee extended to a source that would be far more
expensive to re-fetch.
