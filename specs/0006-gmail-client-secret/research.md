# Research: Reading a Secret, and Saying What Went Wrong

Everything below was checked against the code or against a live provider. Where something
could not be verified, it says so.

---

## R1. Google requires the secret — observed, not inferred

**Finding**: `oauth2.googleapis.com/token` refuses the authorization-code exchange for a client
registered as `installed` unless `client_secret` is present. Observed 2026-09-12:

```json
{ "error": "invalid_request", "error_description": "client_secret is missing." }
```

The request that produced it carried `client_id`, `grant_type`, `code`, `redirect_uri` and
`code_verifier` — a correct PKCE exchange, and correct for Microsoft, which issues no secret to a
public client.

**Decision**: send `client_secret` for Gmail, in both the code exchange and the refresh call.

**Unverified, and stated as such**: only the *exchange* has been observed to require it. Google's
refresh grant for installed clients is documented to take the same pair, and the design sends it
in both places, but no refresh has yet been performed by this tool against a live account —
there has never been a stored Gmail token to refresh. If the refresh turns out not to need it,
sending it is harmless; if it needs something further, the first `ingest` after this feature will
say so in the provider's own words, which R3 is what makes possible.

**Alternatives considered**: registering the OAuth client as a *Web application* instead, which
can use PKCE without a secret. Rejected: a web client requires a fixed registered redirect URI,
which defeats the OS-chosen loopback port this tool depends on, and would make every user
register a port.

---

## R2. The loopback-host question is closed

**Finding**: the registered redirect URI was `http://localhost` while the tool redirected to
`http://127.0.0.1:52876/`. The redirect arrived, the code was received, and the flow reached the
token exchange — which is past the point where a mismatch is rejected.

**Decision**: no redirect change is needed, and the uncertainty recorded when Gmail was first
configured can be closed. Google treats the two loopback hosts as equivalent for `installed`
clients, and ignores the port.

---

## R3. Where the refresh gets the secret

**The problem**: `MailReader` performs the refresh. It holds `_config_path` and receives the
`ConfiguredSource` — which carries `credential`, a `CredentialReference` holding the name — but
it has no credential store. `tokens.toml` stores `client_id` and `tenant`, not a secret.

**Decision**: **inject the credential store into the reader**, mirroring the `use_config_path`
setter that already exists for exactly this shape of dependency. `sources/run.py` orchestrates
and `open_config` already constructs the store, so the value travels the path the config path
already travels.

**Rationale**: the reader needs *a* way to resolve a credential name to a value; the question is
only whether it reaches for one or is handed one. Being handed one keeps the number of places
that construct a credential store at one, which is what makes FR-001a ("the accessor is the only
way") checkable rather than aspirational.

**Alternatives considered**:

- **Store the secret in `tokens.toml` alongside the refresh token.** Rejected: it would copy a
  secret into a second file for no gain. The file already exists and is already permission-checked,
  so this is not a new exposure in kind — but it is a second copy to rotate, and a stale copy
  after the user changes the secret in Google's console would fail with a message pointing at the
  wrong file.
- **Let the reader construct its own store from `_config_path`.** Rejected: it puts credential
  access in a second module, and the boundary this feature introduces is exactly the thing that
  should not be reachable from two places.
- **Pass the resolved secret rather than the store.** Rejected: it would mean resolving every
  account's secret before any is needed, so a run that touches one Gmail account would read them
  all.

---

## R4. Redaction covers more than expected — and two new holes

**Finding**, by reading the code rather than assuming:

| Path | Redacted? | How |
|---|---|---|
| `--json` output | Yes | `render.envelope()` wraps the whole payload in `redact()` |
| Human output | Yes | `render.human()` applies `redact()` |
| **Error messages** | Yes | `IkwydError` → `commands.fail()` → a `Result` → the same two functions |
| The log | Yes | `RedactingFilter` is installed on the logger |
| **`print(..., file=sys.stderr)`** | **No** | Goes nowhere near `render.py` |

The last row is the finding. There are now **two** direct-print sites that bypass the chokepoint,
and both were added in the last two days:

- `cli/setup_commands.py` — the "Opening … with $EDITOR" line (`0005`)
- `cli/mail_commands.py` — the authorisation narration (added while diagnosing this bug)

Neither prints a secret today. The narration prints the sign-in URL, which carries the
`client_id`, and a client_id is explicitly not a secret. But `render.py`'s own docstring says the
point of a chokepoint is that the property holds "for every command written from now on,
including ones nobody has thought of yet", and a direct `print` is precisely the convention-decay
it was built to prevent.

**Decision**: route both through `redact()`, and add a test that fails if a new direct print to a
user-facing stream appears in `cli/` without it — checked through the AST, in the manner `0003`
and `0004` already use for their boundaries.

**Rationale**: this feature introduces the first value that *must not* be printed. Leaving two
unguarded exits while adding the thing they might exit with is the wrong order to do it in.

---

## R5. A secret shorter than six characters is silently not registered

**Finding**: `redaction.register()` ignores any value under `_MIN_LENGTH = 6`, deliberately —
below that, masking mangles ordinary text. Google's client secrets are `GOCSPX-` plus around 28
characters, so this never bites in practice.

**Decision**: leave the threshold alone, and do **not** add a special case. Instead, treat it as
what it is — a documented limit — and make the accessor's contract say that registration is
attempted for every value, not that it is guaranteed for every value.

**Rationale**: lowering the threshold to cover a hypothetical short secret would mask common
short strings across all output, which is a real cost against an imaginary benefit. A six-character
OAuth secret does not exist.

---

## R6. Which kinds send a secret must be declared, not hardcoded

**The problem**: FR-006a requires `sources validate` to warn when a secret sits in an entry
belonging to a kind that never sends one. The validator must therefore know which kinds do.

**Decision**: `SourceKind` gains a declarative boolean. The validator asks the kind; it does not
test for the string `mail.gmail`.

**Rationale**: `0004` already put `credential_required`, `required_access` and `destinations` on
`SourceKind` for exactly this reason — so that `sources kinds` can print the truth and the
validator can check it without a table of special cases. A hardcoded provider name in the
validator would be the one place the truth is written twice.

**Alternatives considered**: inferring it from whether the kind has a token endpoint. Rejected:
Microsoft has one too, and needs no secret — the two properties are unrelated and only look
correlated in a sample of two.

---

## R7. Bounding the provider's response

**Decision**: 500 characters, already implemented as `MAX_REFUSAL_CHARACTERS`.

**Rationale**: an OAuth error body is a short JSON object — the one in R1 is 78 characters.
Anything appreciably longer is a provider's HTML error page, and pasting a page of markup into a
terminal helps nobody. The cap is a named constant rather than a literal so that the test can
assert against the same number the code uses.

**Alternatives considered**: parsing the JSON and extracting `error_description`. Rejected for
now: it works for both providers today, and fails silently the moment one answers with something
that is not the shape expected — at which point the user would see nothing at all, which is the
state this feature exists to end. Showing the raw text is worse-looking and more honest.

---

## R8. No new dependency, no new destination, no migration

- **Dependencies**: none added. The whole feature is one extra form field, one accessor, one
  validator rule, and tests.
- **Network destinations**: unchanged. `oauth2.googleapis.com` was already declared by `0004` and
  is already in the allow-list; this feature changes what is *sent* to it, not where.
- **Schema**: untouched. Nothing here reads or writes the store.
- **Credential scope**: unchanged. `gmail.metadata` is what is requested before and after; a
  client secret authenticates the *application*, not the user, and widens no grant.
