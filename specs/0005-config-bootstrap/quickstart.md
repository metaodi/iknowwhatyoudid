# Quickstart: validating `init` and `edit`

How to prove this feature works. Every scenario runs against a temporary configuration
directory — **no test writes to the real one**, which is itself one of the scenarios.

No test spawns a real editor. The launcher is substituted and what *would* have been run is
asserted, which is how every case in [research R2](./research.md) becomes testable at all.

## Prerequisites

```bash
uv sync
uv run mypy src tests      # must be clean
uv run pytest              # must be green
```

---

## Scenario 1 — nothing the user wrote is ever changed (US2, FR-001, FR-002, SC-002)

**The guarantee the requirement amendment rests on**, and the first thing to test.

```bash
uv run pytest tests/integration/test_init.py -k "existing or overwrite" -v
```

Write all three files with known content — including a `credentials.toml` holding a
recognisable value — hash them, run `init`, hash again. Byte-identical, every time.

Then assert the negative directly: **no flag, option or environment variable overwrites**.
Walk the argument parser for the `init` command and assert nothing resembling `--force`,
`--overwrite` or `--replace` exists (FR-009). This is the assertion that stops the narrowing
in [contracts/amendments.md](./contracts/amendments.md) quietly becoming a relaxation.

## Scenario 2 — the whole-surface test, extended (FR-004)

```bash
uv run pytest tests/integration/test_sources_cli.py -k "ever_changed" -v
```

`0002`'s `test_no_command_ever_writes_the_configuration_file` **stays** and grows to cover
`init`, `sources edit` and `projects edit`, and to cover `projects.toml` and
`credentials.toml` as well as `config.toml`.

The renamed version asserts the property that actually matters: *nothing the user wrote is
ever changed*. It is the same test doing a better-stated job, not a weaker one.

## Scenario 3 — a fresh configuration works (US1, FR-005 to FR-013, SC-001, SC-005)

```bash
uv run pytest tests/integration/test_init.py \n  -k "appear or outside_it or shipped_templates or freshly or finds_them" -v
```

| Assertion | Requirement |
|---|---|
| All three files appear in an empty directory | FR-005 |
| The directory is created if absent, and nothing outside it is touched | FR-007 |
| They are exactly the shipped templates | FR-013 |
| `sources validate` then passes with **zero errors** | SC-005 |
| `projects validate` passes | SC-005 |
| The tool finds them without being told where they are | FR-006 |

The validation step is the one that matters. `0004` shipped an `examples/config.toml` with
uncommented mail sources that could not validate, and it was caught by running the quickstart
by hand rather than by any test. `init` makes these files the first thing a new user sees.

## Scenario 4 — the credentials file (FR-014 to FR-017, SC-005a, SC-005b)

```bash
uv run pytest tests/integration/test_init.py -k "credential or permissions_are_applied" -v
uv run pytest tests/integration/test_edit.py -k credentials -v
```

| Assertion | Why |
|---|---|
| Created readable by its owner and nobody else, asked of the operating system | SC-005a — not trusted from the write |
| Permissions are in place **before** content is written | FR-015. Asserted by observing the order, not the end state: the end state is identical either way, and the window is the whole point |
| An existing one is byte-identical after `init` | FR-016 — the highest-stakes case of Scenario 1 |
| Nothing is prompted for, generated, or written as a value | FR-017, SC-005b |
| No command exists that opens it in an editor | FR-027, SC-007a |

## Scenario 5 — per-file outcomes (FR-010 to FR-012, SC-003)

```bash
uv run pytest tests/integration/test_init.py   -k "reported or json_form or two_absent or twice or what_to_do_next" -v
```

Every combination of present and absent across three files, verifying that each is decided
independently:

| Present before | Expected |
|---|---|
| none | 3 created |
| `config.toml` only | 2 created, 1 left alone |
| all three | 0 created, 3 left alone, **nothing written**, exit `0` |

Running `init` twice must produce no change on the second run and no error — a non-zero exit
there would break `ikwyd init && ikwyd sources validate`.

## Scenario 6 — the editor command is resolved correctly (US3, FR-020, FR-021)

```bash
uv run pytest tests/unit/test_editor_command.py -v
```

A pure function, so every case is a test that spawns nothing. The table from
[research R2](./research.md), each row an assertion:

| `$EDITOR` | Expected |
|---|---|
| `notepad` | `['notepad']` |
| `code --wait` | `['code', '--wait']` |
| `C:\Program Files\…\code.exe` (exists, no args) | one argument, **path intact** |
| `"C:\Program Files\…\npp.exe" -multiInst` | two arguments, quotes stripped |
| `vim` | `['vim']` |
| unset, with `$VISUAL` set | `$VISUAL` wins |
| both unset | the platform opener |
| set to something that does not exist | reported **by name** — the user set it, so they can fix it |

Plus the two that are about safety rather than parsing:

- the file path is **the last argument**, always appended, never interpolated;
- `shell=False`, asserted through the AST — a path containing `&` or `;` must be an
  argument, not a command.

## Scenario 7 — `edit` opens the right file and changes nothing (US3, SC-007, SC-008)

```bash
uv run pytest tests/integration/test_edit.py -v
```

With the launcher substituted:

| Assertion | Requirement |
|---|---|
| `sources edit` hands over the configuration path | FR-019 |
| `projects edit` hands over the mapping path | FR-019 |
| `--config` and `--projects` are honoured | FR-006 |
| The file is byte-identical afterwards | SC-008 |
| Its contents are never read — a file of invalid TOML still opens | FR-024 |
| Nothing happens after the editor closes | FR-025 |
| A missing file is **not created**, and `init` is named | FR-022 |
| No editor at all: the path is printed and it says so plainly | FR-023 |

The invalid-TOML case is the one worth writing down: a configuration too broken to parse is
exactly the one you most need to open.

## Scenario 8 — the boundary, with a third door (research R4)

```bash
uv run pytest tests/integration/test_mail_boundaries.py -v
```

`cli/editor.py` joins `git/binary.py` and `protection/encryption.py` as a module permitted to
spawn a process, and the reason is recorded beside the other two.

Its lock is a **different shape**, and the test says so: an editor is chosen by the user, so
there is no allow-list of commands to keep. What is asserted instead is that the tool never
*constructs* a command — `shell=False`, path always last, nothing read from the file.

## Scenario 9 — the templates ship (FR-013, research R1)

```bash
uv run pytest tests/unit/test_templates.py -v
```

| Assertion | Why |
|---|---|
| All three are readable through `importlib.resources` | The path users get |
| Each parses as TOML | The cheapest thing to break while editing a comment |
| Each holds placeholders only, and no real address, path or token | The constitution, and this repository is public |
| Every `[[source]]` in the config template is commented out | Otherwise a fresh `sources validate` fails on day one |
| `examples/` holds no copy of any template | One source of truth (research R1) |

And the packaging assertion that would have caught the original bug: **build a wheel and
assert the templates are in it.** Marked `slow`; it is the only test here that runs a build.

## Scenario 10 — nothing else is disturbed (FR-028 to FR-031, SC-010, SC-011)

```bash
uv run pytest tests/integration/test_init.py -k "offline or isolation" -v
```

Run every command in this feature with sockets forbidden and the store path pointed at a
file that does not exist. All succeed. This feature opens no database and contacts nothing.

Then the isolation check `0004` established: snapshot the **real** configuration and data
directories, run everything against a temporary one, assert nothing in the real ones changed.

---

## Every success criterion, and the test that asserts it

Filled in after running the scenarios above by hand (T047). No criterion is left resting on
prose.

| SC | Asserted by |
|---|---|
| SC-001 — installed tool to validating configuration in one command | `test_init.py::test_a_freshly_created_configuration_validates` |
| SC-002 — every existing file byte-identical | `test_init.py::test_existing_files_are_byte_identical_afterwards`, `test_sources_cli.py::test_nothing_the_user_wrote_is_ever_changed` |
| SC-003 — a second run changes nothing and exits `0` | `test_init.py::test_running_it_twice_changes_nothing_the_second_time` |
| SC-004 — 0 options that would overwrite | `test_init.py::test_no_option_exists_that_would_overwrite` |
| SC-005 — a fresh configuration validates with zero errors | `test_init.py::test_a_freshly_created_configuration_validates`, `::test_a_freshly_created_mapping_validates` |
| SC-005a — credentials readable by its owner alone | `test_init.py::test_the_credentials_file_is_readable_by_its_owner_alone`, `::test_permissions_are_applied_before_any_content` |
| SC-005b — 0 credential values written, prompted for or generated | `test_init.py::test_nothing_resembling_a_credential_is_written`, `test_templates.py::test_the_credentials_template_holds_no_value_resembling_a_secret` |
| SC-006 — everything needing attention is a recognisable placeholder | `test_templates.py::test_every_template_uses_obvious_placeholders` |
| SC-007 — both edit commands open the correct file | `test_edit.py::test_sources_edit_hands_over_the_configuration_path`, `::test_projects_edit_hands_over_the_mapping_path` |
| SC-007a — 0 commands open the credentials file | `test_edit.py::test_no_command_opens_the_credentials_file`, `::test_the_editable_files_are_exactly_the_two` |
| SC-008 — a file opened for editing is byte-identical afterwards | `test_edit.py::test_the_file_is_byte_identical_afterwards` |
| SC-009 — every failure names the path and what to do, and leaves no partial file | `test_init.py::test_a_failed_write_leaves_no_file_at_all`, `::test_a_failed_write_says_which_file_and_why`, `::test_a_directory_that_cannot_be_created_is_reported`, `test_edit.py::test_a_missing_file_is_not_created_and_init_is_named`, `::test_no_editor_at_all_prints_the_path_and_says_so` |
| SC-010 — 0 network connections | `test_init.py::test_offline_and_without_a_store` |
| SC-011 — 0 commands read or write the store | `test_init.py::test_offline_and_without_a_store` |
| SC-012 — the setup command completes in under a second | `test_init.py::test_init_completes_in_well_under_a_second` |

**SC-009 changed the code.** Writing its test found that a failed write left the empty file
behind, which a later `init` would have reported as "left alone" forever. `config/bootstrap.py`
now removes what it started — safe, because an existing file returns before the file is
touched, so the only file it can ever delete is the one that call just made.

## Known limits at the end of this feature

1. **`edit` does nothing after the editor closes.** Validating automatically only works when
   the editor blocks, so a graphical editor returning immediately would report on a file you
   had not finished writing. `ikwyd sources validate` is one command away.
2. **A Windows `$EDITOR` combining a spaced path with arguments must be quoted.** No parser
   can infer it, and both `shlex` modes get the unquoted form wrong in different ways.
3. **There is no way to open `credentials.toml` from the tool.** Deliberate; `init` prints
   the path.
4. **`init` does not create the store.** It is created by the commands that use it and needs
   no template.
