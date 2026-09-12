# Specification Quality Checklist: Getting Configured — `init` and `edit`

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-12
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

**16/16 passing.** 32 functional requirements, 15 success criteria, 3 user stories.

Both clarifications answered:

| Question | Answer | Where it landed |
|----------|--------|-----------------|
| Validate after editing | **No** — the command opens a file and stops | FR-025; US3 scenario 6; Assumptions |
| Create `credentials.toml` | **Yes**, readable by its owner alone | FR-014 to FR-017; US1 scenarios 1–2; SC-005a, SC-005b |

### The requirement amendment

`0002` FR-002 and `0003` FR-029 are **narrowed, not relaxed**: from "never write" to "never
modify, reformat, or reorder anything the user wrote". FR-004 keeps the existing
whole-surface test and extends it to cover the new commands, so the protection that mattered
stays checkable.

### Consequences of answering yes to credentials

Recorded because this is the riskier of the two answers, and the recommendation had been no:

- The feature now creates a file whose entire purpose is to hold secrets, so a permissions
  mistake has a worse blast radius than one in `config.toml`. **FR-015** answers it by
  requiring permissions to be in place *before* any content is written — the same discipline
  `0004` used for `tokens.toml` — and **SC-005a** verifies it by asking the operating system
  rather than trusting the write.
- **FR-016** makes the no-overwrite rule strongest here: overwriting `config.toml` costs a
  preference, overwriting `credentials.toml` costs a secret the user cannot recover from a
  template.
- **FR-027** was added rather than assumed: there is deliberately **no** command that opens
  the credentials file in an editor. Handing a file of secrets to whatever `$EDITOR` happens
  to name is a risk with no matching benefit, and `init` prints the path for anyone who
  wants it.

### Settled without asking, each recorded in Assumptions

- `edit` does not create a missing file — one creator is far easier to guarantee than two;
- `$VISUAL`/`$EDITOR` beats the operating system's association, because a user who set one
  has already said what they want, and `.toml` often has no association at all;
- a partial result is reported rather than rolled back — a reported partial leaves the user
  further forward than an all-or-nothing failure.

### To carry into `/speckit-plan`

This feature makes `edit` the **second** interactive command, and `0004`'s
`cli/mail_commands.py` states in as many words that `sources authorise` is the only one.
That claim must be updated rather than left to become quietly false. FR-026 keeps the part
that actually matters: neither command may be reachable from anything that reads a source,
so a scheduled run can never block on an editor.
