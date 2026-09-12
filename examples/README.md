# The example files moved — run `ikwyd init` instead

This directory used to hold `config.toml`, `projects.toml` and `credentials.toml.example`,
together with an instruction to copy them into your configuration directory by hand.

That instruction is gone, because the tool now does it:

```bash
ikwyd init
```

It creates all three where the tool looks for them, tells you where that is, and **never
overwrites a file that already exists** — there is no `--force`, deliberately. Run it as
often as you like; the second run reports that everything is already there and writes
nothing.

Then:

```bash
ikwyd sources edit      # open the configuration in your editor
ikwyd projects edit     # open the project mapping
ikwyd sources validate  # check it, offline, before reading anything
```

## Where the files live now

[`src/iknowwhatyoudid/templates/`](../src/iknowwhatyoudid/templates/) — inside the package,
so they ship with an installed tool.

They had to move. `pyproject.toml` packages `src/iknowwhatyoudid` and nothing else, so
anything in `examples/` is absent from the wheel: `ikwyd init` would have worked for anyone
who cloned this repository and failed for everyone who installed it. That is written up in
[`specs/0005-config-bootstrap/research.md`](../specs/0005-config-bootstrap/research.md) R1,
with the wheel listing that proves it.

They **moved** rather than being copied — there is one copy of each file, not two, so there
is nothing that can drift.

## Reading them without installing anything

They are ordinary TOML with comments explaining each setting:

- [`config.toml`](../src/iknowwhatyoudid/templates/config.toml) — which sources to read from
- [`projects.toml`](../src/iknowwhatyoudid/templates/projects.toml) — how activity maps to projects
- [`credentials.toml`](../src/iknowwhatyoudid/templates/credentials.toml) — where secrets go, and nowhere else

Every value that needs your attention is an obvious placeholder. None of them contains a real
address, path or token.
