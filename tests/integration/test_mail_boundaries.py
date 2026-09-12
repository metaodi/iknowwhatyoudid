"""The boundaries this feature rests on, asserted about the whole codebase.

Three claims are made elsewhere in prose and are worth nothing unless something checks
them:

* only `net/http.py` may reach the network;
* only the two allow-list modules may spawn a process;
* nothing under `projects/` may do either, which is what makes re-derivation provably
  unable to contact a mail account (FR-044).

Every check inspects the **abstract syntax tree**, not the file's text. `0003` learned
that the hard way: a grep for "subprocess" matched a docstring explaining that the module
does not use subprocess, and the test passed for the wrong reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "iknowwhatyoudid"

#: Reaching any of these means opening a socket.
#:
#: `urllib.request` rather than bare `urllib`: `urllib.parse` is pure string manipulation
#: — building a query, splitting a host — and forbidding it would ban URL handling rather
#: than network access, which is not what this boundary is for.
NETWORK_MODULES = frozenset(
    {
        "urllib.request",
        "socket",
        "http.client",
        "http.server",
        "ssl",
        "ftplib",
        "smtplib",
        "imaplib",
        "poplib",
    }
)

#: Reaching any of these means starting a program.
PROCESS_MODULES = frozenset({"subprocess", "os.spawn", "multiprocessing", "pty"})


def imported_modules(path: Path) -> set[str]:
    """Every module name a file imports, from the AST rather than from its text."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import cannot reach the standard library
                continue
            if node.module:
                found.add(node.module)
                found.add(node.module.split(".")[0])
    return found


def modules_under(*parts: str) -> list[Path]:
    root = SRC.joinpath(*parts) if parts else SRC
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def relative(path: Path) -> str:
    return str(path.relative_to(SRC)).replace("\\", "/")


# --- the network door -----------------------------------------------------------------


def test_only_net_http_reaches_the_network() -> None:
    """FR-019 — one module is the whole egress surface.

    This is what lets a reviewer answer "where can this tool connect to?" by reading one
    file, rather than by trusting three provider modules and hoping a fourth never
    appears.
    """
    offenders = {
        relative(path): sorted(imported_modules(path) & NETWORK_MODULES)
        for path in modules_under()
        if imported_modules(path) & NETWORK_MODULES
    }
    offenders.pop("net/http.py", None)
    # `auth/pkce.py` binds a one-shot listener on 127.0.0.1 to receive the OAuth redirect.
    # That is the opposite of egress — nothing leaves the machine, and it is how the
    # authorisation code stays out of the terminal and out of shell history. Listed here
    # rather than left to slip through, so the exception is visible in review.
    loopback = offenders.pop("auth/pkce.py", None)
    if loopback is not None:
        assert loopback == ["http.server"], (
            f"pkce.py reaches further than the loopback listener: {loopback}"
        )
    assert offenders == {}, f"modules reaching the network outside net/http.py: {offenders}"


def test_the_loopback_listener_binds_only_to_127_0_0_1() -> None:
    """The exception above is only safe while it stays on the loopback interface.

    Binding 0.0.0.0 would expose the redirect receiver to the network, which is a very
    different thing from receiving a redirect from the local browser.
    """
    source = (SRC / "auth" / "pkce.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    hosts = {
        node.elts[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Tuple)
        and node.elts
        and isinstance(node.elts[0], ast.Constant)
        and isinstance(node.elts[0].value, str)
        and "." in node.elts[0].value
    }
    assert hosts == {"127.0.0.1"}, hosts


def test_net_http_exists_and_is_the_one_that_does() -> None:
    """The converse, so the test above cannot pass by everything being absent."""
    path = SRC / "net" / "http.py"
    assert path.exists()
    assert imported_modules(path) & NETWORK_MODULES, "net/http.py must be the module that connects"


# --- the process door -----------------------------------------------------------------


def test_only_the_allow_list_modules_start_a_process() -> None:
    """Principle II for an external binary.

    `git` can `push` and `gc`. Confining every invocation to one module is what makes its
    allow-list meaningful — otherwise a second call site could simply not use it. Mail adds
    no third-party binary: the `hey` CLI was investigated and rejected (research R1).
    """
    # Three modules legitimately start a program, and each is a door with a lock on it:
    #   git/binary.py            — 0003's read-only git allow-list
    #   protection/encryption.py — 0001's at-rest probe (`manage-bde`, `fdesetup`,
    #                              `lsblk`), which reads a status and nothing else
    #   cli/editor.py            — 0005's editor launcher
    #
    # The third lock is a **different shape**, which is why it is written out rather than
    # filed under the same rule. An editor cannot be allow-listed: the command is the
    # user's own, chosen in their own environment, and the tool has no basis for approving
    # `vim` and refusing `hx`. What is asserted instead is that the tool never *constructs*
    # a command — `shell=False`, the path appended as the last argument, nothing
    # interpolated (research R4). `tests/unit/test_editor_command.py` checks that through
    # the AST; this test only records that the door exists.
    allowed = {"git/binary.py", "protection/encryption.py", "cli/editor.py"}
    offenders = {
        relative(path): sorted(imported_modules(path) & PROCESS_MODULES)
        for path in modules_under()
        if imported_modules(path) & PROCESS_MODULES and relative(path) not in allowed
    }
    assert offenders == {}, f"modules starting a process outside the three allowed: {offenders}"


# --- re-derivation cannot read a source -----------------------------------------------


@pytest.mark.parametrize("forbidden", ["mail", "net", "auth"])
def test_projects_cannot_reach_a_mail_account(forbidden: str) -> None:
    """FR-044 — structural, not a rule someone has to remember.

    `0003` made re-derivation provably unable to read a repository. Mail is far more
    expensive to re-fetch, so the same guarantee matters more here: changing a mapping
    must never turn into a year of downloads.
    """
    offenders = []
    for path in modules_under("projects"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and forbidden in node.module.split("."):
                offenders.append(relative(path))
            if isinstance(node, ast.ImportFrom) and node.level and node.module == forbidden:
                offenders.append(relative(path))
    assert not offenders, f"projects/ imports {forbidden}/: {sorted(set(offenders))}"


def test_projects_neither_connects_nor_spawns() -> None:
    """The same guarantee stated directly, in case an import route is missed above."""
    forbidden = NETWORK_MODULES | PROCESS_MODULES
    offenders = {
        relative(path): sorted(imported_modules(path) & forbidden)
        for path in modules_under("projects")
        if imported_modules(path) & forbidden
    }
    assert offenders == {}, f"projects/ can reach the outside world: {offenders}"
