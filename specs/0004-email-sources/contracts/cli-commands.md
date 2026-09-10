# Contract: CLI commands

Extends [`0002`](../../0002-configurable-sources/contracts/cli-commands.md) and
[`0003`](../../0003-git-source-projects/contracts/cli-commands.md). Every command offers `--json`, writes
diagnostics to stderr, and exits non-zero on failure (Principle VI).

## New: `ikwyd sources authorise NAME`

Obtains the authorisation a mail account needs, once.

```text
$ ikwyd sources authorise work-mail
Opening your browser to sign in to Microsoft 365.
  Requesting: Mail.ReadBasic — read your mail, without message bodies or attachments.
  This grant cannot send, delete, move or mark anything as read.
Waiting for the redirect on http://127.0.0.1:53124/ …

Authorised. Token stored in %APPDATA%\iknowwhatyoudid\tokens.toml (user-only).
Run `ikwyd ingest` to read.
```

- **The only interactive command in the tool.** `ingest` never opens a browser: a scripted or scheduled run
  must never block waiting for one.
- **Not needed for `mail.hey`.** Sign in with `hey` itself; this tool never holds that credential. Running
  `authorise` on a Hey account says so and exits zero.
- `--no-browser` prints the URL instead of opening it, for use over SSH.
- Naming the scope in plain words before the browser opens is deliberate. The user is about to grant access
  to their mail; they should be told what is being asked for by the tool that asks, not only by the consent
  screen.
- Exit codes: `0` authorised · `2` usage · `3` the user declined · `4` the tenant requires an administrator.

## New: `ikwyd mail list [--from DATE] [--to DATE] [--account NAME] [--project NAME]`

Mail activity, filtered. Columns: `WHEN`, `ACCOUNT`, `PROJECT`, `TO`, `SUBJECT`.

`PROJECT` marks an ad-hoc attribution `(ad hoc)`, as every other view does (FR-041).

Every listing ends with the line **`sent mail only — received mail is not read`** (FR-049). A day with no
rows must be distinguishable from a day whose mail this tool does not look at.

## New: `ikwyd mail correspondents [--project NAME]`

Who contributes most to a project (FR-054).

```text
ADDRESS                  PROJECT                   MESSAGES  LAST
anna@acme.example        acme-migration                  84  2026-09-08
ops@acme.example         acme-migration                  31  2026-09-01
bob@northwind.example    northwind.example (ad hoc)      12  2026-08-22

3 correspondents · 1 unmapped domain
```

The unmapped count is the point of the command: it is how a missing mapping becomes discoverable rather
than something to guess at.

## Changed: `ikwyd sources validate`

Adds, for each mail account: whether `addresses` is present and well-formed, whether a credential is
referenced, and whether a token exists. **Contacts nothing** — `0002`'s rule that validation is offline and
fast is unchanged.

`kind = "mail.hey"` additionally checks that the `hey` binary is present and new enough — a cheap
`hey --version`, which contacts nothing. Absent or too old is a finding naming the install command, not a
failure of the run.

## Changed: `ikwyd sources check NAME`

Contacts the account and reports one of five states, which FR-010 requires to be distinguishable:

| State | Meaning | What the user does |
|---|---|---|
| `ready` | Token accepted | Nothing |
| `credential absent` | No token stored | `ikwyd sources authorise NAME` |
| `credential expired` | Refresh rejected | `ikwyd sources authorise NAME` |
| `administrator approval required` | The tenant does not permit user consent | Ask IT to approve the application |
| `unreachable` | Network or provider fault | Try later; nothing is wrong with the configuration |
| `tool missing` | (`mail.hey`) `hey` is not installed, or not signed in | Install it, then run `hey` once to sign in |

Conflating the middle three is the failure mode this table exists to prevent: each needs a different action,
and "authentication failed" tells the user none of them.

## Changed: `ikwyd ingest`

Mail accounts are read alongside every other source. One account failing never stops another (FR-017), and
a failure names the account and the state above.

`--sweep` re-reads the full window and may withdraw messages the provider no longer presents — except from
an archive, which never withdraws.

## Changed: `ikwyd records query`

The `PROJECT` column added in `0003` covers mail unchanged. A mail record's `TITLE` is its subject line.

## Changed: `ikwyd projects validate` / `rederive` / `list`

`validate` checks the new `correspondents` and `subjects` entries, reporting every fault in one pass.

`rederive` re-attributes stored mail. It contacts **no account and opens no socket** — structurally, because
`projects/` cannot import `mail/`, `net/` or `socket`, and a test asserts it. `--dry-run` previews, and the
preview matches applying it exactly (FR-045, SC-013).

`list` shows, per project, how many repositories and how many correspondents contribute to it.

## Invariants

| Invariant | Requirement |
|---|---|
| No command writes to any mail account | FR-013, FR-014 |
| No command contacts a destination other than a configured account | FR-019 |
| Only `sources authorise` is interactive | Principle VI |
| Only `sources authorise` and a token refresh write `tokens.toml`; nothing else writes outside the data directory | FR-008 |
| No credential appears in any output, including `--json` and `--verbose` | FR-008 |
| Every query over stored mail works offline | FR-051, SC-015 |
