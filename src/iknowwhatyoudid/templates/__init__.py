"""The files `ikwyd init` copies into your configuration directory.

This is a package directory — with this `__init__.py` — for one reason: it lets
`importlib.resources` address the templates **by module name** rather than by guessing a
filesystem path relative to `__file__`. That guess is what breaks when the tool is
installed rather than run from a checkout.

**These files used to live in `examples/`, and that did not work.** Verified by building a
wheel: `pyproject.toml` declares `packages = ["src/iknowwhatyoudid"]`, so the wheel contains
that directory and nothing else. `ikwyd init` installed with `uv tool install` would have had
nothing to copy from — working perfectly for anyone who cloned the repository and failing for
everyone who installed the tool. See `specs/0005-config-bootstrap/research.md` R1.

They moved here rather than being copied here. There is one copy, and `examples/README.md`
says where it went.

Every file here must hold **placeholders only** — the constitution requires it of committed
configuration templates, and this repository is public. `tests/unit/test_templates.py`
checks that, that each parses as TOML, and that a wheel really does contain them.
"""

from __future__ import annotations

#: Template file name → the name `init` creates it under.
#:
#: `credentials.toml.template` keeps its suffix deliberately. `.gitignore` carries a
#: `credentials.toml` rule so a user's real secrets can never be committed — and hatchling
#: honours `.gitignore` when deciding what goes in the wheel, so a template named
#: `credentials.toml` is silently dropped from every installed copy. The packaging test in
#: `tests/unit/test_templates.py` caught exactly that.
TEMPLATES: dict[str, str] = {
    "config.toml": "config.toml",
    "projects.toml": "projects.toml",
    "credentials.toml.template": "credentials.toml",
}
