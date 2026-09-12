# Research: Getting Configured — `init` and `edit`

Phase 0 for [plan.md](./plan.md). Every decision below was verified on this machine; where
a claim could not be settled it says so.

Three findings shape the design, and the first would have made the feature silently broken
for anyone who installed the tool rather than cloning it.

---

## R1. `examples/` does not ship in the wheel

**Verified**, by building one:

```text
$ uv build --wheel
$ unzip -l iknowwhatyoudid-0.1.0-py3-none-any.whl
  examples/ present: False
  non-.py files shipped: ['iknowwhatyoudid/py.typed']
```

`pyproject.toml` says `packages = ["src/iknowwhatyoudid"]`, so the wheel contains that
directory and nothing else. **`ikwyd init` installed with `uv tool install` would have
nothing to copy from.** The feature would work perfectly in a git checkout and fail for
every real user — the worst shape a bug can take, because the people who wrote it never see
it.

The same build proves the fix: `py.typed` *is* shipped, so hatchling includes non-Python
files that live inside the package directory. Confirmed directly:

```text
templates in wheel: ['iknowwhatyoudid/templates/config.toml']
importlib.resources reads it: True
```

**Decision**: the three template files **move** from `examples/` to
**`src/iknowwhatyoudid/templates/`**, and are read with `importlib.resources`. They are not
duplicated — there is one copy before the move and one copy after. `examples/` is left
holding a short README pointing at `ikwyd init`.

**Rationale**: one file, one location, no fallback branch, and nothing to drift. The
specification's assumption — "templates are the files already shipped in `examples/`, not a
second copy maintained separately" — is honoured by *moving* rather than copying. And the
feature makes `examples/` redundant as a user-facing thing anyway: the README currently
tells people to `cp examples/config.toml "$APPDATA/..."`, which is precisely the instruction
`init` exists to delete.

**Alternatives considered**:

- **Keep `examples/` canonical and `force-include` it into the wheel.** Works, and keeps the
  path the README already names. Rejected: the loader then needs two lookup paths — packaged
  resource, else repository directory — and the repository branch is the one that would be
  exercised by every test while the packaged branch is the one users get. A fallback whose
  failing side is untested is not a fallback.
- **Generate the templates from string constants in code.** No files to ship at all.
  Rejected: the examples are currently validated by the existing suite as real files, and a
  heredoc in a Python module is harder to read and to review than a `.toml`.
- **Ship a source distribution and read from it.** Does not help; `uv tool install` builds a
  wheel.

---

## R2. Neither `shlex` mode parses a Windows editor command correctly

**Verified**, both modes, on Windows:

| `$EDITOR` value | `posix=True` | `posix=False` |
|---|---|---|
| `notepad` | `['notepad']` | `['notepad']` |
| `code --wait` | `['code', '--wait']` | `['code', '--wait']` |
| `C:\Program Files\…\code.exe --wait` | `['C:Program', 'FilesMicrosoft', …]` ❌ | `['C:\Program', 'Files\Microsoft', …]` ❌ |
| `"C:\Program Files\…\notepad++.exe" -multiInst` | `['C:\Program Files\…', '-multiInst']` ✅ | `['"C:\Program Files\…"', '-multiInst']` ❌ |

`posix=True` **eats the backslashes** — `C:\Program Files` becomes `C:Program`,
`FilesMicrosoft` — and destroys the path. `posix=False` **keeps the quote characters**, so
the executable name literally contains `"` and cannot be found. An unquoted path containing
spaces is broken under both.

**Decision**, in order:

1. If the whole value, untouched, names an existing file, use it as a **single argument**.
   This handles `C:\Program Files\Microsoft VS Code\code.exe` with no quoting at all, which
   is how people actually set `$EDITOR` on Windows.
2. Otherwise `shlex.split(value, posix=True)`, which is correct for every Unix case and for
   the quoted Windows case.
3. Document that a path containing spaces **and** arguments must be quoted.

**Rationale**: step 1 costs one `os.path.isfile` and rescues the case both parsers get
wrong. Steps 2 and 3 then behave exactly as every other tool that reads `$EDITOR` does, so
a user's existing setting keeps working.

**Alternatives considered**:

- **`posix=True` only**, documenting that Windows users must quote. Simpler, and silently
  mangles a setting that works everywhere else. Rejected: the failure is a garbled
  executable name, which reads like the tool is broken rather than like the value needs
  quoting.
- **Platform-dependent parsing.** Rejected: two code paths, and the same `$EDITOR` would
  then mean different things on different machines.

---

## R3. The Windows fallback needs no subprocess at all

**Verified**: `os.startfile` exists on this platform. It calls `ShellExecute` directly and
**does not spawn a process through `subprocess`**.

| Platform | Fallback | Spawns a process? |
|---|---|---|
| Windows | `os.startfile(path)` | **No** |
| macOS | `open <path>` | Yes |
| Linux | `xdg-open <path>` | Yes |

**Decision**: use `os.startfile` where it exists; otherwise `open` or `xdg-open`, whichever
is present, and report honestly when neither is.

**Consequence for the process boundary** (R4): on Windows the default-application path is
reachable without touching `subprocess` at all, so the only reason this feature needs a
process is a user-configured editor.

---

## R4. The editor is a third door, and its lock is a different shape

`0003` established that `git/binary.py` is the only module that may invoke git, guarded by
an **allow-list of subcommands**. `0004` kept that and added `protection/encryption.py` as a
second permitted caller. A test asserts nothing else imports `subprocess`.

**An editor cannot be allow-listed**, and pretending otherwise would be theatre. The command
is chosen by the user, in their own environment; the tool has no basis for approving `vim`
and refusing `hx`.

**Decision**: `cli/editor.py` becomes the third and only other module permitted to spawn a
process, and its invariant is stated in terms of what the tool *constructs* rather than what
it permits:

| Invariant | Why |
|---|---|
| `shell=False`, always | With a shell, a path containing `&` or `;` becomes a command. Without one, an argument is an argument. |
| The file path is the **last** argument, appended, never interpolated | A path is never spliced into a string, so it cannot become a flag or a second command. |
| Nothing is read from the file to decide how to open it | FR-024. The tool hands over a path; it does not parse what is there. |
| The command comes from the environment, unmodified | The user chose it. Editing it would be guessing. |

**Rationale**: the honest statement is "we never build a command line, we run the one the
user already wrote, with one path appended". That is checkable — no `shell=True` anywhere,
path always last — and it is a different guarantee from git's, so it is worth writing down
rather than filing under the same rule.

The boundary test gains a third permitted module with this reason recorded beside it, in the
same place the other two are.

---

## R5. Permissions before content, again

`0004` established the pattern for `tokens.toml`: create the file empty, restrict it to the
owner, **then** write. `protection/permissions.restrict_to_owner` already exists and is
tested, including the Windows SDDL path that `0001` had to correct twice.

**Decision**: `credentials.toml` is created the same way, and FR-015 requires it.

**Rationale**: the obvious implementation — write the file, then fix the permissions — leaves
an instant in which a file intended to hold secrets is readable by anyone on the machine.
The window is short and the consequence is not.

**Note on what is written**: the template contains `token = "REPLACE-with-your-token"`, a
placeholder. The tool never prompts for, generates, or writes a credential value (FR-017),
so nothing sensitive exists at any point in this feature — the permissions guard a file that
will *become* sensitive when the user edits it.

---

## R6. What `init` reports, and why it cannot be a boolean

Three files, each independently either created or already present. A command that answers
"did it work?" with one bit would have to choose between calling a no-op run a failure and
calling a partial run a success.

**Decision**: report per file — `created`, or `left alone` with its path — and exit zero
whenever nothing went wrong, including when there was nothing to do (FR-012).

**Rationale**: running `init` twice is not an error, it is the normal consequence of not
remembering whether you ran it. A non-zero exit there would break the obvious
`ikwyd init && ikwyd sources validate`.

---

## R7. What this feature deliberately does not touch

| Not done | Why |
|---|---|
| Creating the store | It is created by the commands that use it, and needs no template |
| Opening `credentials.toml` in an editor | FR-027 — handing a file of secrets to whatever `$EDITOR` names is a risk with no matching benefit |
| Validating after an editor closes | Only works when the editor blocks; a graphical editor returning immediately would report on an unfinished file |
| An `--force` flag | FR-009 — the one way this tool could destroy a configuration |
| Migrating or reformatting an existing file | The requirement this feature narrows exists precisely to forbid it |
