# Contract: `projects.toml`

**Format**: TOML, parsed with stdlib `tomllib` · **Location**: beside `config.toml`

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\iknowwhatyoudid\projects.toml` |
| macOS | `~/Library/Application Support/iknowwhatyoudid/projects.toml` |
| Linux | `$XDG_CONFIG_HOME/iknowwhatyoudid/projects.toml`, else `~/.config/…` |

Overridable with `--projects PATH`, alongside `--config`.

**The tool never writes this file** (FR-029). As with `config.toml`, `tomllib` is read-only by
construction, so there is no write path to reach for.

**An absent file is valid** (FR-030). Every repository then falls back to its own ad-hoc project, which is
the state a new user starts in — the tool works before it is configured, and mapping is how you improve it.

## Why this is a separate file

`0002`'s FR-041 forbids a project mapping in `config.toml` and rejects one with a blocking
`attribution-not-allowed` finding. That check is implemented and tested, and stays.

The separation is not bureaucratic. Attribution rules change often and are expected to be wrong at first;
the configuration that says *where to read from* is not. Keeping them apart means a bad mapping cannot stop
the tool reading, and re-attributing a year of history is a change to one small file.

## Grammar

```text
projects   := version? project*
version    := "version" "=" integer            # optional; defaults to 1
project    := "[[project]]" name repositories? note?
name       := "name" "=" string                # unique, case-insensitively
repositories := "repositories" "=" [string...]  # repository names or paths
note       := "note" "=" string                # free text, for the user's own benefit
```

## Worked example

```toml
# iknowwhatyoudid — projects
# Which repositories belong to which project. Repositories not named here get a
# project of their own, named after the repository.

version = 1

[[project]]
name         = "acme-migration"
repositories = ["acme-api", "acme-web", "~/dev/acme-infra"]
note         = "Everything for the Acme rollout"

[[project]]
name         = "internal-tooling"
repositories = ["iknowwhatyoudid", "dotfiles"]

# A project with no repositories is valid: you have declared it exists, and it stays
# listed even while empty. Mail and calendar will map onto it in a later feature.
[[project]]
name = "admin"
```

## How a repository is matched

An entry matches a discovered repository if it equals, case-insensitively:

1. the repository's **name** (its working-tree directory name), or
2. any of its **observed paths**, resolved and with `~` expanded.

Names are matched before paths. A name is the common case and survives the repository moving; a path is
there for when two repositories share a name.

## Validation

Reuses `0002`'s finding model exactly — every fault in one run, each located by project and entry, blocking
separated from warning — so there is one way of being told about a mistake.

| Finding | Severity | Requirement |
|---|---|---|
| `duplicate-project-name` — two projects with the same name, case-insensitively | blocking | FR-027 |
| `unknown-top-level-key` | blocking | Refuse rather than ignore, as in `config.toml` |
| `invalid-project-name` — empty or whitespace-only | blocking | FR-027 |
| `repository-mapped-twice` — one repository claimed by two projects | blocking | An activity must land on exactly one project (FR-025) |
| `repository-not-found` — an entry matches no discovered repository | **warning** | FR-042. The repository may simply not be configured yet, or may be on another machine |
| `file-permissions` / `file-permissions-unverified` | warning | As for the other configuration files |

`repository-not-found` is a warning rather than an error on purpose: mapping a repository you have not yet
configured is a reasonable thing to do, and refusing the whole file over it would make the mapping harder
to edit than it needs to be. It is still reported, because a mapping that silently does nothing is how a
user comes to believe their time is being attributed when it is not.

## Changing the mapping

Editing this file changes nothing on its own. `ikwyd projects rederive` applies it, reading no repository
and opening no socket (FR-037), and `--dry-run` shows what would move before anything does (FR-041).

A `user_correction` continues to win over whatever this file says (FR-038). The mapping is a rule; a
correction is the user's statement, and a rule never overrides a statement.
