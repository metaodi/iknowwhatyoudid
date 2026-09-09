# Contract: `--json` output

Every data-emitting command offers `--json` (FR-019, Principle VI). One envelope, one line of JSON on
stdout, diagnostics on stderr.

## Envelope

```json
{
  "schema": "iknowwhatyoudid/v1",
  "command": "sources.validate",
  "ok": false,
  "config_path": "C:\\Users\\ods\\AppData\\Roaming\\iknowwhatyoudid\\config.toml",
  "data": {},
  "findings": []
}
```

| Field | Notes |
|-------|-------|
| `schema` | Bumped only on a breaking change |
| `command` | Dotted command name |
| `ok` | `true` iff exit code is `0` |
| `config_path` | Always present, even when the file is absent — FR-002 requires reporting the exact path looked at |
| `data` | Per-command, below |
| `findings` | Always present; `[]` when clean |

## Finding

```json
{
  "severity": "blocking",
  "code": "duplicate-source-name",
  "source_name": "work-mail",
  "key_path": "source[1].name",
  "line": 14,
  "message": "duplicate source name (also at source[3])",
  "remedy": "names identify a source in the store; give one of them a different name"
}
```

`code` is the stable contract. Tests and consumers key on it, **never on `message`**, so wording can be
improved without breaking anything. `line` is best-effort and may be `null` (research D2) — it is never
asserted on in tests.

Codes in this feature: `parse-error`, `unknown-top-level-key`, `attribution-not-allowed`,
`duplicate-source-name`, `invalid-source-name`, `unknown-kind`, `missing-required-setting`,
`unknown-setting`, `setting-type-mismatch`, `naive-datetime`, `future-datetime`, `credential-missing`,
`credential-unreadable`, `credential-not-required`, `inline-secret`, `file-permissions`,
`file-permissions-unverified`, `unconfigured-source-has-records`, `source-renamed`,
`reading-not-implemented`.

## Per-command `data`

### `sources.list` / `sources.validate`

```json
{
  "sources": [
    {
      "name": "work-mail",
      "kind": "mail.outlook",
      "enabled": true,
      "readiness": "credential_missing",
      "credential": {"name": "outlook-work", "presence": "absent"},
      "destinations": ["Microsoft Graph"]
    }
  ],
  "summary": {"total": 5, "ready": 1, "disabled": 1, "not_readable": 2, "invalid": 0},
  "unconfigured_with_records": [{"name": "old-mail", "record_count": 1284}]
}
```

`unconfigured_with_records` is FR-012: a source removed from the configuration whose records remain. It is
reported rather than deleted, and it appears in `--json` so a script can notice it.

### `sources.kinds`

```json
{
  "kinds": [
    {
      "name": "git.local",
      "summary": "commits, branches and merges in local git repositories",
      "credential_required": false,
      "required_access": [],
      "destinations": [],
      "reading": "not_yet_implemented",
      "settings": [
        {"key": "paths", "type": "path_list", "required": true, "default": null,
         "help": "Repositories to read. Accepts a path or a glob over a containing folder."}
      ]
    }
  ]
}
```

This is the `SourceKind` declaration serialised directly — the same data validation walks, so the
documented contract and the enforced one cannot drift (FR-028, FR-032).

### `sources.destinations`

```json
{"destinations": [{"source": "work-mail", "kind": "mail.outlook", "destination": "Microsoft Graph"}]}
```

### `ingest`

```json
{
  "outcomes": [
    {"source": "recorded-day", "result": "succeeded", "failure": null,
     "detail": null, "records_ingested": 142},
    {"source": "work-mail", "result": "failed", "failure": "credential",
     "detail": "credential 'outlook-work' not found", "records_ingested": 0}
  ],
  "summary": {"succeeded": 1, "failed": 1, "skipped": 2}
}
```

## Guarantees

| Guarantee | Why |
|-----------|-----|
| Redaction is applied to `--json` exactly as to human output | It is the same chokepoint (research D7); a `--json` path that skipped it would be the obvious leak |
| Source order matches file order | Output diffs cleanly across runs |
| `data` is present and well-formed even on failure | A consumer can read `findings` without branching on `ok` first |
| Nothing is written to stdout except this one document | Diagnostics go to stderr, so `| jq` always works |
