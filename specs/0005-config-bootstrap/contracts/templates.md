# Contract: the shipped templates

## Where they live

`src/iknowwhatyoudid/templates/`, read with `importlib.resources`.

**Not `examples/`** — verified by building a wheel:

```text
examples/ present in wheel: False
non-.py files shipped:      ['iknowwhatyoudid/py.typed']
```

`pyproject.toml` declares `packages = ["src/iknowwhatyoudid"]`, so that directory and nothing
else is packaged. Reading templates from `examples/` would have worked for everyone who
cloned the repository and failed for everyone who installed the tool — the worst shape a bug
can take, because the people who wrote it never see it.

The same build proves the fix works: `py.typed` ships, so files inside the package directory
are included. Confirmed directly ([research R1](../research.md)):

```text
templates in wheel:          ['iknowwhatyoudid/templates/config.toml']
importlib.resources reads it: True
```

`templates/` carries an `__init__.py` so it can be addressed by module name rather than by
guessing a filesystem path — which is the point of using `importlib.resources` at all.

## What `examples/` becomes

A `README.md` pointing at `ikwyd init`.

The three `.toml` files **move** out of it; they are not copied. `examples/` is where they
live today and `templates/` is where they live afterwards — one copy either way, so there is
nothing that can drift.

What `examples/` also held was an instruction to
`cp examples/config.toml "$APPDATA/iknowwhatyoudid/"`, and that instruction is precisely what
this feature exists to delete.

## The three templates

| Template | Becomes | Contract it must satisfy |
|---|---|---|
| `config.toml` | `config.toml` | [`0002`'s config-file contract](../../0002-configurable-sources/contracts/config-file.md), as amended by `0004` |
| `projects.toml` | `projects.toml` | [`0003`'s mapping-file contract](../../0003-git-source-projects/contracts/mapping-file.md), as amended by `0004` |
| `credentials.toml` | `credentials.toml` | `0002`'s credentials file, holding placeholders only |

## What every template must satisfy

| Rule | Why | Checked by |
|---|---|---|
| **Placeholders only** — never a plausible-looking value | The constitution requires committed configuration templates to contain placeholders only. A plausible default is worse than an obvious placeholder, because it might be left in place and *work* | `tests/unit/test_templates.py` |
| **Validates cleanly when created** | A template that ships broken is worse than no template | `tests/integration/test_init.py` |
| **Parses as TOML** | Obvious, and the cheapest thing to get wrong while editing a comment | `tests/unit/test_templates.py` |
| **Every source is commented out** | An uncommented example source refers to a path or account the user does not have, so a fresh `sources validate` would fail on day one | `tests/integration/test_init.py` |
| **Explains itself in comments** | The file *is* the documentation; a user reading it should not need the README | review |
| **Contains no real address, path, or token** | Including the author's own — this repository is public | `tests/unit/test_templates.py` |

The credentials template additionally:

| Rule | Why |
|---|---|
| Holds no value that could be mistaken for a credential | A placeholder that looks like a token might be committed by someone who did not read it |
| Is created **owner-only, before any content is written** | There must be no instant at which a file intended to hold secrets is readable by anyone else ([research R5](../research.md)) |

## Why the templates and the validation tests must stay together

`0004` shipped `examples/config.toml` with **uncommented** mail sources that could not
validate, and it was found by running the quickstart by hand rather than by any test.

That is why "validates cleanly when created" is a contract line with a test against it, and
not an assumption. `init` makes these files the first thing a new user sees; a broken one
would be the first thing they see too.
