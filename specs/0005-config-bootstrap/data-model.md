# Data Model: Getting Configured — `init` and `edit`

Phase 1 for [plan.md](./plan.md). **No schema change, no migration, no store access.** This
feature does not open the database at all.

What it has instead are three files on disk, one decision per file, and a rule about the
order things happen in.

---

## The three files

| File | Template | Holds secrets? | Created by | Openable by `edit`? |
|---|---|---|---|---|
| `config.toml` | `templates/config.toml` | no | `init` | **yes** — `sources edit` |
| `projects.toml` | `templates/projects.toml` | no | `init` | **yes** — `projects edit` |
| `credentials.toml` | `templates/credentials.toml` | **will**, once edited | `init` | **no**, deliberately (FR-027) |

Locations are `0002`'s and `0003`'s, unchanged: `config.toml` in the platform's
configuration directory, the other two beside it. `--config` moves all three together, so a
second configuration can be set up without disturbing the first.

**`credentials.toml` is not openable.** Handing a file of secrets to whatever `$EDITOR`
happens to name is a risk with no matching benefit; `init` prints the path.

---

## One decision per file

`init` makes the same decision three times, independently:

```text
         file exists?
        /            \
      yes             no
       |               |
   LEFT_ALONE      create empty
   (nothing            |
    written)      restrict to owner
                       |
                  write template
                       |
                    CREATED
```

| Outcome | Meaning | Exit code contribution |
|---|---|---|
| `CREATED` | The file did not exist and now does | success |
| `LEFT_ALONE` | It was already there; **nothing was written** | success |
| `FAILED` | The directory could not be made, or the write failed | failure, named by path |

**`LEFT_ALONE` is a success, not a warning.** Running `init` twice is the normal consequence
of not remembering whether you ran it, and a non-zero exit there would break
`ikwyd init && ikwyd sources validate` ([research R6](./research.md)).

**Files are independent.** One existing and two missing creates two files and leaves one —
there is no all-or-nothing. A partial result that is reported leaves the user further
forward than a rollback that does not.

---

## The order that matters

Every file, including the two that hold nothing sensitive:

1. `mkdir` the configuration directory if absent
2. create the file **empty**
3. **restrict it to the owner**
4. write the template

Steps 2–4 are not reordered, and step 3 is not special-cased to `credentials.toml`. The
obvious implementation — write, then fix the permissions — leaves an instant in which a file
intended to hold secrets is readable by anyone on the machine. Applying the same order to
all three means the sensitive case cannot be the one somebody forgets.

`protection/permissions.restrict_to_owner` already does step 3, including the Windows SDDL
path `0001` had to correct twice.

---

## The editor command

Resolved by a **pure function** returning a list of arguments, so every case is a unit test
that spawns nothing ([research R2](./research.md)).

| Source | Tried | Notes |
|---|---|---|
| `$VISUAL` | first | The convention for a full-screen editor |
| `$EDITOR` | second | The older, more widely set variable |
| platform opener | third | `os.startfile` on Windows — **no subprocess**; `open` on macOS; `xdg-open` on Linux |
| nothing found | — | Report it and print the path (FR-023). Never silently do nothing. |

Parsing a `$VISUAL`/`$EDITOR` value, in order:

1. **If the whole value names an existing file**, use it as a single argument. Rescues
   `C:\Program Files\Microsoft VS Code\code.exe`, which both `shlex` modes mangle.
2. Otherwise `shlex.split(value, posix=True)`.
3. A path containing spaces **and** arguments must be quoted — documented, because it is the
   one case nothing can infer.

The file path is **appended last**, never interpolated, and `shell=False` always. The tool
does not construct a command line; it runs the one the user already wrote, with one path on
the end.

---

## Where templates come from

`src/iknowwhatyoudid/templates/`, read with `importlib.resources`.

**Verified**: `examples/` is not in the wheel, and files inside the package directory are
([research R1](./research.md)). Reading from the repository would have worked for everyone
who cloned it and failed for everyone who installed it.

`examples/` keeps a README pointing at `ikwyd init` — the instruction it used to hold is the
one this feature exists to delete.

---

## What is deliberately absent

| Absent | Why |
|---|---|
| A `--force` flag | FR-009. The one way this tool could destroy a configuration. |
| A backup-then-overwrite path | Same. A backup is still a rewrite, and the user did not ask for one. |
| Any read of a file's contents | FR-024. `edit` checks a file exists and hands over its path — which is why a file too broken to parse is exactly the one you can still open. |
| Validation after editing | FR-025. It only works when the editor blocks; a graphical editor returning immediately would report on an unfinished file. |
| Any store access | FR-029. This feature never opens the database. |
| Any credential value | FR-017. Nothing is prompted for, generated, or written — the permissions guard a file that will *become* sensitive when the user edits it. |
