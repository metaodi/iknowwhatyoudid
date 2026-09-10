# iknowwhatyoudid

A local tool to get information about how you spend your days.

It reconstructs how time was actually spent by reading the traces a working day leaves
behind — mail, calendar, git history, browser history, SharePoint — and turning them into
a reviewable daily record. The point is to make filling in a timesheet a matter of
confirming evidence rather than reconstructing from memory.

Everything stays on your machine. The only network traffic is to source systems you
configured yourself, and only to read from them.

## Install

```bash
uv sync
uv run ikwyd --help
```

Requires Python 3.12. `uv` provisions it.

## What works today

Features `0001` (the local store) and `0002` (configurable sources) are implemented: the
database everything reads and writes, the normalized record shape, migrations,
corrections, the configuration file, validation, the source-kind registry, credential
handling, and the CLI around all of it.

**No real connector exists yet.** `git.local`, `mail.*` and `calendar.*` ship as
*declarations* — you can configure them and they validate, but they report
`not readable` rather than pretending to work. Only the `fixture` kind actually reads
anything. Connectors are features `0003`–`0005`.

## Configure your sources

```bash
cp examples/config.toml "$APPDATA/iknowwhatyoudid/config.toml"   # Windows
ikwyd sources kinds          # what can be configured, and the settings each accepts
ikwyd sources validate       # every fault at once; contacts nothing
ikwyd sources destinations   # the whole egress surface, before anything is contacted
ikwyd ingest                 # read from every ready source
```

The configuration file holds **no secrets** — credentials are referenced by name, with
values in `credentials.toml` beside it. The tool never writes either file.

## Commands

```bash
ikwyd sources list            # every configured source and its status
ikwyd sources validate        # check the configuration; contacts nothing
ikwyd sources check NAME [--live]
ikwyd sources kinds [NAME]    # available kinds and their settings
ikwyd sources destinations    # every destination the configuration could contact
ikwyd ingest [--source NAME] [--dry-run] [--sweep]

ikwyd store info              # where the store is and what it holds
ikwyd store check             # full integrity check
ikwyd store migrate           # apply pending schema migrations
ikwyd store protection        # file permissions and disk-encryption state

ikwyd records query --from 2026-03-01 --to 2026-03-31 [--source NAME]

ikwyd corrections export --out corrections.jsonl
ikwyd corrections import corrections.jsonl [--dry-run]
ikwyd corrections list [--pending]

ikwyd derived discard         # drop derived attributions; raw and corrections untouched
```

Every command takes `--json`, writes results to stdout and diagnostics to stderr, and
exits non-zero on failure. `--store PATH` points at a different store.

## Where things live

| What | Path |
|------|------|
| Store | `%LOCALAPPDATA%\iknowwhatyoudid\store.db` (Windows) |
| | `~/Library/Application Support/iknowwhatyoudid/store.db` (macOS) |
| | `$XDG_DATA_HOME/iknowwhatyoudid/store.db`, else `~/.local/share/…` (Linux) |
| Log | beside the store |

The store is created on first use, owner-only, with no setup step.

## A few things worth knowing

**Nothing is deleted on the tool's own initiative.** A record that disappears from its
source is marked withdrawn and dated, not removed — it may be the evidence behind a
timesheet you already submitted. A store that fails an integrity check is reported with a
recovery step and left exactly as it is.

**Corrections are the only irreplaceable data.** No source can supply them again, so they
are keyed by the source's own identifiers rather than internal row ids, which is what lets
them survive deleting the store and re-ingesting from scratch. Import merges newest-wins
by when the correction was made, and names every replacement — nothing changes silently.

**Protection at rest is the operating system's job.** There is no passphrase, so commands
stay runnable unattended. `store protection` reports what it can actually verify, and says
`UNVERIFIED` rather than implying protection it has not confirmed — on Windows that is the
normal answer, because reading BitLocker status needs administrator rights.

## Development

This project follows Spec-Driven Development. Requirements and feature specifications live
under [`specs/`](specs/); project-wide principles and constraints live in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md).

```bash
uv run pytest          # must be green
uv run mypy src tests  # must be clean
```

Install `specify`:

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```

Then use the following loop to create a new feature:

```
/speckit-specify <new feature in natural langauge>   # describe a new feature
/speckit-clarify                                     # optional, let the AI ask clarifying questions
/speckit.plan                                        # plan the implementation
/speckit-tasks                                       # optional, mostly to break down the plan in smaller chunks
/speckit-implement                                   # actually implement the feature
```