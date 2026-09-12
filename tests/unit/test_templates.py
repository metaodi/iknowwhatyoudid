"""The files `ikwyd init` creates (FR-013, research R1).

Two kinds of assertion here, and the second is the one that matters most.

**Content**: each template parses, holds placeholders only, and carries no real address,
path or token — this repository is public, and the constitution requires committed
configuration templates to contain placeholders only.

**Packaging**: a wheel really does contain them. That is the test that would have caught the
original bug, where templates lived in `examples/` and were absent from every installed copy
of the tool. It is the only test in the suite that runs a build, and it is marked `slow` for
that reason — but skipping it would let the feature break silently for installed users while
every other test stayed green.
"""

from __future__ import annotations

import importlib.resources as resources
import tomllib
import zipfile
from pathlib import Path

import pytest

from iknowwhatyoudid.templates import TEMPLATES

ROOT = Path(__file__).resolve().parents[2]

#: Strings that would mean a real value had been committed. `REPLACE` is the convention the
#: existing examples already use.
PLACEHOLDER_MARKERS = ("REPLACE", "example.com", "example.org", "primary")

#: Anything matching these is a real value that escaped review.
FORBIDDEN = (
    "oderbolz",          # the author's own name, in any address or path
    "metaodi",           # and their domain
    "@hey.com",
    "@gmail.com",
    "@ebp.ch",
    "C:\\Users\\",       # a real Windows home directory
    "/home/",            # or a real POSIX one
    "ghp_",              # a GitHub token
    "xoxb-",             # a Slack token
    "BEGIN RSA PRIVATE KEY",
)


def read(name: str) -> str:
    return resources.files("iknowwhatyoudid.templates").joinpath(name).read_text(
        encoding="utf-8"
    )


# --- content ---------------------------------------------------------------------------


def test_every_template_is_readable_through_importlib() -> None:
    """The path an installed user gets, not a filesystem guess from `__file__`."""
    for name in TEMPLATES:
        assert read(name).strip(), name


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_template_parses_as_toml(name: str) -> None:
    """The cheapest thing to break while editing a comment."""
    tomllib.loads(read(name))


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_no_template_carries_a_real_value(name: str) -> None:
    """This repository is public, and these files are the first thing a user opens."""
    text = read(name)
    found = [marker for marker in FORBIDDEN if marker.lower() in text.lower()]
    assert not found, f"{name} contains {found}"


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_template_uses_obvious_placeholders(name: str) -> None:
    """A plausible-looking default is worse than a placeholder.

    A placeholder gets replaced. A default that looks reasonable might be left in place —
    and might even work, against something the user did not intend.
    """
    text = read(name)
    assert any(marker in text for marker in PLACEHOLDER_MARKERS), name


def test_any_active_source_in_the_config_template_is_all_placeholders() -> None:
    """A freshly created configuration must not fail to validate on day one.

    `0004` shipped an `examples/config.toml` with uncommented mail sources that could not
    validate, and it was found by running the quickstart by hand rather than by any test.
    `init` makes this file the first thing a new user sees.

    An active source is allowed, and is arguably better than none: it produces a warning
    that names the thing to edit. What it must not do is carry a value that looks real.
    """
    document = tomllib.loads(read("config.toml"))
    for source in document.get("source", []):
        rendered = str(source)
        assert "REPLACE" in rendered, f"active source is not a placeholder: {source}"
        assert "credential" not in source, (
            "an active source must not name a credential, or a fresh validate reports it "
            "missing before the user has done anything wrong"
        )


def test_the_credentials_template_holds_no_value_resembling_a_secret() -> None:
    """A placeholder that looks like a token might be committed by someone who did not read it."""
    text = read("credentials.toml.template")
    document = tomllib.loads(text)
    for name, entry in document.get("credential", {}).items():
        if isinstance(entry, dict):
            for key, value in entry.items():
                assert "REPLACE" in str(value), f"credential.{name}.{key} is not a placeholder"


# --- the files really moved ----------------------------------------------------------------


def test_examples_holds_no_template() -> None:
    """One copy, one location (research R1). Two would drift."""
    stray = sorted(p.name for p in (ROOT / "examples").glob("*.toml*"))
    assert stray == [], f"examples/ still holds {stray}"


def test_examples_explains_where_they_went() -> None:
    """Someone browsing the repository should not find an empty directory."""
    readme = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    assert "ikwyd init" in readme
    assert "templates" in readme


# --- packaging: the test that would have caught the original bug -------------------------


@pytest.mark.slow
def test_the_templates_are_inside_a_built_wheel(tmp_path: Path) -> None:
    """Research R1, asserted rather than remembered.

    `examples/` was not in the wheel, so an installed `ikwyd init` would have had nothing to
    copy — working for everyone who cloned the repository and failing for everyone else.
    This is the only test that runs a build; if it is ever skipped, that failure mode comes
    back silently while every other test stays green.
    """
    import subprocess

    result = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, wheels
    inside = set(zipfile.ZipFile(wheels[0]).namelist())

    for name in TEMPLATES:
        assert f"iknowwhatyoudid/templates/{name}" in inside, (
            f"{name} is missing from the wheel — an installed `ikwyd init` would fail"
        )
