"""`ikwyd init`, `ikwyd sources edit`, `ikwyd projects edit`.

The commands that get a user configured, and the only ones that create a configuration
file. Creating is confined to `config/bootstrap.py`; this module decides *which* files and
reports what happened.

`edit` deliberately does **nothing** once the editor closes — no validation, no ingestion.
Validating automatically only works when the editor blocks, so a graphical editor returning
immediately would report on a file the user had not finished writing, which is worse than
saying nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..config.bootstrap import Outcome, create_all
from ..config.location import (
    credentials_path_for,
    projects_path_for,
    resolve_config_path,
    resolve_projects_path,
)
from ..errors import IkwydError, UsageError
from . import editor
from .commands import Result
from .render import table

#: What each file is for, shown beside it so a new user knows which to open first.
_PURPOSE = {
    "config.toml": "declare the sources to read from",
    "projects.toml": "map repositories and correspondents to projects",
    "credentials.toml": "secrets go here, and nowhere else (readable by you alone)",
}


def init(config: str | None, *, as_json: bool = False) -> Result:
    """Create the three files a user edits, wherever they are missing.

    Never overwrites. There is no flag that would, and
    `test_init.py::test_no_option_exists_that_would_overwrite` walks the parser to keep it
    that way.
    """
    config_path = resolve_config_path(config)
    results = create_all(config_path)

    created = sum(1 for r in results if r.outcome is Outcome.CREATED)
    left_alone = sum(1 for r in results if r.outcome is Outcome.LEFT_ALONE)
    failed = [r for r in results if r.outcome is Outcome.FAILED]

    rows = []
    for result in results:
        label = {
            Outcome.CREATED: "created",
            Outcome.LEFT_ALONE: "left alone",
            Outcome.FAILED: "FAILED",
        }[result.outcome]
        note = result.detail or (_PURPOSE.get(result.name, "") if result.outcome is Outcome.CREATED else "")
        rows.append([label, result.name, note])

    lines = [f"Configuration directory: {config_path.parent}", ""]
    lines.append(table(["", "FILE", ""], rows) or "Nothing to do.")
    lines.append("")

    tail = f"{created} created, {left_alone} left alone."
    if left_alone and not created:
        tail += " Nothing was written."
    lines.append(tail)

    if failed:
        for result in failed:
            lines.append(f"  {result.name}: {result.detail}")
    elif created:
        # FR-018. A command that leaves you wondering what to do next has not finished.
        lines += [
            "",
            "Next: edit the files, then check them.",
            "  ikwyd sources edit",
            "  ikwyd projects edit",
            "  ikwyd sources validate",
        ]
    else:
        lines += ["", "Everything is already in place. `ikwyd sources validate` checks it."]

    payload = {
        "directory": str(config_path.parent),
        "files": [
            {
                "name": r.name,
                "path": str(r.path),
                "outcome": r.outcome.value,
                **({"owner_only": True} if r.name == "credentials.toml" else {}),
                **({"detail": r.detail} if r.detail else {}),
            }
            for r in results
        ],
        "created": created,
        "left_alone": left_alone,
    }

    return Result("init", not failed, config_path.parent, payload, "\n".join(lines))


# --- edit ---------------------------------------------------------------------------------


def edit_sources(config: str | None, *, open_browser: bool = True) -> Result:
    """Open the sources configuration in the user's editor."""
    return _edit(resolve_config_path(config), "sources")


def edit_projects(config: str | None, projects: str | None) -> Result:
    """Open the project mapping in the user's editor."""
    config_path = resolve_config_path(config)
    return _edit(resolve_projects_path(projects, config_path), "projects")


def _edit(path: Path, what: str) -> Result:
    """Hand one file to the user's editor. Read nothing, change nothing.

    The file's contents are never opened — which is precisely why a configuration too broken
    to parse is the one you can still open (FR-024).
    """
    if not path.is_file():
        raise UsageError(
            f"{path} does not exist",
            remedy=(
                "Run `ikwyd init` to create it. This command opens files; it does not "
                "create them."
            ),
        )

    command = editor.resolve(path)
    if command is None:
        raise IkwydError(
            "no editor found: neither $VISUAL nor $EDITOR is set, and no default "
            "application is available for this file",
            remedy=f"Set $EDITOR, or open it yourself:\n    {path}",
        )

    description = editor.describe(command)

    # Announced **before** the editor is launched, and on stderr where diagnostics go.
    # A terminal editor takes over the terminal and does not give it back until the user
    # quits, so a message printed afterwards arrives too late to tell them anything —
    # and reads in the wrong tense when it finally appears.
    print(f"Opening {path} with {description}.", file=sys.stderr)

    outcome = editor.launch(command, path)

    lines: list[str] = []
    if outcome.exit_code not in (0, None):
        # Reported, not treated as failure: editors exit non-zero for many reasons, and
        # refusing to continue would be unhelpful.
        lines.append(f"The editor exited with {outcome.exit_code}.")

    return Result(
        f"{what}.edit",
        True,
        path,
        {
            "path": str(path),
            "editor": description,
            "source": command.source,
            "exit_code": outcome.exit_code,
        },
        "\n".join(lines),
    )


def credentials_path(config: str | None) -> Path:
    """Where the credentials file is, for anyone who wants to open it themselves.

    There is deliberately **no** command that opens it (FR-027): handing a file of secrets
    to whatever `$EDITOR` happens to name is a risk with no matching benefit.
    """
    return credentials_path_for(resolve_config_path(config))


def _unused(value: Any) -> None:  # pragma: no cover
    return None


__all__ = ["credentials_path", "edit_projects", "edit_sources", "init"]
