# Contract: what changes in `0002` and `0003`

This feature needs a requirement that two shipped features state absolutely. Principle III
says the spec is the source of truth and the code is the defect — so the specs change first,
and they change in a way that keeps what they were protecting.

## What they say today

**`0002` FR-002**, and its [config-file contract](../../0002-configurable-sources/contracts/config-file.md):

> The tool **never writes this file** (FR-002). There is no command that creates, edits, or
> reformats it.

**`0003` FR-029**, and its [mapping-file contract](../../0003-git-source-projects/contracts/mapping-file.md):

> **The tool never writes this file** (FR-029). As with `config.toml`, `tomllib` is read-only
> by construction, so there is no write path to reach for.

A test asserts it across the whole command surface:
`tests/integration/test_sources_cli.py::test_no_command_ever_writes_the_configuration_file`.

## Why they say it

Not because writing is bad. Because a tool that **rewrites** a user's configuration can lose
their comments, reorder their keys, and change what the file means without saying so. The
file is the user's statement of intent. It must come back exactly as they left it.

That reason is still right, and nothing here weakens it.

## What they say after this feature

> The tool **never modifies, reformats, reorders, or rewrites** any part of a configuration
> file the user has written. `ikwyd init` may **create** one where none exists; it will not
> touch one that does, and there is no flag that would make it.

The change is a **narrowing**, not a relaxation:

| | Before | After |
|---|---|---|
| Modify an existing file | forbidden | **forbidden** |
| Reformat or reorder | forbidden | **forbidden** |
| Overwrite | forbidden | **forbidden**, and no flag exists |
| Create where nothing exists | forbidden | permitted, by one command |
| Open in the user's editor | forbidden | permitted, reading nothing |

Creating a file that does not exist destroys nothing. Handing an existing file to the user's
own editor changes nothing — the tool does not read it, parse it, or write it back.

## Edits to make

| File | Change |
|---|---|
| `specs/0002-configurable-sources/spec.md` | FR-002 reworded, with a note that `0005` narrowed it |
| `specs/0002-configurable-sources/contracts/config-file.md` | The "never writes" sentence reworded; `ikwyd init` named as the one creator |
| `specs/0003-git-source-projects/spec.md` | FR-029, likewise |
| `specs/0003-git-source-projects/contracts/mapping-file.md` | Likewise |
| `specs/0004-email-sources/contracts/config-file.md` | It says "the rule that the tool never writes this file [is] unchanged" — now inherits the narrowed rule |
| `specs/0004-email-sources/contracts/mapping-file.md` | Likewise |

Each amendment **records that it was amended and by which feature**, rather than quietly
reading as though it had always said this. A specification whose history is edited out is
harder to trust than one that shows its working.

## The test does not go away

`test_no_command_ever_writes_the_configuration_file` stays, and grows (FR-004):

| Assertion | Before | After |
|---|---|---|
| No command alters an existing `config.toml` | yes | **yes**, plus the new commands |
| No command alters an existing `projects.toml` | — | **yes** |
| No command alters an existing `credentials.toml` | — | **yes** — the highest-stakes case |
| `init` creates where nothing exists | — | yes |
| No flag or environment variable overwrites | — | yes |

The renamed version asserts the property that actually matters:
**nothing the user wrote is ever changed.**

## What would make this amendment wrong

Recorded so a future reader can check whether it still holds:

- If `init` ever gained a `--force`, or any other way to overwrite, the narrowing would have
  become a relaxation and this document would be a fig leaf.
- If any command began reading a configuration file in order to rewrite it — normalising
  formatting, migrating a renamed key, sorting entries — the original prohibition would have
  been right and this one too weak.
- If `edit` ever wrote to the file itself rather than delegating to the user's editor.

None of those is in this feature, and FR-009, FR-021 and FR-024 each forbid one of them.
