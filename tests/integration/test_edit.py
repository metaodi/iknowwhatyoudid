"""`ikwyd sources edit` and `ikwyd projects edit` — opening the file, and nothing else.

No test here spawns a real editor. The launcher is substituted and what gets recorded is
the *path that was handed over*, because that is the whole behaviour of these commands:
choose the right file, pass it to whatever the user uses, and stay out of the way.

The last test in this file is about `ingest` rather than `edit`, and belongs here anyway:
it asserts that no interactive command is reachable from the one command a user schedules.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import editor
from iknowwhatyoudid.cli.main import main

FIXTURES = Path("tests/fixtures/configs")
SRC = Path(__file__).resolve().parents[2] / "src" / "iknowwhatyoudid"


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[str, ...], Path]]:
    """Record what would have been launched, and launch nothing."""
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_launch(command: editor.Command, path: Path) -> editor.Outcome:
        calls.append((command.argv, path))
        return editor.Outcome(exit_code=0)

    # Patched on the module itself: `setup_commands` holds a reference to this module,
    # not to the function, so the substitution is seen at the call site.
    monkeypatch.setattr(editor, "launch", fake_launch)
    monkeypatch.setenv("VISUAL", "")
    monkeypatch.setenv("EDITOR", "notepad")
    return calls


def configured(tmp_path: Path) -> Path:
    """A configuration directory holding all three files."""
    space = tmp_path / "config-dir"
    space.mkdir()
    shutil.copy(FIXTURES / "valid.toml", space / "config.toml")
    (space / "projects.toml").write_text("[[projects]]\nname = 'a'\n", encoding="utf-8")
    (space / "credentials.toml").write_text("# nothing\n", encoding="utf-8")
    return space


# --- the right file is handed over ----------------------------------------------------------


def test_sources_edit_hands_over_the_configuration_path(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-019."""
    space = configured(tmp_path)

    code = main(["sources", "edit", "--config", str(space / "config.toml")])
    capsys.readouterr()

    assert code == 0
    assert [path for _, path in opened] == [space / "config.toml"]


def test_projects_edit_hands_over_the_mapping_path(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-020 — the mapping, not the configuration. They are different files."""
    space = configured(tmp_path)

    code = main(["projects", "edit", "--config", str(space / "config.toml")])
    capsys.readouterr()

    assert code == 0
    assert [path for _, path in opened] == [space / "projects.toml"]


def test_projects_edit_honours_an_explicit_mapping(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    elsewhere = tmp_path / "other-mapping.toml"
    elsewhere.write_text("[[projects]]\nname = 'b'\n", encoding="utf-8")
    space = configured(tmp_path)

    main(
        [
            "projects",
            "edit",
            "--config",
            str(space / "config.toml"),
            "--projects",
            str(elsewhere),
        ]
    )
    capsys.readouterr()

    assert [path for _, path in opened] == [elsewhere]


def test_the_editor_that_was_chosen_is_named_in_the_output(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A surprising editor must be traceable to the setting that named it."""
    space = configured(tmp_path)

    main(["sources", "edit", "--config", str(space / "config.toml")])
    captured = capsys.readouterr()

    # On stderr, and printed before the launch: a terminal editor would otherwise hold the
    # terminal until the user quit, and the message would arrive after it was any use.
    assert "config.toml" in captured.err
    assert "$EDITOR" in captured.err and "notepad" in captured.err


# --- and the file is not changed --------------------------------------------------------------


def test_the_file_is_byte_identical_afterwards(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-022 — the tool hands the file over; it does not touch it."""
    space = configured(tmp_path)
    before = {
        name: (space / name).read_bytes()
        for name in ("config.toml", "projects.toml", "credentials.toml")
    }

    main(["sources", "edit", "--config", str(space / "config.toml")])
    main(["projects", "edit", "--config", str(space / "config.toml")])
    capsys.readouterr()

    for name, content in before.items():
        assert (space / name).read_bytes() == content, name


def test_a_file_too_broken_to_parse_still_opens(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-024 — and this is the case you most need the command for.

    Every other command in the tool refuses to run against this file. If `edit` refused
    too, the only way to fix a broken configuration would be to find it by hand, which is
    exactly the problem the command exists to solve.
    """
    space = configured(tmp_path)
    broken = "[[sources]\nthis = is not = toml\n"
    (space / "config.toml").write_text(broken, encoding="utf-8")

    code = main(["sources", "edit", "--config", str(space / "config.toml")])
    capsys.readouterr()

    assert code == 0
    assert [path for _, path in opened] == [space / "config.toml"]
    assert (space / "config.toml").read_text(encoding="utf-8") == broken


def test_validate_refuses_the_same_file_that_edit_opens(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The previous test is only interesting if the file really is unreadable."""
    space = configured(tmp_path)
    (space / "config.toml").write_text("[[sources]\nbroken\n", encoding="utf-8")

    code = main(
        [
            "sources",
            "validate",
            "--config",
            str(space / "config.toml"),
            "--store",
            str(tmp_path / "s.db"),
        ]
    )
    capsys.readouterr()

    assert code != 0, "if this passes, the broken-file test proves nothing"


# --- when it cannot open anything --------------------------------------------------------------


def test_a_missing_file_is_not_created_and_init_is_named(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-021 — `edit` opens files; it does not create them. `init` does."""
    space = tmp_path / "empty"
    space.mkdir()

    code = main(["sources", "edit", "--config", str(space / "config.toml")])
    captured = capsys.readouterr()

    assert code != 0
    assert not (space / "config.toml").exists(), "edit must not create the file"
    assert opened == [], "nothing was opened"
    assert "ikwyd init" in captured.out + captured.err


def test_no_editor_at_all_prints_the_path_and_says_so(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-023 — never silently doing nothing.

    A command that appears to succeed and opens no window is the worst outcome here: the
    user waits for an editor that is never coming.
    """
    space = configured(tmp_path)
    def nothing_found(path: Path) -> editor.Command | None:
        return None

    monkeypatch.setattr(editor, "resolve", nothing_found)

    code = main(["sources", "edit", "--config", str(space / "config.toml")])
    captured = capsys.readouterr()
    text = captured.out + captured.err

    assert code != 0
    assert str(space / "config.toml") in text, "the path must be printed so it can be opened"
    assert "EDITOR" in text


# --- T041: nothing interactive is reachable from `ingest` ----------------------------------------


def module_name(path: Path) -> str:
    relative = path.relative_to(SRC).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(["iknowwhatyoudid", *parts])


def path_for(name: str) -> Path | None:
    tail = name.split(".")[1:]
    module = SRC.joinpath(*tail).with_suffix(".py")
    if module.is_file():
        return module
    package = SRC.joinpath(*tail, "__init__.py")
    return package if package.is_file() else None


def imports_of(path: Path) -> set[str]:
    """Every module a file imports, resolved to a dotted name, from the AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # The package this file lives in: `a.b` for both `a/b/c.py` and `a/b/__init__.py`.
    own = module_name(path).split(".")
    package = own if path.name == "__init__.py" else own[:-1]

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                parts = [*base, node.module] if node.module else list(base)
            else:
                parts = [node.module] if node.module else []
            prefix = ".".join(parts)
            if not prefix:
                continue
            found.add(prefix)
            found.update(prefix + "." + alias.name for alias in node.names)
    return found


def reachable_from(start: Path) -> set[str]:
    """The transitive closure of package modules, plus every standard-library name seen."""
    seen: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        name = module_name(current)
        if name in seen:
            continue
        seen.add(name)
        for imported in imports_of(current):
            seen.add(imported)
            if imported.startswith("iknowwhatyoudid"):
                target = path_for(imported)
                if target is not None:
                    queue.append(target)
    return seen


def test_not_reachable_from_ingest() -> None:
    """FR-026 — a scheduled run can never block on a browser or an editor.

    Asserted over the import closure rather than by running `ingest` once, because the
    failure this guards against is a *future* edit: someone adding "open the editor if the
    mapping is missing" to a code path that runs unattended at 3am.
    """
    closure = reachable_from(SRC / "cli" / "sources_commands.py")

    assert "webbrowser" not in closure, "ingest can reach a browser"
    assert "iknowwhatyoudid.cli.editor" not in closure, "ingest can reach an editor"
    assert "iknowwhatyoudid.cli.setup_commands" not in closure


def test_the_closure_walker_would_notice(tmp_path: Path) -> None:
    """The previous test passes trivially if the walker finds nothing. It does not."""
    closure = reachable_from(SRC / "cli" / "sources_commands.py")

    assert "iknowwhatyoudid.config.location" in closure, closure
    assert len(closure) > 20, "the closure is suspiciously small"


def test_the_three_interactive_commands_are_the_ones_we_think() -> None:
    """If a fourth appears, this goes red and FR-026 gets extended to cover it."""
    interactive = set()
    for path in SRC.rglob("*.py"):
        names = imports_of(path)
        if "webbrowser" in names or "iknowwhatyoudid.cli.editor" in names:
            interactive.add(module_name(path))

    assert interactive == {
        "iknowwhatyoudid.cli.mail_commands",  # sources authorise — opens a browser
        "iknowwhatyoudid.cli.setup_commands",  # sources edit, projects edit
    }, interactive


# --- FR-027: there is no way to open the credentials file ------------------------------


def command_paths() -> list[str]:
    """Every command path the CLI accepts, walked from the parser itself."""
    from iknowwhatyoudid.cli.main import build_parser

    found: list[str] = []

    def walk(parser: object, path: str = "") -> None:
        leaf = True
        for action in getattr(parser, "_actions", []):
            choices = getattr(action, "choices", None) or {}
            if hasattr(choices, "items"):
                for name, sub in choices.items():
                    if hasattr(sub, "_actions"):
                        leaf = False
                        walk(sub, (path + " " + name).strip())
        if leaf and path:
            found.append(path)

    walk(build_parser())
    return found


def test_no_command_opens_the_credentials_file() -> None:
    """FR-027, SC-007a — deliberate, not an oversight.

    Handing a file of secrets to whatever `$EDITOR` happens to name is a risk with no
    matching benefit: the value in it has to be pasted from somewhere else anyway. `init`
    prints the path, and that is the whole affordance.
    """
    paths = command_paths()

    assert "sources edit" in paths, "the walker found nothing; the next assertion is empty"
    assert not [path for path in paths if "credential" in path], paths


def test_the_editable_files_are_exactly_the_two(
    tmp_path: Path,
    opened: list[tuple[tuple[str, ...], Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Asserted by running every `edit` there is, not by reading the parser twice."""
    space = configured(tmp_path)
    config = str(space / "config.toml")

    for path in command_paths():
        if path.endswith(" edit"):
            main([*path.split(), "--config", config])
            capsys.readouterr()

    assert sorted({path.name for _, path in opened}) == ["config.toml", "projects.toml"]
