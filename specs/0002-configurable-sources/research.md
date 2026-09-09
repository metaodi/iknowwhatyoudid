# Phase 0 Research: Configurable Sources

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-09-09

Each decision below was carried into [plan.md](./plan.md). Findings marked **verified** were checked by
running code on the target machine (Windows 11, `uv` 0.7.15, CPython 3.12.11 available via `uv`) rather
than recalled.

---

## D1. Configuration file format — TOML, not YAML

**Decision**: TOML, parsed with the standard library's `tomllib`.

**This overrides the format named in the feature description.** The user wrote "most probably a YAML
file, but open to other suggestions if there is a good reason for it". The reasons below are offered as
that good reason; the decision is easy to reverse and the spec deliberately depends on no format (see
`spec.md` Assumptions).

**Rationale**:

1. **Zero dependency.** `tomllib` has been in the standard library since 3.11. YAML needs `PyYAML` or
   `ruamel.yaml`. The constitution makes the standard library the default and requires every third-party
   dependency to be justified here — and "the file looks nicer" does not clear that bar when the
   alternative is equally readable.
2. **`tomllib` is read-only by construction**, which is exactly FR-002: the tool must never rewrite or
   reformat the user's file. With a YAML library the write path exists and someone eventually uses it.
   Here it is not reachable.
3. **Parse errors carry a position.** Verified: `tomllib.loads('[[source]]\nname = "a"\nkind = \n')`
   raises `TOMLDecodeError: Invalid value (at line 3, column 8)`, satisfying FR-004's "report the failure
   with the location in the file".
4. **Native datetimes.** Verified: `since = 2026-01-01T00:00:00Z` parses directly to a timezone-aware
   `datetime.datetime`. FR-038's earliest-point-to-read-from needs exactly this, and in YAML it would
   arrive as a string needing hand-parsing, or as a naive datetime.
5. **YAML's implicit typing is an active hazard for this specific data.** The configuration holds mail
   folder names, git identities, and calendar names — unquoted human strings. YAML 1.1, which PyYAML
   implements, converts `no`, `off`, `y`, and `on` to booleans, and strings like `19:30` to sexagesimal
   integers. A folder literally named `No Reply` or an identity list containing `y` would silently change
   type. TOML has no implicit typing: a bare word is an error, not a coercion.
6. **The shape fits.** Verified against a realistic sample: `[[source]]` array-of-tables gives one block
   per source, dotted keys (`folders.include = [...]`) give nested per-kind settings without indentation,
   and comments are supported. Nothing in the intended configuration needs YAML's anchors or multi-line
   scalars.

**Alternatives considered**:

- **YAML (PyYAML)** — the user's initial preference and the most familiar format. Rejected on the
  dependency rule plus the implicit-typing hazard above. If it is ever adopted, `yaml.safe_load` would be
  mandatory (`yaml.load` executes arbitrary constructors), which is a footgun TOML does not have.
- **YAML (ruamel.yaml)** — better spec compliance (YAML 1.2, so no Norway problem) and round-trip
  comment preservation. Rejected: a heavier dependency, and its main advantage — writing the file back
  with comments intact — is a capability FR-002 forbids using.
- **JSON** — stdlib, unambiguous. Rejected: no comments, and a configuration people are expected to hand-
  edit and annotate needs them. Trailing-comma errors are also a poor experience.
- **INI via `configparser`** — stdlib. Rejected: everything is a string, no lists, no nesting, no typed
  datetimes. Every setting would need hand-parsing and hand-validating.

**Consequences**: FR-035 to FR-037's settings are expressed as dotted keys within each `[[source]]`
block. The full grammar is in [contracts/config-file.md](./contracts/config-file.md).

---

## D2. Locating semantic errors in the file — key paths, with best-effort line numbers

**Decision**: Every finding carries a structured key path (`source[1].folders.include`). A best-effort
pass over the raw file text additionally attaches a line number where one can be found unambiguously.
Where it cannot, the finding is emitted with the key path alone.

**Rationale**: FR-016 requires each problem located "by source name and by setting", which the key path
satisfies exactly. But User Story 1 scenario 3 also says "where in the file it is", which reads as a line.
`tomllib` discards position information for successfully parsed values — it returns plain dicts — so a
line number is not available from the parser for semantic (as opposed to syntax) errors. Rather than
re-implement a TOML parser to keep positions, or add a dependency that does, the loader keeps the raw
text and searches it for the relevant key within the relevant `[[source]]` block. This succeeds for the
ordinary case of a key written once on its own line and degrades to "no line number" for the awkward ones
(inline tables, multi-line arrays, a key repeated across blocks) rather than reporting a wrong line.

**Alternatives considered**:

- **`tomlkit`** — a style-preserving TOML library that retains positions. Rejected: a runtime dependency
  bought for a nicety, when the key path already satisfies the requirement.
- **Hand-rolled position-tracking parser** — rejected outright; re-implementing TOML to improve an error
  message is exactly the complexity the constitution's simplicity rule exists to prevent.
- **Line numbers only, no key paths** — rejected: `--json` consumers need something structured, and a
  line number is useless the moment the user edits the file.

**Consequences**: A `Finding` has an optional `line`. Tests assert on key paths, never on line numbers,
so the best-effort locator can never break the suite.

---

## D3. File permission check (FR-006) — platform-specific, and Windows needs SDDL

**Decision**: Two implementations behind one function. POSIX reads `stat.S_IMODE` and warns if the group
or other read bit is set. Windows reads the file's owner and DACL through `ctypes` calls to
`advapi32.GetNamedSecurityInfoW` and `ConvertSecurityDescriptorToStringSecurityDescriptorW`, then parses
the resulting SDDL string. If either check raises, the tool emits a *"could not verify permissions"*
warning — never a clean pass.

**Rationale**: **Verified — the naive approach is broken on the target platform.** On this Windows 11
machine, `os.stat("pyproject.toml").st_mode` returns `0o100666` — the permission bits are a fiction
Python synthesises, identical for every file regardless of its actual ACL — and `os.geteuid` does not
exist. A POSIX-style check would therefore report a genuinely private file as world-readable, or a
genuinely exposed one as safe, at random. FR-006 implemented that way would be worse than not
implementing it.

`icacls` was the obvious subprocess alternative and is **verified unusable for parsing**: on this machine
it returns principal names in German — `NT-AUTORITÄT\SYSTEM`, `VORDEFINIERT\Administratoren` — plus a
localised summary line. Any parser keyed on those names breaks on a differently localised Windows.

The SDDL route is **verified locale-independent**. On this machine both test files return:

```text
O:S-1-5-21-…-13577D:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;S-1-5-21-…-13577)
```

The owner SID appears in `O:`, and the DACL grants full access to `SY` (Local System), `BA` (Builtin
Administrators), and the owner — all expressed as SID abbreviations or raw SIDs, never as translated
names. The check is then simply: warn if any ACE grants read to a principal that is not the owner and not
in the accepted set `{SY, BA}`. Principals such as `WD` (Everyone), `BU` (Builtin Users), or another
user's SID are what the warning is for.

**Alternatives considered**:

- **`pywin32` (`win32security`)** — the conventional answer, and cleaner code. Rejected: a large
  dependency, on one platform, for one warning. `ctypes` reaches the same two Win32 calls with no
  dependency at all.
- **Parsing `icacls`** — rejected on the verified localisation problem above.
- **Skipping the check on Windows** — rejected. Windows is the primary target platform; silently having
  no check there would make FR-006 a requirement that passes its tests on CI and does nothing for the
  actual user.
- **Reporting "safe" when the check fails** — rejected on the spec's stated bias toward reporting a gap
  rather than assuming it away.

**Consequences**: none for this feature. `0001` shipped this check as `protection/permissions.py`,
including two cases this analysis did not anticipate — ACEs whose rights are a numeric mask
(`0x1200a9`), and the `OW`/`CO` owner trustees, which a naive check reports as third parties. This
feature calls it rather than reimplementing it.

---

## D4. Source-kind declarations — explicit `SettingSpec` values, not a validation library

**Decision**: Each source kind declares its settings as an explicit, immutable sequence of `SettingSpec`
dataclasses — name, type, required, default, help text, and whether the value is a path, an identity, or
a credential reference. Validation walks that sequence.

**Rationale**: FR-028 requires listing "the available source kinds and each kind's accepted settings" to
the user, and FR-032 requires the declaration to be complete enough that a kind supplied from outside the
project would need nothing further. Both requirements need the declaration to be *enumerable and
printable*, not merely *enforceable*. An explicit data structure is the direct expression of that; a
validation library is a way of enforcing constraints from which a description must then be reverse-
engineered. It is also trivially serialisable for the `--json` form of `sources kinds`.

**Alternatives considered**:

- **Pydantic** — the default reflex, and genuinely good at validation. Rejected on three grounds: it is a
  substantial runtime dependency in a project whose constitution defaults to the standard library; its
  JSON Schema export describes types well but carries the semantic tags (this string is a path, this one
  is a credential reference) awkwardly; and its error messages are shaped for developers, whereas FR-016
  and FR-017 want findings shaped for the person editing the file.
- **`dataclasses` + `typing.get_type_hints` introspection** — zero dependency, less code to write.
  Rejected: type hints alone cannot express "required", "this is a credential reference", or help text
  without a parallel annotation scheme, which is a `SettingSpec` with extra indirection.
- **JSON Schema** — a genuine standard and externally consumable. Rejected: needs a validator dependency,
  and its error reporting locates faults by JSON Pointer, which is further from the user's TOML file than
  the key paths of D2.

**Consequences**: Roughly 150 lines in `kinds/spec.py`. Adding a kind means adding a declaration and a
reader, which is the shape a future `0003`/`0004`/`0005` will slot into.

---

## D5. Extension boundary — in-project registry, contract shaped as if public

**Decision**: `kinds/registry.py` holds an explicit mapping of kind name to declaration, populated by
direct import from within the package. No entry-point scanning, no plugin directory, no dynamic import of
anything outside `iknowwhatyoudid.kinds`.

**Rationale**: This is the user's answer to Q1 (option C). FR-031 forbids loading a kind from elsewhere;
FR-032 requires the declaration nonetheless be complete enough that an external kind would need nothing
further. An explicit dict satisfies FR-031 by construction — there is no code path that reads the
filesystem or the entry-point registry looking for kinds, so there is nothing to accidentally enable. The
`SourceKind` contract is documented in [contracts/source-kind.md](./contracts/source-kind.md) as though it
were public, so FR-031 can later be relaxed by adding a discovery mechanism, without any change to the
contract or to a user's configuration file.

**Alternatives considered**:

- **`importlib.metadata.entry_points()`** — the standard Python plugin mechanism, zero dependency.
  Rejected for now: any package installed in the same environment could register a source kind, and this
  process holds mail and calendar credentials. Enabling that is a trust decision the user deferred.
- **A plugin directory scanned at startup** — rejected for the same reason, with the added problem that
  a path is easier to write to than a package is to install.

**Consequences**: User Story 4 is tested by adding a fixture kind to the registry within the test, which
proves the same property the plugin mechanism would — that no existing kind and no existing configuration
file needs to change — without opening the loading path.

---

## D6. Credential resolution — presence-only, from a user-only-readable file

**Decision**: A `CredentialStore` that answers one question: is a named credential present? It reads a
separate secrets file, distinct from the configuration file, checked with the same permission logic as
D3. It does **not** return the value to any caller in this feature.

**Rationale**: This feature never authenticates to anything — the three real kinds are declarations only
(FR-033), and the fixture kind needs no credential. What it must do is FR-021: report which credential
each source needs and whether it is present, without revealing the value. Presence is the entire
requirement, and a store that cannot return a value cannot leak one. Choosing the OS keyring now would
mean designing an authorization flow for sources whose reading behaviour is not yet specified.

The keyring-versus-file question that `spec.md` defers to this plan is therefore answered as: **a file
now, because that is all this feature needs; the keyring decision belongs to `0004`**, the first feature
that performs a real OAuth flow and has an actual token to store. The `CredentialStore` boundary takes a
name and returns presence, so a keyring-backed implementation can replace the file-backed one behind it.

**Alternatives considered**:

- **`keyring` package now** — a runtime dependency, plus platform backends, for a capability this feature
  does not exercise. Rejected as premature; revisit in `0004`.
- **Environment variables** — zero code. Rejected: they leak into child processes and process listings,
  and there is no way to check permissions on one.
- **Storing credentials in the configuration file** — forbidden by FR-020 and the constitution.

**Consequences**: `sources check --live` (FR-018) is defined in the contract but has no kind that can
exercise it beyond the fixture kind's simulated check, which is the honest consequence of FR-033.

---

## D7. Redaction (FR-022) — one chokepoint, not a convention

**Decision**: A process-wide redaction registry holds values known to be secret. `cli/render.py` is the
only module that converts a payload into text, and it applies redaction there, for both human and `--json`
output.

**Rationale**: FR-022 and SC-007 require that no credential value appears in output, diagnostics, logs, or
the store — a property that must hold for every command written from now on, including ones nobody has
thought of. Enforced per call site it is a convention that decays. Enforced at the single point where data
becomes text it is structural. A logging filter applying the same registry covers the diagnostics path.

**Alternatives considered**:

- **Redact at each command** — rejected: correctness would depend on every future author remembering.
- **A secret-carrying wrapper type whose `__str__` and `__repr__` redact** — genuinely appealing, and
  strictly better where it applies. Rejected as the primary mechanism because it protects only values
  that stay inside the wrapper, and a secret read from a file arrives as a plain `str`. Worth adding
  later as defence in depth; the chokepoint is the load-bearing control.

**Consequences**: SC-007 is testable directly — a test plants known secret values, runs every command,
and searches all output streams, the log file, and the store for them.

---

## D8. Inline-secret detection (FR-023) — key-name patterns plus a shape check

**Decision**: Warn when a configuration value looks like a secret, using two signals together: the key
name matches a pattern (`password`, `token`, `secret`, `api_key`, `client_secret`, and similar), or the
value matches a recognisable credential shape (a PEM block header, a `ghp_`/`xox`-style prefixed token,
or a long high-entropy base64-ish run). Findings are warnings (FR-017), never blocking.

**Rationale**: FR-023 asks the tool to notice a mistake, not to prove one. Key-name matching catches the
overwhelmingly common case — someone writing `password = "hunter2"` where a credential reference belongs
— with near-zero false positives. The shape check catches a secret pasted under an innocuous key name.
Keeping these warnings rather than errors means a false positive can never stop a user working, which is
what makes a heuristic acceptable at all.

**Alternatives considered**:

- **Entropy threshold alone** — rejected: git commit hashes, SIDs, long file paths, and calendar IDs all
  score high, producing warnings on correct configurations.
- **A full secret-scanning ruleset (gitleaks-style)** — rejected: a large dependency or a large ruleset to
  maintain, for a hygiene warning on a file that by design holds no secrets.
- **Not implementing it** — rejected; it is FR-023 and the mistake it catches is the exact one that leaks
  a mail account.

---

## D9. CLI construction — `argparse` with subcommands

**Decision**: `argparse` with subparsers. Commands are library functions returning typed payloads;
`cli/main.py` maps a payload to an exit code and hands it to `cli/render.py`.

**Rationale**: Stdlib, and sufficient for six commands with few options. The structural point matters more
than the parser: because commands are functions returning data, the integration tests call them directly
and assert on structures, and only a thin layer of subprocess tests covers exit codes and stream routing.
That keeps the constitution's `--json`/exit-code/stdout-vs-stderr rules cheap to test exhaustively.

Exit codes: `0` success; `1` findings block or a source failed; `2` usage error. The full mapping is in
[contracts/cli-commands.md](./contracts/cli-commands.md).

**Alternatives considered**:

- **`click` / `typer`** — nicer ergonomics, better help output. Rejected: a runtime dependency, and
  `typer` pulls a further transitive tree. Neither earns its place at six commands.

---

## D10. Configuration file location

**Decision**: Windows `%APPDATA%\iknowwhatyoudid\config.toml`; macOS
`~/Library/Application Support/iknowwhatyoudid/config.toml`; Linux
`$XDG_CONFIG_HOME/iknowwhatyoudid/config.toml`, falling back to `~/.config/…`. Overridable per-invocation
with `--config PATH` (FR-003).

**Rationale**: FR-002 requires exactly one documented default, reported verbatim when the file is absent.
**Verified** on this machine: `APPDATA=C:\Users\ods\AppData\Roaming`, `LOCALAPPDATA` also set,
`XDG_CONFIG_HOME` unset — so the Windows branch uses `APPDATA` (roaming, which is right for
user-authored configuration) and the Linux branch needs the `~/.config` fallback rather than assuming
`XDG_CONFIG_HOME` is set.

Note this is the *configuration* location; the constitution puts the *store* in the tool's own data
directory, which is a different path and `0001`'s decision. Keeping user-authored configuration separate
from the derived store is what lets the store be deleted and rebuilt (Principle IV) without the user
losing what they wrote.

**Alternatives considered**:

- **`platformdirs`** — the standard answer for this. Rejected: a dependency for roughly 15 lines of
  branch logic. Verified that the environment variables needed are present.
- **A dotfile in `$HOME`** — rejected: inconsistent with the platform conventions the constitution's data
  directory rule already implies.
- **A file in the current working directory** — rejected: it makes behaviour depend on where the command
  is run, which is a poor property for a tool whose output feeds timesheets.

---

## D11. Development dependencies

**Decision**: `pytest` and `mypy`, both dev-only. Runtime dependencies stay empty.

**Rationale**: `mypy` is mandated outright by the constitution. `pytest` is justified by the requirement
that automated tests accompany every behavioural change: its fixture model is what makes the
per-user-story integration tests — each needing a temp config file, a temp secrets file, and a fresh
in-memory store — readable rather than a mass of `setUp` inheritance. `unittest` is the zero-dependency
alternative and was considered; it was rejected because parameterised cases (one per malformed-config
fixture) and composable fixtures are exactly what this test suite is made of, and `unittest` expresses
both poorly. Neither package ships to the user.

---

## Open items carried into implementation

None blocking. Two things are deliberately deferred and recorded so they are not rediscovered as
surprises:

1. **The store exists.** `0001-local-store-foundation` shipped `SqliteSourceStateStore` against
   [contracts/source-state.md](./contracts/source-state.md). Resumption points are durable and the
   in-memory implementation is now a test double. `0001` also added `RunMode` to the record contract,
   which this feature must thread through — see tasks T078 and T079.
2. **The keyring-versus-file credential decision is answered only for this feature** (D6). `0004` owns the
   real decision, and the `CredentialStore` boundary is where it lands.
