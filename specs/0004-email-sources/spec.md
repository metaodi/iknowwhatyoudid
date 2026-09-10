# Feature Specification: Email Sources and Correspondent Attribution

**Feature Branch**: `0004-email-sources`

**Created**: 2026-09-10

**Status**: Draft

**Input**: User description: "I want a new source for email. There are some generic parts about e-mail like it has a sender/recipient, a date it was sent and a subject line. It should be possible to map either recipients/senders or subject lines to a project. And since there are multiple sources of email this is a bigger feature. To start I want to support Outlook (M365, not sure if it's possible to read locally or if a connection to the Outlook server is neeeded and how to handle the authentication, this is a company account). Privately I use GMail and Hey for email, so I want to be able to ingest and query those services as well. I guess this could be either through their respective API or IMAP, not sure what the best approach is here."

## Overview

Mail is the largest trace a working day leaves. A commit says a repository was touched; a mail says *who
you were dealing with*, which is usually what a timesheet line is actually about. This feature makes mail
evidence in the same way `0003` made git history evidence: read it, normalise it to one shape regardless
of where it came from, attribute it to a project, and never touch the mailbox.

Three accounts are in scope, in priority order: a **Microsoft 365 work account**, a **Gmail account**, and
a **Hey account**. They are three very different systems, and the whole point of the design is that only a
thin layer knows that. Everything downstream — storage, attribution, correction, querying — sees one
generic activity shape with a sender, recipients, an instant, and a subject.

What counts as evidence here is **mail the user sent**. A message you wrote is something you did, at a
known moment; a message that arrived in your inbox is something that happened to you, and a mailbox full
of newsletters and automated notifications would bury the signal it was meant to provide.

This feature also extends the project mapping introduced by `0003`. Until now a project could only be
named by its repositories. It must now also be nameable by **who you corresponded with** and by **what the
subject line says**, because that is how mail identifies work.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Work mail becomes evidence (Priority: P1)

I configure my Microsoft 365 work account. I run an ingestion. I ask what happened last Tuesday, and the
mail I sent that day appears alongside my commits — each one a point in time with who it was with and what
it was about. Nothing in my mailbox changes: no message is marked read, no folder is touched, nothing is
sent.

**Why this priority**: This is the account timesheets are actually about. It is also the hardest one —
a company tenant, an administrator who may or may not permit the access, and a consent flow — so proving
it end to end is what tells us the feature is real. Delivering it alone already replaces "what was I doing
on the 14th?" with an answer.

**Independent Test**: Configure one work account against recorded fixture responses, ingest, and query a
date range. Verify every message the user sent appears once with the right recipients, instant and subject,
that received mail is absent, that the mailbox is provably unmodified, and that no message body is anywhere
in the store.

**Acceptance Scenarios**:

1. **Given** a configured work account with a valid credential, **When** I ingest, **Then** each message
   **I sent** within the configured scope becomes one activity carrying its recipients, instant and
   subject, and nothing else from the message.
2. **Given** mail I received but never replied to, **When** I ingest, **Then** it is not recorded, and the
   output says plainly that received mail is outside what this tool reads.
3. **Given** an ingestion has completed, **When** I compare the mailbox before and after, **Then** no
   message has been marked read, moved, labelled, deleted or sent, and no draft exists that did not before.
4. **Given** I ingest a second time with nothing changed at the source, **When** it completes, **Then** zero
   new activities are recorded.
5. **Given** my credential has expired or been revoked, **When** I ingest, **Then** the run reports that
   account as failed with a reason I can act on, other configured accounts still ingest, and nothing
   already stored is lost.
6. **Given** no network connection, **When** I query mail already ingested, **Then** it answers in full.

---

### User Story 2 - Mail lands on the right project (Priority: P2)

I say in my project mapping that anything with `anna@acme.example` or with `[ACME]` in the subject belongs
to the Acme migration. From then on, mail with Anna is Acme work — and when I get the mapping wrong, I fix
one line and re-derive without re-downloading a year of mail.

**Why this priority**: Without this, mail is a flat list of things that happened. With it, mail answers
"how much of Tuesday was Acme?" — the actual question. It is P2 only because it needs mail to exist first.

**Independent Test**: Ingest fixture mail, apply a mapping with one correspondent rule and one subject
rule, and verify each message lands where the mapping says. Then change the mapping, re-derive with the
network unavailable, and verify the attributions move and every hand correction survives.

**Acceptance Scenarios**:

1. **Given** a mapping naming a correspondent, **When** a message has that address as sender or recipient,
   **Then** the message is attributed to that project, and the view says the correspondent rule is why.
2. **Given** a mapping naming a subject pattern, **When** a message's subject matches it, **Then** the
   message is attributed to that project, and the view says the subject rule is why.
3. **Given** I change the mapping, **When** I re-derive, **Then** every affected message moves to its new
   project, zero mailboxes are contacted, and zero network connections are opened.
4. **Given** I have hand-corrected one message's project, **When** the mapping changes and I re-derive,
   **Then** my correction still stands and still overrides the mapping.
5. **Given** a message matches no rule at all, **When** I look at it, **Then** it sits in an ad-hoc project
   named after its recipients' domain, marked ad hoc so it never reads as a project I chose.
6. **Given** a message matches both a correspondent rule and a subject rule naming different projects,
   **When** I look at it, **Then** it belongs to the subject rule's project, and the view says which rule
   won.

---

### User Story 3 - Personal mail from Gmail (Priority: P3)

I add my Gmail account. Its mail appears in the same record, in the same shape, under the same attribution
rules as my work mail — with a different credential and, if I want, a different set of folders.

**Why this priority**: It proves the generic shape is genuinely generic rather than Microsoft's shape with
a coat of paint. That proof is worth having before a fourth source is ever contemplated. It is P3 because
personal mail rarely lands on a billable timesheet line.

**Independent Test**: Configure a Gmail account against recorded fixture responses alongside the work
account, ingest both in one run, and verify both produce identical activity shapes and obey the same
mapping rules — with no provider-specific handling anywhere downstream of reading.

**Acceptance Scenarios**:

1. **Given** both a work and a Gmail account are configured, **When** I ingest, **Then** both are read in
   one run and each account's failure is independent of the other's.
2. **Given** a Gmail message and a work message with the same correspondent, **When** the mapping names that
   correspondent, **Then** both are attributed to the same project by the same rule.
3. **Given** I query a day, **When** the results are shown, **Then** each activity says which account it
   came from, so two accounts are never silently conflated.

---

### User Story 4 - Personal mail from Hey (Priority: P4)

I add my Hey account, and it behaves exactly as the other two do.

**Why this priority**: Lowest value per unit of work, and the account most likely to contribute nothing to
a timesheet. It is in scope because the user has it, and because a third provider is the real test of
whether adding a fourth is a small change or a rewrite.

**Independent Test**: Configure a Hey account against recorded fixture responses and verify it produces the
same activity shape and obeys the same rules, with no change required to storage, attribution or querying.

**Acceptance Scenarios**:

1. **Given** a Hey account is configured, **When** I ingest, **Then** its mail is recorded in the same shape
   as every other account's.
2. **Given** Hey exposes something the other providers do not, **When** it is read, **Then** it is either
   normalised into the generic shape or deliberately not stored — never leaked into the shape as a
   provider-specific field other sources must then pretend to have.

---

### Edge Cases

- **A message with no subject.** Recorded with an empty subject and shown as such — never given an invented
  title, because a blank subject is itself information about the kind of message it was.
- **A message with fifty recipients.** Recorded in full; a broadcast is evidence of something different from
  a two-person exchange, and truncating the recipient list would hide that.
- **A message I sent to myself.** Recorded once, and counted as mine.
- **A thread.** Every message in it is its own activity at its own instant. Threads are not collapsed:
  a reply three weeks later is not evidence of work three weeks ago.
- **A message whose date is missing, absurd, or in the future.** Handled exactly as `0001` decided for any
  record: a future-dated activity is accepted and flagged rather than discarded or silently corrected.
- **A message that arrives while an ingestion is running.** Either read by this run or the next; never
  half-read, never counted twice.
- **A message deleted at the source between two runs.** Governed by `0001`'s withdrawal rule: it is marked
  withdrawn by an exhaustive sweep, never by an incremental run, and never deleted from the store.
- **A mailbox that has been archived or a folder that has been renamed.** Reported by name as not found,
  and the remaining folders are still read.
- **An address that appears in the mapping but never in any mail.** A warning naming it, never a blocking
  error — mapping a colleague before they mail you is reasonable.
- **The same human with several addresses.** They will attribute independently until the mapping names each
  address. Recognising that they are one person is explicitly not in scope here.
- **An automated sender** — build notifications, calendar invitations, newsletters. In scope of what is read
  or not, per Question 1; if read, attributable like anything else.
- **A very large mailbox.** Ingestion is resumable and its cost is proportional to what is new, not to the
  size of the mailbox.
- **Company policy forbids the access this needs.** The tool must say so plainly at configuration time,
  before a year of history is attempted, rather than failing message by message.

## Requirements *(mandatory)*

### Configuring an account

- **FR-001**: The system MUST let a user declare one or more mail accounts in the configuration file
  introduced by `0002`, each with its own kind, credential reference and read scope.
- **FR-002**: The system MUST NOT write to the configuration file, and MUST NOT require a mail account to be
  configured for any other part of the tool to work.
- **FR-003**: The system MUST let a user declare which addresses are **theirs** for each account, so that
  mail they sent can be told from mail they received.
- **FR-004**: The system MUST let a user narrow what is read — by folder, label, or equivalent — and MUST
  report at configuration time when a named folder or label does not exist.
- **FR-005**: The system MUST let a user declare a start date per account, and MUST NOT read anything older
  than it.
- **FR-006**: The system MUST validate an account's configuration without contacting the account, and MUST
  report every fault in one pass rather than one per run.
- **FR-007**: The system MUST report, for each configured account, whether it is ready to read, and if not,
  precisely what is missing.

### Credentials and authorisation

- **FR-008**: The system MUST reference credentials by name only in configuration, and MUST NOT store a
  credential value in the configuration file, the database, the log, or any output.
- **FR-009**: The system MUST request the narrowest read-only authorisation each provider offers, and MUST
  state in its plan exactly which authorisation it requests and why.
- **FR-010**: The system MUST report clearly when a credential is absent, expired, revoked, or refused by an
  administrator, and MUST distinguish these from one another — "not permitted" and "not configured" require
  different actions from the user.
- **FR-011**: The system MUST let a user check that an account is reachable and its credential accepted,
  without ingesting anything.
- **FR-012**: The system MUST NOT require a credential to be re-entered on every run.

### Reading, and not writing

- **FR-013**: The system MUST NOT create, modify, delete, send, move, label, archive, flag or mark as read
  anything in any mail account, under any circumstance including failure and interruption.
- **FR-014**: The system MUST NOT alter the read/unread state of any message, including as a side effect of
  reading it.
- **FR-015**: The system MUST read incrementally, so that a second run costs an amount proportional to what
  has changed rather than to the size of the mailbox.
- **FR-016**: The system MUST survive an interrupted run without loss or duplication, and MUST resume rather
  than restart.
- **FR-017**: The system MUST continue reading the remaining accounts when one account fails, and MUST name
  the account that failed and why.
- **FR-018**: The system MUST respect a provider's rate limits and MUST NOT retry in a way that risks the
  user's account being throttled or suspended.
- **FR-019**: The system MUST NOT contact any destination other than the configured accounts.

### What is stored, and what is never stored

- **FR-020**: The system MUST record, for each message: its sender, its recipients, the instant it was sent,
  its subject line, which account it came from, and a stable identifier.
- **FR-021**: The system MUST record **which of the user's own addresses** sent the message, so that an
  account holding several addresses can be told apart later without re-reading anything.
- **FR-022**: The system MUST record the instant a message was sent with its original offset from UTC
  preserved, so that a message sent at 9am local time reads as 9am.
- **FR-023**: The system MUST NOT store any message body, in whole or in part.
- **FR-024**: The system MUST NOT store, download, or open any attachment, nor record an attachment's
  content; the fact that a message had attachments MAY be recorded.
- **FR-025**: The system MUST NOT store any duration or effort estimate against a message. A message is a
  point in time; turning points into hours belongs to a later feature.
- **FR-026**: The system MUST store mail in the same normalised form as every other source, so that querying,
  correcting and exporting need no knowledge of which provider it came from.
- **FR-027**: The system MUST record enough to rebuild every derived conclusion without contacting the
  account again.

### One shape, three providers

- **FR-028**: The system MUST expose mail from every provider as one activity shape, and MUST NOT surface a
  provider-specific field that other providers cannot supply.
- **FR-029**: The system MUST make adding a further mail provider a matter of supplying the reading part
  alone, with no change to storage, attribution, correction or querying.
- **FR-030**: The system MUST record which account each activity came from, and MUST NOT merge two accounts
  into one identity even where they share addresses.
- **FR-031**: The system MUST normalise addresses consistently across providers, so that the same
  correspondent written two ways is recognised as one address.

### Attributing mail to a project

- **FR-032**: The system MUST let a user map a **correspondent** — an address, or a whole domain — to a
  project in the mapping file introduced by `0003`.
- **FR-033**: The system MUST let a user map a **subject pattern** to a project.
- **FR-034**: The system MUST apply a correspondent rule when the address appears as either the sender or
  any recipient of a message. Since only sent mail is recorded (FR-048), in practice this matches on
  recipients; the rule is stated in full so that widening the scope later changes one requirement, not the
  attribution model.
- **FR-035**: The system MUST record, for every attributed message, both the rule that produced the
  attribution and the evidence it rested on — which address or which pattern matched.
- **FR-036**: The system MUST attribute each message to **exactly one project**, as `0003` does for each
  commit. Where several rules match, a **subject rule wins over a correspondent rule**; where two rules of
  the same kind match, the one **declared first** in the mapping file wins. The outcome MUST be
  deterministic and MUST NOT depend on the order in which mail was read.
- **FR-037**: The system MUST record which rule won for a message that several rules matched, so that a
  message filed under one project when the user expected another is explicable without guesswork.
- **FR-038**: The system MUST attribute a message matching **no rule** to an ad-hoc project named after its
  recipients' domain, marked ad hoc, exactly as `0003` names an unmapped repository after itself. No stored
  activity is left unattributed.
- **FR-039**: The system MUST choose that domain deterministically: from the message's recipients, discard
  every address whose domain is one of the user's own; of those remaining take the **most frequent** domain,
  breaking a tie by taking the alphabetically first; where none remain — a message sent only to colleagues —
  use the user's own domain.
- **FR-040**: The system MUST stop listing an ad-hoc project once a mapping change leaves it holding
  nothing, and MUST say which ad-hoc projects it removed.
- **FR-041**: The system MUST make an attribution the tool inferred visually distinguishable from one the
  user confirmed, in every view without exception.
- **FR-042**: The system MUST let a user correct any message's project, and that correction MUST override
  any rule.
- **FR-043**: A user's correction MUST survive re-ingestion, re-derivation, and a mapping change.
- **FR-044**: The system MUST re-attribute already-stored mail when the mapping changes, without contacting
  any account and without opening any network connection.
- **FR-045**: The system MUST be able to show what a mapping change would do before it does it, and the
  preview MUST match the result exactly.
- **FR-046**: The system MUST report a mapping entry that matches no mail as a warning, never as an error.
- **FR-047**: The system MUST NOT let a faulty mapping prevent mail from being read; reading and attributing
  are separately recoverable.

### Which mail counts

- **FR-048**: The system MUST record **only mail the user sent** — a message whose sender is one of that
  account's declared own addresses. Mail the user merely received MUST NOT be recorded.
- **FR-049**: The system MUST state, wherever mail activity is listed or summarised, that received mail is
  outside what it reads. A day that looks empty must be distinguishable from a day that was empty.
- **FR-050**: The system MUST let a user exclude a folder, label or recipient pattern from being read at
  all, so that a mailing list need never enter the store.

### Seeing it

- **FR-051**: Every capability in this feature MUST be usable from the command line, and every command that
  emits data MUST offer a machine-readable form.
- **FR-052**: The system MUST let a user list mail activity by date range, by account, and by project.
- **FR-053**: The system MUST show mail and git activity together in one chronological record.
- **FR-054**: The system MUST let a user see which correspondents contribute most to a project, so that a
  wrong or missing mapping is discoverable rather than something to be guessed at.
- **FR-055**: The system MUST answer every query about already-ingested mail with no network connection.

### Key Entities

- **Mail account**: A configured mailbox the user owns. Has a kind, a credential reference, a set of
  addresses that are the user's own, a read scope, and a start date. Accounts are never merged.
- **Message activity**: One message the user sent, at one instant. Carries the sending address, the
  recipients, the subject, the account it came from, and a stable identifier. Carries no body, no attachment
  content, and no duration.
- **Correspondent**: An address the user sent mail to. Normalised, so one address written two ways is
  recognised as one — but two addresses belonging to one person remain two correspondents.
- **Correspondent rule**: A mapping from an address or a domain to a project.
- **Subject rule**: A mapping from a subject pattern to a project.
- **Project**: Unchanged from `0003` — the unit everything is recorded against. A project may now be named
  by repositories, by correspondents, by subject patterns, or by any combination.
- **Attribution**: Unchanged from `0003` — the link from an activity to a project, carrying the rule and the
  evidence that produced it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from an unconfigured tool to seeing last week's work mail, attributed to
  projects, by editing two files and running two commands.
- **SC-002**: After a full ingestion, every message in every configured mailbox is provably unchanged —
  same read state, same folder, same flags — verified by comparing the mailbox before and after.
- **SC-003**: Zero messages are created, sent, moved, deleted or marked read across the entire test suite.
- **SC-004**: 100% of stored mail activities carry a sender, an instant and a subject field, and 0% carry
  any part of a message body or any attachment content, verified by searching the whole store for planted
  sentinel text.
- **SC-004a**: 0% of stored mail activities are messages the user did not send, verified against a fixture
  mailbox containing both.
- **SC-005**: 0% of stored mail activities carry a duration or effort estimate.
- **SC-006**: Re-running an ingestion with nothing changed at the source records zero new activities.
- **SC-007**: A second ingestion after a week's new mail costs time proportional to the new mail, not to the
  size of the mailbox.
- **SC-008**: Changing the project mapping and re-deriving re-attributes every affected message while
  opening zero network connections and contacting zero mailboxes.
- **SC-009**: 100% of user corrections survive re-ingestion and a mapping change, and continue to override
  every rule.
- **SC-010**: Every attribution in every view is identifiable as either inferred or user-confirmed, with no
  ambiguous cases.
- **SC-010a**: 100% of stored mail activities carry exactly one project, and every one that several rules
  matched records which rule won.
- **SC-010b**: Attributing the same fixture mailbox twice, read in a different order each time, produces
  identical attributions.
- **SC-011**: One account failing never prevents the others from being ingested, and the failed account is
  named with a reason in the output.
- **SC-012**: A credential that is missing, expired, or refused by an administrator produces three
  distinguishable messages, each naming what the user must do next.
- **SC-013**: A mapping change can be previewed, and the preview's predicted moves match what applying it
  actually does, exactly.
- **SC-014**: Mail from all three providers produces activities of identical shape, verified by the same
  assertions passing against each provider's fixtures unchanged.
- **SC-015**: All queries over already-ingested mail succeed with the network unavailable.
- **SC-016**: A mail account can be configured, validated and diagnosed without contacting the account.

## Assumptions

- **Only sent mail is read.** Received mail is deliberately out of scope, which narrows the feature
  considerably: no inbox is enumerated, and the volume and sensitivity of what is stored both fall sharply.
  Worth noting that this is narrower than the original description of feature `0002`, which spoke of "what
  email were sent or received on each day" — the decision here supersedes that, and FR-049 requires the
  tool to say so in its output rather than let a quiet day look like an idle one. Widening the scope later
  is a change to FR-048, not to the attribution model, because FR-034 is already written in terms of sender
  *or* recipient.
- **Every message lands on exactly one project.** Where several rules match, a subject rule beats a
  correspondent rule and the earlier-declared rule beats the later one. This keeps the model identical to
  `0003`, where one commit has one project, so nothing downstream needs to learn about shared work. A
  genuinely shared message is filed under one project and corrected by hand where that matters. The cost is
  accepted knowingly: the alternative — one message on several projects — makes every "how much time on
  Acme?" answer ambiguous about double-counting, and that ambiguity would reach a billing record.
- **Unmatched mail falls back to the recipients' domain.** This mirrors `0003`, where an unmapped
  repository becomes a project named after itself: nothing is left unattributed, and the ad-hoc name is a
  real hint about the work rather than a placeholder. Expect many such projects at first; they disappear as
  the mapping grows, and FR-040 removes each one as soon as it holds nothing.
- **Only metadata is stored.** The user's description enumerated sender, recipient, date and subject, and
  this specification treats that enumeration as the boundary: no body, no attachment content, ever. This
  follows the precedent set in `0003`, where a commit's subject is stored and its body never is. Mail
  bodies are considerably more sensitive than commit messages, so the same rule applies with more force.
- **Reading is remote, not from local files.** Reading a local Outlook data file was considered and is
  assumed out of scope: such a file is a live database the desktop client holds open, and operating on it
  risks exactly the corruption the read-only principle exists to prevent. Whether a provider is best read
  through its own interface or through a general mail protocol is a design decision for the plan, not a
  requirement here — the specification requires only that the choice be read-only, incremental, and
  narrowly authorised.
- **A company tenant may refuse.** The work account belongs to an employer who may restrict the access this
  feature needs. This is assumed to be a real possibility rather than an edge case, so the requirement is
  that the tool detect and explain it early (FR-010), not that it be circumvented. If the tenant refuses
  outright, User Story 1 cannot be delivered against that account and the priority order should be revisited
  rather than worked around.
- **One address, one correspondent.** Recognising that two addresses belong to the same human is a separate
  concern and is not attempted here.
- **Threads are not collapsed.** Each message stands alone at its own instant.
- **Contacts are not read.** Only the addresses appearing on messages are recorded; no address book,
  directory or organisational chart is consulted.
- **Calendar is not in scope.** Invitations arriving as mail are messages like any other; the calendar
  itself is a later feature.
- **Existing foundations are reused unchanged**: the store, migrations, corrections and withdrawal rules
  from `0001`; the configuration file, credential referencing, and source lifecycle from `0002`; the
  project entity, mapping file, ad-hoc fallback and re-derivation from `0003`. This feature extends the
  mapping file; it does not introduce a second one.
- **Fixtures only.** Per the constitution, no test may run against the developer's own live mailbox. Every
  provider is tested against recorded responses.
