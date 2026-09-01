# Specs

This directory holds all feature specifications for `iknowwhatyoudid`,
following a Spec-Driven Development (SDD) workflow. Specifications are the
source of truth: code is generated to satisfy what is written here, not the
other way around.

Before writing a new spec, read the project constitution at
[`.specify/memory/constitution.md`](../.specify/memory/constitution.md). It
defines the principles and constraints every spec must respect.

## Folder convention

Each feature or capability gets its own numbered folder:

```
specs/
  0001-example-feature/
    spec.md       # what the feature does and why (no implementation detail)
    plan.md       # how it will be implemented (architecture, stack, data flow)
    tasks.md      # concrete, reviewable task breakdown derived from the plan
    checklist.md  # optional: acceptance criteria and quality gates
```

Numbers are zero-padded and increase sequentially (`0001`, `0002`, ...).
Use a short, descriptive slug after the number, e.g. `0002-shell-history-import`.

## Workflow

1. **Constitution** – Confirm the change fits the project constitution. Update
   the constitution first if it needs to evolve.
2. **Specify** – Create a new folder under `specs/` and write `spec.md`,
   describing the desired behavior in natural language. Focus on *what* and
   *why*, not implementation.
3. **Clarify** – Review the spec for ambiguity and resolve open questions
   before planning.
4. **Plan** – Write `plan.md`, deciding the technical approach: architecture,
   data sources, data flow, and tech stack choices.
5. **Tasks** – Break the plan into `tasks.md`, a list of concrete, reviewable
   implementation tasks.
6. **Implement** – Implement only what is scoped in `tasks.md`.
7. **Verify** – Check the implementation against `spec.md` (and
   `checklist.md`, if present) before merging.

See `specs/0001-example-feature/` for a template showing the expected
structure of each artifact.
