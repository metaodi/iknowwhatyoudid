# Contract: the message shape

One shape, whatever produced it. FR-028 says no provider-specific field may surface; this is the list that
enforces it.

## The normalised message

Produced by `mail/message.py` from a provider's raw headers, and the only thing `mail/reader.py` sees.

| Field | Type | Source | Notes |
|---|---|---|---|
| `message_id` | text | `Message-ID` header | Normalised: angle brackets stripped, trimmed, lowercased |
| `message_id_is_derived` | bool | — | True where the message had no `Message-ID` and the provider's own id was used instead |
| `sent_at` | instant with offset | `Date` header, or `sentDateTime` | **The original UTC offset is preserved** (FR-022) |
| `sender` | address | `From` | Normalised per [research R12](../research.md) |
| `sent_by` | address | — | Which of the account's declared addresses matched the sender (FR-021) |
| `recipients` | list of (address, role) | `To`, `Cc` | Role is `to` or `cc` |
| `subject` | text | `Subject` | Verbatim, including an empty string |
| `has_attachments` | bool | `hasAttachments`, or presence of a multipart part | The **fact** only — never a name, size or content |
| `account` | text | configuration | The source name (FR-030) |
| `provider` | text | — | `graph`, `gmail`, `hey`, `mbox` — diagnostics only |

## Fields that must never exist

| Never | Requirement | How it is verified |
|---|---|---|
| Body, in whole or in part, including a preview | FR-023 | Sentinel text planted in every fixture body; the entire store is searched for it (SC-004) |
| Attachment name, size, or content | FR-024 | Same sentinel technique on attachment filenames |
| `Bcc` | plan decision | Asserted absent; it names people the other recipients were not told about, and attribution never needs it |
| Duration or effort | FR-025 | Asserted null on every mail record (SC-005) |
| Any provider-specific field | FR-028 | The same shape assertions run unchanged against all four providers' fixtures (SC-014) |

## Normalisation rules

**Addresses**: trim, drop the display name and angle brackets, lowercase everything. Nothing else — no
Gmail dot-stripping, no `+tag` removal. Those would merge addresses the user never said were the same, and
`+tag` is often exactly the signal a correspondent rule wants ([research R12](../research.md)).

**Instants**: parsed with `email.utils.parsedate_to_datetime`, which preserves the offset — verified:
`Tue, 10 Mar 2026 09:14:00 +0100` → `2026-03-10 09:14:00+01:00`. A message with an unparseable or absent
date is **skipped and reported by identifier**, never given an invented time: a wrong instant in a timesheet
is worse than a missing message, because only the missing one gets noticed.

**Subjects**: taken verbatim. Encoded-word headers (`=?UTF-8?B?…?=`) are decoded with `email.header`; a
subject that cannot be decoded keeps its replacement characters rather than failing the message — the same
trade `0003` settled on for commit subjects.

**Empty subject**: recorded as an empty string and shown as such. Never given an invented title — a blank
subject is itself information about the kind of message it was.

## Identity and deduplication

`source_id` is `mail:<message_id>`.

The same message reaching the store twice — read from Graph and again from an exported archive — is **one
record**, because `Message-ID` is assigned once by the sending system and travels with the message. This is
why the identifier is the header rather than any provider's own id, which would make the same message look
like two ([research R10](../research.md)).

Where `message_id_is_derived` is true the identifier is `mail:<provider>:<their-id>`, which cannot collide
with a real `Message-ID` and is visibly weaker.

## Withdrawal

| Provider | May a sweep withdraw? |
|---|---|
| Microsoft 365 | Yes — a delta says a message was removed |
| Gmail | Yes — history says a message was removed |
| Hey | Yes — a sweep re-searches the window, and a message the search no longer returns has gone |
| Exported archive | **No.** `withdrawable: false` in the payload |

An archive is a snapshot; its silence about a message means nothing about the mailbox. The store already
refuses to withdraw a record whose payload declares it non-withdrawable — the protection built for git
branch creations, which had the same property ([research R13](../research.md)).
