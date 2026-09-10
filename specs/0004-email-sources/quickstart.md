# Quickstart: validating Email Sources and Correspondent Attribution

How to prove this feature works. Every scenario runs against **recorded fixtures** — hand-built `.mbox`
files and captured provider responses. Per the constitution, **no test contacts a live mail account**, and
none may run against the developer's own mailbox.

## Prerequisites

```bash
uv sync
uv run mypy src tests      # must be clean
uv run pytest              # must be green
```

Fixtures live in `tests/fixtures/mail/` (archives) and `tests/fixtures/responses/` (recorded Graph and
Gmail JSON). Every fixture body contains the sentinel string `SENTINEL-BODY-MUST-NEVER-BE-STORED`, and every
attachment is named `SENTINEL-ATTACHMENT.pdf`. Several scenarios below search the entire store for those.

---

## Scenario 0 — the `hey` CLI cannot send (US4, FR-013, Principle II)

```bash
uv run pytest tests/integration/test_mail_readonly.py -k hey -v
```

Assert that `mail/hey_cli.py` refuses every mutating subcommand — `compose`, `reply`, `event`, `setup` —
with `HeyCommandNotAllowedError`, and that it is the **only** module in the codebase importing `subprocess`,
checked by inspecting imports through the AST rather than by grepping text (which `0003` learned to distrust
when a docstring matched).

Assert too that `thread read`, though allow-listed as read-only, is **not invoked by the reader** — because
it returns bodies, and FR-023 for Hey rests on never asking for one.

## Scenario 1 — nothing is written, anywhere (US1, FR-013, FR-014, SC-002, SC-003)

**The guarantee the feature rests on**, and the first thing to test.

```bash
uv run pytest tests/integration/test_mail_readonly.py -v
```

Three levels, weakest to strongest:

1. **Behavioural**: hash an `.mbox` fixture before and after a full ingestion including `--sweep`; assert
   the bytes and the modification time are identical.
2. **Structural**: assert `net/http.py` issues only `GET` and `POST` to token endpoints, and that no
   provider module contains a call that could mutate — by inspecting the module's AST, not by grepping its
   text, which `0003` learned the hard way when a docstring matched.
3. **By construction**: assert the requested scopes are exactly `Mail.ReadBasic offline_access` and
   `gmail.metadata`. Neither grants a write. This is the level that actually holds.

## Scenario 2 — no body and no attachment reaches the store (FR-023, FR-024, SC-004)

```bash
uv run pytest tests/integration/test_mail_shape.py -k sentinel -v
```

Ingest fixtures whose bodies and attachment names contain sentinels, then search **every column of every
table**, plus the log file, for either sentinel. Zero hits.

Assert too that `format=metadata` and `$select` are what the provider modules actually send — so the
guarantee survives someone later "helpfully" widening a field list.

## Scenario 3 — only sent mail (FR-048, SC-004a)

Ingest an archive containing both mail the user sent and mail they received. Assert only the sent messages
became records, and that `mail list` ends with `sent mail only — received mail is not read` (FR-049).

For the API providers, assert the request asked for the **Sent** folder or label — received mail is never
fetched, not fetched and discarded.

## Scenario 4 — one shape, four providers (US3, US4, FR-028, SC-014)

```bash
uv run pytest tests/integration/test_mail_shape.py -v
```

The same assertions run **unchanged** against a Graph fixture, a Gmail fixture, a recorded `hey search
--json` output and an `.mbox` fixture. If any provider needs its own assertion, FR-028 is broken.

Includes: an offset-preserving instant (`+0100` stays `+0100`), an empty subject recorded as empty, a
fifty-recipient broadcast recorded in full, an encoded-word subject decoded, and a message with no `Date`
skipped and reported by identifier rather than given an invented time.

## Scenario 5 — the same message from two sources is one record (FR-020, R10)

Put one message in both a Graph fixture and an `.mbox` export. Ingest both. Assert **one** record, because
identity is the `Message-ID` rather than any provider's own id.

## Scenario 6 — attribution by correspondent and by subject (US2, FR-032 to FR-035)

```bash
uv run pytest tests/integration/test_mail_attribution.py -v
```

| Case | Expected |
|---|---|
| Address rule matches a recipient | `mapping:correspondent`, evidence names the address |
| Domain rule matches a subdomain | `mapping:correspondent-domain` |
| Subject rule matches a bracketed tag | `mapping:subject`, evidence names the text |
| Subject and correspondent disagree | Subject wins (FR-036) |
| Address and domain rule disagree | Address wins, whatever the declaration order |
| Two subject rules match | The one declared first wins |
| **`[ACME]` as a subject rule** | Matches `Re: [ACME] plan` and **not** `A message` — the glob trap ([research R11](../research.md)) |
| Nothing matches | `mapping:ad-hoc-domain`, marked ad hoc |

## Scenario 7 — the ad-hoc domain is deterministic (FR-039, SC-010b)

The case that has no obvious answer: a message sent to two organisations.

Assert the algorithm in [data-model.md](./data-model.md) — own domains discarded, most frequent of the rest,
ties broken alphabetically, own domain where nothing remains. Then ingest the same fixture twice in
**different orders** and assert the attributions are byte-identical.

## Scenario 8 — changing the mapping re-attributes nothing re-read (US2, FR-044, SC-008)

1. Ingest fixture mail; hand-correct one message's project.
2. Change `projects.toml`.
3. Run `projects rederive` with **the fixture files deleted** and sockets forbidden.

| Assertion | Requirement |
|---|---|
| Every affected message carries the new project | FR-044 |
| Zero sockets opened, zero files read | FR-044, SC-008 |
| The corrected message keeps its correction | FR-043, SC-009 |
| `--dry-run` predicts exactly what applying it does | FR-045, SC-013 |
| No module under `projects/` imports `mail/`, `net/` or `socket` | structural |

Deleting the fixtures is the point: it makes "reads nothing" impossible to pass by accident.

## Scenario 9 — the four credential states are distinguishable (FR-010, SC-012)

```bash
uv run pytest tests/integration/test_mail_auth.py -v
```

Against recorded responses: no token; a refresh rejected with `invalid_grant`; an `AADSTS65001`
administrator-approval response; a network failure. Four distinct messages, each naming the next action.

Assert also that **no token or code appears** in stdout, stderr, `--json`, `--verbose`, or the log.

## Scenario 10 — one account failing never silences another (FR-017, SC-011)

Configure three accounts; make one fail. Assert the other two ingest fully, the failed one is named with its
state, and the exit code is non-zero.

## Scenario 11 — resumption and withdrawal (FR-015, FR-016, R13)

| Step | Expected |
|---|---|
| Ingest, then ingest again unchanged | Zero new records (SC-006) |
| Ingest, add a message, ingest | Only the new message is fetched |
| A stored delta token is rejected | Falls back to a bounded full read; no data lost |
| A Gmail `historyId` returns 404 | Falls back to a full `SENT` list; the store deduplicates |
| `--sweep`, a message removed at the provider | Marked withdrawn, not deleted |
| `--sweep` over an **archive** | **Nothing withdrawn ever**, whatever the archive omits |

The last row is the one most likely to be got wrong, and it is the same trap `0003` hit with the git reflog.

## Scenario 12 — the migration (m0003)

```bash
uv run pytest tests/integration/test_migration_m0003.py -v
```

Against **both an empty and a populated store**. Cases are in
[contracts/schema-m0003.md](./contracts/schema-m0003.md); the load-bearing ones are that a populated v2
store keeps every count, that a deliberately failing migration leaves the store at v2 with both new tables
absent, and that corrections are untouched.

## Scenario 13 — `tokens.toml` is the only thing written outside the store (FR-008)

Snapshot the real configuration and data directories, run every command in this feature against fixtures,
and assert nothing in them changed. Then assert `tokens.toml` is created with user-only permissions and that
reading it with wider permissions is refused, using `0001`'s existing permission machinery.

## Scenario 14 — everything answers offline (FR-051, SC-015)

Ingest, then forbid sockets entirely and run `mail list`, `mail correspondents`, `records query`,
`projects list` and `projects rederive`. All succeed.

---

## Known limits at the end of this feature

These are properties of the sources, not of the implementation, and the tool states them:

1. **Received mail is not read.** By decision, not omission — `mail list` says so on every listing.
2. **Hey needs its official CLI installed and signed in.** There is no IMAP, POP or third-party API; the
   `hey` binary is the route ([research R1](./research.md)). Without it that account reports `tool missing`
   and the others still ingest.
3. **Gmail needs re-authorising about weekly**, unless the OAuth app goes through Google verification and a
   CASA assessment ([research R4](./research.md)).
4. **A company tenant may refuse entirely**, and whether it does is not knowable in advance
   ([research R6](./research.md)).
5. **An archive never withdraws.** A message absent from a later export stays in the store until the user
   removes it by hand — an export proves nothing about a mailbox.
6. **No hours are produced.** Mail is recorded as points in time; turning them into durations is a later
   feature.
