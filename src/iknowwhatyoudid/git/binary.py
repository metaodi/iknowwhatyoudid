"""The only place git may be invoked (Principle II).

Principle II says no connector may create, modify, delete, send, move, label, archive or
mark-as-read anything in a connected system. This is the first feature pointed at the
user's real repositories, so that is enforced as an **allow-list** rather than a
convention every call site has to remember: a command not listed here cannot be run, and
"no mutating command is ever executed" is checkable in one file.

Verified: hashing every file under `.git` before and after running the listed commands
produced an identical digest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..errors import GitCommandNotAllowedError, GitReadError, GitUnavailableError

#: STRICT tables need it; `--no-commit-header` and modern `%aI` need 2.33.
MINIMUM_GIT = (2, 33, 0)

DEFAULT_TIMEOUT_SECONDS = 60

#: The complete set of git subcommands this project may run. Every one is read-only.
#: `status` is deliberately absent: it was verified not to write in the case tested, and
#: the design does not depend on knowing the conditions under which it would.
ALLOWED: frozenset[str] = frozenset(
    {
        "rev-parse",
        "rev-list",
        "log",
        "for-each-ref",
        "cat-file",
        "reflog",
        "--version",
    }
)

#: Applied to every invocation.
#:   OPTIONAL_LOCKS   git takes no lock it does not strictly need, so a read cannot
#:                    interfere with the user working in the repository (FR-020)
#:   TERMINAL_PROMPT  never block waiting for credentials
#:   CONFIG_NOSYSTEM  system config cannot introduce a hook or alias that changes what
#:                    these commands do
_SAFE_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_ASKPASS": "",
    "GIT_PAGER": "cat",
    "LC_ALL": "C",
}

#: Applied as `-c` options, before the subcommand.
_SAFE_CONFIG = (
    "gc.auto=0",  # no maintenance as a side effect
    "core.fsmonitor=false",  # no monitor process started
    "log.showSignature=false",  # no signature verification, so no keyring, no network
    "core.hooksPath=",  # no repository hook can run
    "protocol.version=0",
)


@dataclass(frozen=True, slots=True)
class GitVersion:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def supported(self) -> bool:
        return (self.major, self.minor, self.patch) >= MINIMUM_GIT


def find_git() -> str | None:
    return shutil.which("git")


def require_git() -> str:
    path = find_git()
    if path is None:
        raise GitUnavailableError(
            "git is not on PATH",
            remedy=(
                "Install git and make sure `git --version` works, then run this again. "
                "Nothing has been read."
            ),
        )
    return path


def version() -> GitVersion:
    output = _invoke(None, "--version", timeout=10)
    parts = output.split()
    numbers = parts[2] if len(parts) > 2 else "0.0.0"
    pieces = (numbers.split(".") + ["0", "0", "0"])[:3]
    try:
        return GitVersion(*(int("".join(c for c in p if c.isdigit()) or 0) for p in pieces))
    except (TypeError, ValueError):  # pragma: no cover
        return GitVersion(0, 0, 0)


def require_supported_git() -> GitVersion:
    found = version()
    if not found.supported:
        wanted = ".".join(str(p) for p in MINIMUM_GIT)
        raise GitUnavailableError(
            f"git {found} is too old; this needs {wanted} or newer",
            remedy="Upgrade git. Nothing has been read.",
        )
    return found


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    env.update(_SAFE_ENV)
    return env


def _command(subcommand: str, *args: str) -> list[str]:
    """The argv for one allowed command, or a refusal.

    Every path to a subprocess goes through here, so the allow-list cannot be bypassed
    by adding a second way to run git.
    """
    if subcommand not in ALLOWED:
        raise GitCommandNotAllowedError(
            f"`git {subcommand}` is not on the read-only list",
            remedy=(
                "Only read-only plumbing may be run against a user's repository. "
                "If a new command is genuinely needed, add it to ALLOWED in "
                "git/binary.py so the change is visible in review."
            ),
        )

    command = [require_git()]
    for setting in _SAFE_CONFIG:
        command += ["-c", setting]
    command.append(subcommand)
    command.extend(args)
    return command


def _invoke(
    repository: Path | None,
    subcommand: str,
    *args: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    command = _command(subcommand, *args)

    try:
        result = subprocess.run(
            command,
            cwd=str(repository) if repository is not None else None,
            env=_environment(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitReadError(
            f"`git {subcommand}` timed out after {timeout}s"
            + (f" in {repository}" if repository else ""),
            remedy="The repository is unchanged. It was skipped; the others still ran.",
        ) from exc
    except OSError as exc:
        raise GitReadError(f"could not run git: {exc}") from exc

    if result.returncode != 0:
        raise GitReadError(
            f"`git {subcommand}` failed"
            + (f" in {repository}" if repository else "")
            + f": {result.stderr.strip() or result.returncode}",
            remedy="The repository is unchanged and was skipped.",
        )
    return result.stdout


def run(repository: Path, subcommand: str, *args: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Run one allowed read-only command in *repository* and return its stdout."""
    return _invoke(repository, subcommand, *args, timeout=timeout)


def run_lines(repository: Path, subcommand: str, *args: str) -> list[str]:
    output = run(repository, subcommand, *args)
    return [line for line in output.splitlines() if line]


def stream_lines(repository: Path, subcommand: str, *args: str) -> Iterator[str]:
    """As `run_lines`, but yields each line as git produces it.

    A developer's repository can hold tens of thousands of commits. Reading all of them
    into one string before parsing any makes peak memory a function of how long you have
    worked somewhere, which is the wrong shape for a tool that runs on a laptop. This
    reads a pipe instead, so only one line is held at a time.

    The caller may stop early; the pipe is then closed and git is terminated, which is
    safe precisely because everything on the allow-list only reads.
    """
    command = _command(subcommand, *args)
    try:
        process = subprocess.Popen(  # noqa: S603 — argv is built by `_command`
            command,
            cwd=str(repository),
            env=_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise GitReadError(f"could not run git: {exc}") from exc

    assert process.stdout is not None
    try:
        for line in process.stdout:
            stripped = line.rstrip('\r\n')
            if stripped:
                yield stripped
    finally:
        stopped_early = process.poll() is None
        process.stdout.close()
        if stopped_early:
            process.terminate()
        stderr = process.stderr.read() if process.stderr is not None else ""
        if process.stderr is not None:
            process.stderr.close()
        returncode = process.wait()
        if returncode != 0 and not stopped_early:
            raise GitReadError(
                f"`git {subcommand}` failed in {repository}: "
                f"{stderr.strip() or returncode}",
                remedy="The repository is unchanged and was skipped.",
            )


def try_run(repository: Path, subcommand: str, *args: str) -> str | None:
    """As `run`, but returns None where the command legitimately fails.

    Used for questions whose negative answer is not an error — "is this a repository?",
    "does it have a root commit?".
    """
    try:
        return run(repository, subcommand, *args)
    except GitReadError:
        return None
