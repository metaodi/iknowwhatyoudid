"""Creating a configuration file where none exists — and only there.

This is the **only** module in the tool that writes a configuration file, and keeping it the
only one is what makes "never overwrite" a property of a single function rather than a rule
several modules have to remember. `edit` does not create; nothing else writes.

## What `0002` and `0003` used to forbid

Both said the tool never writes these files and that no command creates them.
[`0005` narrowed that](../../../specs/0005-config-bootstrap/contracts/amendments.md): what
they were protecting is that **a file the user wrote must come back exactly as they left
it** — no reformatting, no reordering, no lost comments. Creating a file that does not exist
destroys nothing, so it is permitted; changing one that does is still forbidden, and there
is deliberately no flag that would.

## The order things happen in

Every file, including the two that hold nothing sensitive:

1. create it **empty**
2. **restrict it to the owner**
3. write the template

Steps 2 and 3 are not swapped, and step 2 is not special-cased to `credentials.toml`. The
obvious implementation — write, then fix the permissions — leaves an instant in which a file
intended to hold secrets is readable by anyone on the machine. Applying the same order to all
three means the sensitive case cannot be the one somebody forgets.

If any step fails, the file is removed again (SC-009). Half of it is worse than none: an
empty `config.toml` looks like a configuration, and every later `init` would report it as
"left alone". Removing it is safe because an existing file returns before step 1, so the
only file this can ever delete is the one this call just made.
"""

from __future__ import annotations

import importlib.resources as resources
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..protection import permissions
from ..templates import TEMPLATES


class Outcome(StrEnum):
    """What happened to one file. Never one verdict for a whole run.

    Three files are each independently either created or already present, so a single
    boolean would have to call either a no-op run or a partial run a failure. Running `init`
    twice is the normal consequence of not remembering whether you ran it.
    """

    CREATED = "created"
    LEFT_ALONE = "left_alone"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Result:
    """One file's outcome, with enough to tell the user what to do next."""

    name: str
    path: Path
    outcome: Outcome
    detail: str = ""

    @property
    def ok(self) -> bool:
        """`LEFT_ALONE` is a success.

        A non-zero exit for "everything was already there" would break
        `ikwyd init && ikwyd sources validate`, which is the obvious thing to type.
        """
        return self.outcome is not Outcome.FAILED


def template_text(template_name: str) -> str:
    """Read one shipped template.

    Through `importlib.resources` rather than a path derived from `__file__`: the templates
    live inside the package precisely so they survive installation, and addressing them by
    module name is what makes that work
    ([research R1](../../../specs/0005-config-bootstrap/research.md)).
    """
    return (
        resources.files("iknowwhatyoudid.templates")
        .joinpath(template_name)
        .read_text(encoding="utf-8")
    )


def create(target: Path, template_name: str) -> Result:
    """Create one file from its template, or leave an existing one completely alone.

    An existing file is detected **before** anything is opened — not by catching an error
    from an exclusive write — so there is no path through this function that touches it.
    """
    name = target.name

    if target.exists():
        # Deliberately the first thing checked, and the function returns here. Nothing
        # below this line can run against a file the user wrote.
        return Result(name, target, Outcome.LEFT_ALONE)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return Result(name, target, Outcome.FAILED, f"could not create the directory: {exc}")

    try:
        text = template_text(template_name)
    except (OSError, ModuleNotFoundError) as exc:  # pragma: no cover — a broken install
        return Result(name, target, Outcome.FAILED, f"template {template_name} is missing: {exc}")

    try:
        # Empty, then restricted, then written. See the module docstring for why the order
        # is not the obvious one.
        target.touch()
        permissions.restrict_to_owner(target)
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        # Remove what we started. Reaching here means the file did **not** exist when this
        # function began — that was checked and returned above — so this can only ever
        # delete our own half-written file, never the user's.
        #
        # Leaving it would be worse than the failure itself: an empty `config.toml` looks
        # like a configuration, and the next `init` would report it as "left alone"
        # forever. A file that is not there is at least honest about it.
        try:
            target.unlink(missing_ok=True)
        except OSError:  # pragma: no cover — nothing better to do, and the real error wins
            pass
        return Result(name, target, Outcome.FAILED, f"could not write it: {exc}")

    return Result(name, target, Outcome.CREATED)


def create_all(config_path: Path) -> list[Result]:
    """Create whichever of the three files are missing, beside *config_path*.

    Each is decided on its own: one present and two absent creates two and leaves one. There
    is no all-or-nothing, because a partial result that is reported leaves the user further
    forward than a rollback that does not.
    """
    from ..config.location import credentials_path_for, projects_path_for

    targets: list[tuple[Path, str]] = [
        (config_path, "config.toml"),
        (projects_path_for(config_path), "projects.toml"),
        (credentials_path_for(config_path), "credentials.toml.template"),
    ]
    # Names must match what the templates package declares, or a rename would silently
    # produce a file nobody asked for.
    assert {template for _, template in targets} == set(TEMPLATES)  # noqa: S101

    return [create(target, template) for target, template in targets]
