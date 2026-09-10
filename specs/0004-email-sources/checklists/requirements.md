# Specification Quality Checklist: Email Sources and Correspondent Attribution

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-10
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

**16/16 passing.** All three clarifications were answered and folded in:

| Question | Answer | Where it landed |
|----------|--------|-----------------|
| Which mail counts as activity | Only mail the user **sent** | FR-048, FR-049; US1 scenarios 1–2; Overview; Assumptions |
| Mail matching no rule | Ad-hoc project per **recipients' domain** | FR-038, FR-039, FR-040; US2 scenario 5 |
| A message matching several rules | **One project**, subject rule beats correspondent rule, earlier declaration beats later | FR-036, FR-037; US2 scenario 6; SC-010a, SC-010b |

Two consequences of those answers were resolved here rather than deferred, because leaving either vague
would have made a requirement untestable:

- **Which domain names an ad-hoc project**, when a sent message has recipients at several. FR-039 states a
  deterministic rule (drop the user's own domains, take the most frequent of the rest, break ties
  alphabetically, fall back to the user's own domain for internal-only mail). Without it, "named after its
  recipients' domain" has no single answer for the common case of a message to two organisations.
- **What replaces the sent/received direction field**, now that direction is a constant. FR-021 instead
  records *which of the user's own addresses* sent the message — useful where an account holds several,
  and not a field invented for a caller that does not exist.

Deliberately left to `/speckit-plan` and `research.md`, with the spec stating only the constraints they
must satisfy:

- whether each provider is read through its own interface or a general mail protocol;
- how consent is obtained on a Microsoft 365 company tenant, and what happens if an administrator refuses;
- where a token lives between runs.

One risk is recorded in Assumptions rather than resolved: the work account belongs to an employer who may
forbid the access User Story 1 needs. FR-010 requires the tool to detect and explain that early. If the
tenant refuses outright, US1 is undeliverable against that account and the story priorities should be
revisited rather than worked around.
