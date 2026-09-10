# Specification Quality Checklist: Git Source and Projects

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

### Iteration 1 (2026-09-10)

Three open items: how "time spent" is derived, where the repository-to-project mapping lives, and
whether commit messages are stored. Two of them moved the outer edge of the feature, so "Scope is
clearly bounded" failed alongside them.

### Iteration 2 (2026-09-10) — all items pass

All three resolved; requirements grew 40 → 45 and success criteria 12 → 14.

- **Time spent** → **nothing is stored**. Activity is recorded as points in time; no duration, no
  effort estimate (FR-016). Git records when a commit was made and never how long the work behind it
  took, so a duration here would be an inference entering a billing record as though it were
  evidence. FR-017 requires the stored activity to be sufficient for a later summarising feature to
  derive hours from these records alone, without re-reading a repository. SC-013 asserts nothing
  stored carries a duration. Deriving hours is now explicitly out of scope.
- **Mapping location** → **its own file beside the sources configuration** (FR-028 to FR-031). This
  was the one finding that conflicted with shipped behaviour: `0002` FR-041 rejects a project mapping
  in the sources configuration with a blocking finding, and that check is implemented and tested.
  Keeping the mapping in a separate file leaves FR-041 intact and unamended — attribution rules change
  often, and a bad rule must not be able to break the configuration that says where to read from. The
  file is never written by the tool (FR-029), an absent one is valid and means everything falls back
  to ad-hoc projects (FR-030), and it is validated with the same all-faults-at-once reporting as the
  sources configuration (FR-031).
- **Commit messages** → **subject line only** (FR-015, SC-014). The subject is what makes a day's work
  recognisable when confirming a timesheet; bodies are where pasted logs, ticket text and customer
  names accumulate and buy nothing for that purpose. Bodies are out of scope, and so is any
  attribution rule that would need to read them.

Deliberate scope decision, recorded rather than left implicit: this feature introduces the **Project**
entity that `0001` and `0002` both deferred. `0001` puts attribution rules out of scope; `0002`
FR-041 defers the mapping to "a later attribution feature". That feature is this one. It does mean
`0003` is two things — a connector and an attribution layer — which the user was offered the chance to
split and chose to keep together, since a git source that cannot name a project is not useful for the
purpose the tool exists for.

Carried into `/speckit-plan`:

- The store already holds attributions (`derived_attribution`, with project, rule and evidence) and
  corrections (`user_correction`), but `project` there is a free-text column. FR-024's stable project
  identity therefore implies a schema migration, which the constitution requires to ship with the
  change and to be tested against both an empty and a populated store.
- `0002`'s `SourceReader.read()` gained `RunMode` in `0001`'s wake; FR-022 makes this the first
  feature with a real reader that must supply it, and FR-023 the first that can actually cause a
  withdrawal.

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
