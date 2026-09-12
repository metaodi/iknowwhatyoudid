"""Resolving an editor command — every case from research R2, spawning nothing.

The resolver is a pure function precisely so that the cases that are hard to reproduce
(a Windows path with spaces, a `$VISUAL` that overrides `$EDITOR`, an editor set to
something that is not installed) can each be a unit test rather than a manual check on
somebody's machine.

The second half of this file asserts the *shape of the launcher* through the AST, because
what protects a user whose configuration directory contains `&` is not that the current
code happens to be careful — it is that no future edit can make it careless without a test
going red.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import editor

EDITOR_SOURCE = Path(editor.__file__)


# --- R2: parsing a setting ----------------------------------------------------------------


def test_a_bare_name_is_one_argument() -> None:
    assert editor.parse("notepad") == ["notepad"]


def test_a_name_with_a_flag_splits() -> None:
    assert editor.parse("code --wait") == ["code", "--wait"]


def test_surrounding_whitespace_is_ignored() -> None:
    assert editor.parse("  vim  ") == ["vim"]


def test_an_empty_setting_yields_nothing() -> None:
    """Distinct from a bad setting: an unset variable must fall through to the next one."""
    assert editor.parse("") == []
    assert editor.parse("   ") == []


def test_an_unquoted_path_with_spaces_survives_when_it_names_a_real_file(
    tmp_path: Path,
) -> None:
    r"""The row both `shlex` modes get wrong (research R2).

    `posix=True` eats the backslashes and `posix=False` keeps the quote characters, so the
    only thing that rescues `C:\Program Files\...\code.exe` is asking the filesystem
    whether the whole value is a file before splitting it at all.
    """
    program = tmp_path / "Program Files" / "editor.exe"
    program.parent.mkdir(parents=True)
    program.write_text("", encoding="utf-8")

    assert editor.parse(str(program)) == [str(program)]


def test_a_quoted_path_with_arguments_splits_correctly(tmp_path: Path) -> None:
    """The row `posix=True` gets right — and the reason step 2 is `posix=True`."""
    program = tmp_path / "Program Files" / "editor.exe"
    program.parent.mkdir(parents=True)
    program.write_text("", encoding="utf-8")

    argv = editor.parse('"' + str(program) + '" -multiInst')

    assert argv == [str(program), "-multiInst"]
    assert '"' not in argv[0], "posix=False would have left the quote in the name"


def test_an_unbalanced_quote_is_not_a_crash() -> None:
    """A broken setting must produce a nameable error, not a traceback."""
    assert editor.parse('"vim') == ['"vim']


# --- R2: which setting wins ----------------------------------------------------------------


def test_visual_wins_over_editor() -> None:
    command = editor.from_environment({"VISUAL": "vim", "EDITOR": "nano"})
    assert command is not None
    assert command.argv == ("vim",)
    assert command.source == "VISUAL"


def test_editor_is_used_when_visual_is_unset() -> None:
    command = editor.from_environment({"EDITOR": "nano"})
    assert command is not None
    assert command.source == "EDITOR"


def test_an_empty_visual_falls_through_to_editor() -> None:
    """Set-but-empty is how a shell profile unsets a variable in practice."""
    command = editor.from_environment({"VISUAL": "", "EDITOR": "nano"})
    assert command is not None
    assert command.source == "EDITOR"


def test_neither_set_is_not_an_error() -> None:
    assert editor.from_environment({}) is None


# --- R3: the platform fallback --------------------------------------------------------------


def test_windows_falls_back_to_the_shell_and_needs_no_argv() -> None:
    command = editor.platform_opener("win32")
    assert command is not None
    assert command.is_platform_open
    assert command.argv == ()


def test_the_environment_is_preferred_over_the_platform(tmp_path: Path) -> None:
    command = editor.resolve(
        tmp_path / "config.toml", environ={"EDITOR": "nano"}, platform="win32"
    )
    assert command is not None
    assert command.source == "EDITOR"
    assert not command.is_platform_open


def test_the_platform_is_used_when_nothing_is_configured(tmp_path: Path) -> None:
    command = editor.resolve(tmp_path / "config.toml", environ={}, platform="win32")
    assert command is not None
    assert command.source == "platform"


# --- naming the editor back to the user -----------------------------------------------------


def test_the_setting_that_chose_the_editor_is_named() -> None:
    """A surprising editor must be traceable to the variable that named it."""
    command = editor.from_environment({"EDITOR": "nano"})
    assert command is not None
    described = editor.describe(command)
    assert "$EDITOR" in described
    assert "nano" in described


def test_a_missing_editor_is_reported_by_name(tmp_path: Path) -> None:
    """FR-023 — "not found" is useless; naming the command that was not found is not."""
    command = editor.Command(("mspaint-9000-definitely-not-installed",), source="EDITOR")

    with pytest.raises(editor.EditorNotFoundError) as caught:
        editor.launch(command, tmp_path / "config.toml")

    assert "mspaint-9000-definitely-not-installed" in str(caught.value)


# --- T031: the shape of the launcher, through the AST ---------------------------------------


def launcher_call() -> ast.Call:
    """The one `subprocess.run` in `editor.py`, from the tree rather than the text."""
    tree = ast.parse(EDITOR_SOURCE.read_text(encoding="utf-8"), filename=str(EDITOR_SOURCE))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert len(calls) == 1, "expected exactly one subprocess.run, found " + str(len(calls))
    return calls[0]


def test_no_shell_is_ever_requested() -> None:
    """A configuration path containing `&` must be an argument, never a command."""
    for keyword in launcher_call().keywords:
        if keyword.arg == "shell":
            assert isinstance(keyword.value, ast.Constant)
            assert keyword.value.value is False
            return
    raise AssertionError("shell= is not stated at all; state it, so it cannot drift")


def test_shell_true_appears_nowhere_in_the_module() -> None:
    tree = ast.parse(EDITOR_SOURCE.read_text(encoding="utf-8"), filename=str(EDITOR_SOURCE))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            assert not (isinstance(node.value, ast.Constant) and node.value.value is True)


def test_the_command_is_a_list_and_the_path_is_its_last_element() -> None:
    """Appended, not interpolated — so it cannot become a flag or a second command."""
    argument = launcher_call().args[0]
    assert isinstance(argument, ast.List), "the command must be a list, never a string"

    last = argument.elts[-1]
    assert isinstance(last, ast.Call), "the last element must be the path"
    assert isinstance(last.func, ast.Name) and last.func.id == "str"

    starred = [element for element in argument.elts if isinstance(element, ast.Starred)]
    assert starred, "the user's own argv must be spread ahead of the path"
    assert argument.elts.index(starred[-1]) < len(argument.elts) - 1


def test_no_string_formatting_reaches_the_command() -> None:
    """An f-string here would be a command line built by the tool. There is none."""
    argument = launcher_call().args[0]
    for node in ast.walk(argument):
        assert not isinstance(node, ast.JoinedStr), "the command must never be formatted"
        if isinstance(node, ast.BinOp):
            assert not isinstance(node.op, ast.Mod), "no %-formatting in the command"


def test_the_module_never_reads_the_file_it_opens() -> None:
    """FR-024 — a file too broken to parse is exactly the one you need to open."""
    tree = ast.parse(EDITOR_SOURCE.read_text(encoding="utf-8"), filename=str(EDITOR_SOURCE))
    forbidden = {"read_text", "read_bytes", "open", "load", "loads"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden, "editor.py calls " + node.func.attr
