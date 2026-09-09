# Specification Quality Checklist: Configurable Sources

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-09
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

### Iteration 1 (2026-09-09)

Three open items, all scope or security decisions with no safe default: extensibility scope,
whether the three connectors ship inside this feature, and where the person-to-project mapping
lives. Two of them held the scope boundary open, so "Scope is clearly bounded" failed with them.

### Iteration 2 (2026-09-09) — all items pass

All three resolved by the user; the specification was updated and re-validated.

- **Extensibility scope** — source kinds ship inside this project only (FR-031). The kind
  declaration is nonetheless specified as a public boundary (FR-032) so run-time discovery
  could be enabled later without breaking anyone's configuration file. Keeps third-party code
  away from a process holding mail and calendar credentials, without painting the design into a
  corner. User Story 4 gained an acceptance scenario asserting that an externally offered kind
  is not loaded.
- **Feature boundary** — this feature delivers the configuration contract only (FR-033); the
  git, mail, and calendar connectors each become their own specification, expected as `0003`,
  `0004`, `0005`. This matches the constitution's connector rule, under which each connector's
  own `plan.md` must document its endpoints, credential scopes, and retention. The contract is
  proven against a fixture source kind (FR-034, SC-012), so nothing here depends on a real
  account existing.
- **Attribution boundary** — the configuration declares which identities are the user's own
  (FR-040) and carries no project mapping; a configuration attempting to declare one is
  rejected rather than ignored (FR-041). Consistent with
  `specs/0001-local-store-foundation`, which puts attribution rules in a later feature.

Requirement count grew from 41 to 45 and success criteria from 11 to 12 as a result.

Deliberate non-decisions, correctly left to `plan.md` per the constitution:

- The concrete configuration file format. YAML is recorded in Assumptions as the expected
  choice, but no requirement depends on it; alternatives considered belong in `plan.md`.
- Whether credentials live in the OS keyring or a user-only-readable file, and how each
  source's authorization flow is driven.

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
