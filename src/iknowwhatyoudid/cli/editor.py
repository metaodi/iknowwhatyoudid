"""The only module that launches an editor.

`0003` made `git/binary.py` the only module that may invoke git, guarded by an **allow-list
of subcommands**. This is the third module permitted to spawn a process, and its lock is a
different shape — which is why it is written down rather than filed under the same rule.

**An editor cannot be allow-listed.** The command is chosen by the user, in their own
environment; the tool has no basis for approving `vim` and refusing `hx`. Pretending
otherwise would be theatre.

What *can* be guaranteed is that the tool never **constructs** a command line:

* `shell=False`, always. With a shell, a path containing `&` or `;` becomes a command;
  without one, an argument is an argument.
* the file path is the **last** argument, appended, never interpolated into a string;
* nothing is read from the file in order to open it;
* the command comes from the environment unmodified — the user chose it.

Resolution is a **pure function** returning a list of arguments, so every case in
[research R2](../../../specs/0005-config-bootstrap/research.md) is a unit test that spawns
nothing. Only `launch` needs a process, and it is four lines.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess  # noqa: S404 — see the module docstring; this is a declared door
import sys
from dataclasses import dataclass
from pathlib import Path

#: Tried in this order. `$VISUAL` is the convention for a full-screen editor; `$EDITOR` is
#: older and more widely set.
ENVIRONMENT_VARIABLES = ("VISUAL", "EDITOR")

#: The platform's own "open this with whatever handles it". `os.startfile` is used on
#: Windows and spawns no process at all (research R3).
POSIX_OPENERS = {"darwin": "open"}
DEFAULT_POSIX_OPENER = "xdg-open"


@dataclass(frozen=True, slots=True)
class Command:
    """An editor invocation, resolved but not yet run."""

    argv: tuple[str, ...]
    #: Where it came from — `VISUAL`, `EDITOR`, or `platform`. Shown to the user so a
    #: surprising editor is traceable to the setting that chose it.
    source: str
    #: True for `os.startfile`, which takes no argument vector.
    is_platform_open: bool = False


@dataclass(frozen=True, slots=True)
class Outcome:
    exit_code: int | None


class EditorNotFoundError(Exception):
    """A configured editor names something that is not there.

    Distinct from "nothing is configured": the user set this value, so they can fix it, and
    silently falling through to the system default would hide their mistake.
    """


def parse(value: str) -> list[str]:
    """Split an editor setting into arguments.

    Neither `shlex` mode is correct on Windows, verified both ways (research R2):
    `posix=True` eats the backslashes in `C:\\Program Files\\…`, and `posix=False` keeps the
    quote characters so the executable name literally contains `"`.

    So: if the whole value names an existing file, it is **one argument** — which rescues
    the unquoted Windows path that both parsers mangle, and is how people actually set
    `$EDITOR` there. Otherwise it is split as a shell would, which is right for every Unix
    case and for the quoted Windows one.

    A path containing spaces **and** arguments must be quoted. Nothing can infer that.
    """
    stripped = value.strip()
    if not stripped:
        return []

    if os.path.isfile(stripped):
        return [stripped]

    try:
        return shlex.split(stripped, posix=True)
    except ValueError:
        # An unbalanced quote. Better to treat the whole thing as one name and let the
        # launcher report that it does not exist than to guess at what was meant.
        return [stripped]


def from_environment(environ: dict[str, str] | None = None) -> Command | None:
    """`$VISUAL`, then `$EDITOR`. None if neither is set."""
    env = os.environ if environ is None else environ
    for name in ENVIRONMENT_VARIABLES:
        raw = env.get(name, "")
        argv = parse(raw)
        if argv:
            return Command(tuple(argv), source=name)
    return None


def platform_opener(platform: str | None = None) -> Command | None:
    """The operating system's default application for a file.

    On Windows this is `os.startfile`, which calls `ShellExecute` and spawns no process
    through `subprocess` at all — so the fallback path needs no process there (research R3).
    """
    system = sys.platform if platform is None else platform

    if system.startswith("win"):
        return Command((), source="platform", is_platform_open=True)

    name = POSIX_OPENERS.get(system, DEFAULT_POSIX_OPENER)
    if shutil.which(name):
        return Command((name,), source="platform")
    return None


def resolve(
    path: Path,
    *,
    environ: dict[str, str] | None = None,
    platform: str | None = None,
) -> Command | None:
    """What would open *path*, or None if nothing would.

    Pure: reads the environment and asks whether files exist, and does nothing else. The
    path is accepted so that a future rule could depend on the file type; today it does not.
    """
    configured = from_environment(environ)
    if configured is not None:
        return configured
    return platform_opener(platform)


def describe(command: Command) -> str:
    """How to name the editor in output, so a surprise is traceable to its setting."""
    if command.is_platform_open:
        return "the default application for this file"
    rendered = " ".join(command.argv)
    if command.source in ENVIRONMENT_VARIABLES:
        return f"${command.source} ({rendered})"
    return rendered


def launch(command: Command, path: Path) -> Outcome:
    """Run it, with the path appended last and no shell.

    The path is **appended**, never interpolated: it cannot become a flag, and it cannot
    become a second command. `shell=False` is what makes that true rather than hopeful.
    """
    if command.is_platform_open:
        os.startfile(str(path))  # noqa: S606 — Windows only
        return Outcome(exit_code=None)

    executable = command.argv[0]
    if not os.path.isfile(executable) and shutil.which(executable) is None:
        raise EditorNotFoundError(executable)

    completed = subprocess.run(  # noqa: S603 — argv is the user's own, path appended last
        [*command.argv, str(path)],
        shell=False,
        check=False,
    )
    return Outcome(exit_code=completed.returncode)
