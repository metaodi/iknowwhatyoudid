# Contract: CLI commands

Extends [`0001`](../../0001-local-store-foundation/contracts/cli-commands.md) and the three
features after it. Every command offers `--json`, writes diagnostics to stderr, and exits
non-zero on failure.

## New: `ikwyd init`

Puts the three files a user edits where the tool looks for them.

```text
$ ikwyd init
Configuration directory: C:\Users\ods\AppData\Roaming\iknowwhatyoudid

  created     config.toml       declare the sources to read from
  created     projects.toml     map repositories and correspondents to projects
  created     credentials.toml  secrets go here, and nowhere else (readable by you alone)

3 created, 0 left alone.

Next: edit the files, then run `ikwyd sources validate`.
  ikwyd sources edit
  ikwyd projects edit
```

Run again, with everything in place:

```text
$ ikwyd init
Configuration directory: C:\Users\ods\AppData\Roaming\iknowwhatyoudid

  left alone  config.toml
  left alone  projects.toml
  left alone  credentials.toml

0 created, 3 left alone. Nothing was written.
```

| | |
|---|---|
| **Creates** | `config.toml`, `projects.toml`, `credentials.toml`, from the shipped templates |
| **Never** | overwrites, truncates, renames, or backs up an existing file |
| **Options** | `--config PATH` to place them elsewhere; `--json` |
| **No option exists** | that would overwrite. Not `--force`, not an environment variable (FR-009) |
| **Exit** | `0` whenever nothing went wrong, **including when there was nothing to do** |

**Per-file outcomes, not one verdict.** Three files each independently created or already
present; a single boolean would have to call either a no-op run or a partial run a failure.
Running `init` twice is the normal consequence of not remembering whether you ran it, and
`ikwyd init && ikwyd sources validate` must work.

**`credentials.toml` is created readable by its owner alone**, and the permissions are in
place **before** any content is written — there is no instant at which a file intended to
hold secrets is readable by anyone else. Nothing sensitive is written: the template holds
placeholders, and the tool never prompts for, generates, or writes a credential value.

### JSON

```json
{
  "command": "init",
  "ok": true,
  "data": {
    "directory": "C:\\Users\\ods\\AppData\\Roaming\\iknowwhatyoudid",
    "files": [
      {"name": "config.toml", "path": "…", "outcome": "created"},
      {"name": "projects.toml", "path": "…", "outcome": "left_alone"},
      {"name": "credentials.toml", "path": "…", "outcome": "created", "owner_only": true}
    ],
    "created": 2,
    "left_alone": 1
  }
}
```

No credential value appears in any form, because none exists.

---

## New: `ikwyd sources edit` · `ikwyd projects edit`

Opens the file in the editor the user already uses.

```text
$ ikwyd sources edit
Opening C:\Users\ods\AppData\Roaming\iknowwhatyoudid\config.toml with $EDITOR (code --wait).
```

When the file is not there:

```text
$ ikwyd projects edit
C:\Users\ods\AppData\Roaming\iknowwhatyoudid\projects.toml does not exist.
  → Run `ikwyd init` to create it. This command opens files; it does not create them.
```

When nothing can open it:

```text
$ ikwyd sources edit
No editor found: neither $VISUAL nor $EDITOR is set, and no default application is
available for this file.
  → Set $EDITOR, or open it yourself:
    C:\Users\ods\AppData\Roaming\iknowwhatyoudid\config.toml
```

| | |
|---|---|
| **Editor** | `$VISUAL`, then `$EDITOR`, then the platform's default application |
| **Never** | creates the file, reads its contents, or changes it |
| **After the editor closes** | nothing. No validation, no ingestion, no output not asked for |
| **Options** | `--config PATH`; `--projects PATH` for the mapping; `--json` |
| **There is no** | `credentials edit`. See below. |

**There is deliberately no command that opens `credentials.toml`.** Handing a file of
secrets to whatever `$EDITOR` happens to name is a risk with no matching benefit, and `init`
prints the path for anyone who wants it (FR-027).

**The file's contents are never read.** `edit` checks a file exists and hands over its path —
which is why a configuration too broken to parse is exactly the one you can still open.

**How an editor command is interpreted**: if the whole value names an existing file it is
used as a single argument; otherwise it is split as a shell would. A path containing spaces
**and** arguments must be quoted. Verified against both `shlex` modes on Windows, where
neither is correct on its own ([research R2](../research.md)).

**The path is always the last argument**, appended rather than interpolated, and no shell is
used. The tool does not construct a command line; it runs the one the user already wrote.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | The editor was launched (and, for a blocking editor, has closed) |
| `1` | The file does not exist, or no editor could be found |
| `2` | Usage |

An editor exiting non-zero is **reported but not treated as failure**: editors exit non-zero
for many reasons, and refusing to continue would be unhelpful.

---

## Changed: the interactive-command rule

`0004` recorded that `sources authorise` was *the only interactive command in the tool*.
After this feature there are three, and the claim is corrected rather than left to become
quietly false.

What matters is unchanged, and is now stated as a rule rather than a count:

> **No interactive command may be reachable from a command that reads a source.** `ingest`
> never opens a browser and never opens an editor, so a scheduled or scripted run can never
> block waiting for a person.

| Command | Interactive | Reachable from `ingest`? |
|---|---|---|
| `sources authorise` | opens a browser | **no** |
| `sources edit` | opens an editor | **no** |
| `projects edit` | opens an editor | **no** |
| everything else | no | — |

---

## Invariants every command in this feature upholds

| Invariant | Requirement |
|---|---|
| No existing file is modified, reformatted, reordered or rewritten | FR-001, FR-002 |
| No flag, option or environment variable overwrites | FR-009 |
| Nothing is written outside the configuration directory | FR-007 |
| No network destination is contacted | FR-028 |
| The store is never opened | FR-029 |
| No source — mail account, repository — is touched | FR-030 |
| No credential value is printed, logged, prompted for, or generated | FR-017, FR-031 |
| A failure names the path and leaves nothing partially written | SC-009 |
