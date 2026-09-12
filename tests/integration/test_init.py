"""`ikwyd init` — creating a configuration, and never touching one that exists.

US1 and US2 together, because they are two halves of one command. US1 is the convenience;
US2 is the guarantee that makes the convenience safe to accept, and it is the reason
[`0005` was allowed to narrow](../../specs/0005-config-bootstrap/contracts/amendments.md)
what `0002` and `0003` forbade absolutely.

No test here writes to the real configuration directory. One of them asserts that.
"""

from __future__ import annotations

import hashlib
import socket
import time
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import editor
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.config.bootstrap import Outcome, create_all
from iknowwhatyoudid.protection import permissions

KNOWN_SECRET = "a-real-token-the-user-would-hate-to-lose"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths_in(space: Path) -> dict[str, Path]:
    return {
        "config": space / "config.toml",
        "projects": space / "projects.toml",
        "credentials": space / "credentials.toml",
    }


def run_init(space: Path, *extra: str) -> int:
    return main(["init", "--config", str(space / "config.toml"), *extra])


# --- US1: a fresh directory ------------------------------------------------------------


def test_all_three_files_appear_in_an_empty_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-005 — one command, and the files are where the tool looks for them."""
    space = tmp_path / "config-dir"
    assert not space.exists()

    exit_code = run_init(space)
    capsys.readouterr()

    assert exit_code == 0
    for name, path in paths_in(space).items():
        assert path.is_file(), name
        assert path.read_text(encoding="utf-8").strip(), f"{name} is empty"


def test_the_directory_is_created_and_nothing_outside_it_is_touched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-007."""
    space = tmp_path / "nested" / "config-dir"
    sibling = tmp_path / "untouched.txt"
    sibling.write_text("leave me", encoding="utf-8")

    run_init(space)
    capsys.readouterr()

    assert space.is_dir()
    assert sibling.read_text(encoding="utf-8") == "leave me"
    assert {p.name for p in space.iterdir()} == {
        "config.toml",
        "projects.toml",
        "credentials.toml",
    }


def test_the_created_files_are_exactly_the_shipped_templates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-013 — no substitution, no generation, no cleverness."""
    from iknowwhatyoudid.config.bootstrap import template_text

    space = tmp_path / "c"
    run_init(space)
    capsys.readouterr()

    assert paths_in(space)["config"].read_text(encoding="utf-8") == template_text("config.toml")
    assert paths_in(space)["projects"].read_text(encoding="utf-8") == template_text("projects.toml")
    assert paths_in(space)["credentials"].read_text(encoding="utf-8") == template_text(
        "credentials.toml.template"
    )


def test_a_freshly_created_configuration_validates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-005 — with **zero errors**.

    `0004` shipped an `examples/config.toml` with uncommented mail sources that could not
    validate, and no test caught it; it was found by running the quickstart by hand. `init`
    makes this file the first thing a new user sees, so it gets a test.
    """
    space = tmp_path / "c"
    run_init(space)
    capsys.readouterr()

    exit_code = main(
        ["sources", "validate", "--config", str(space / "config.toml"),
         "--store", str(tmp_path / "s.db")]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "0 errors" in out, out


def test_a_freshly_created_mapping_validates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    space = tmp_path / "c"
    run_init(space)
    capsys.readouterr()

    exit_code = main(
        ["projects", "validate", "--config", str(space / "config.toml"),
         "--projects", str(space / "projects.toml"), "--store", str(tmp_path / "s.db")]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "0 errors" in out, out


def test_the_tool_then_finds_them_without_being_told_where(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-006 — `--config` points at the directory, and the siblings follow."""
    space = tmp_path / "c"
    run_init(space)
    capsys.readouterr()

    main(["projects", "validate", "--config", str(space / "config.toml"),
          "--store", str(tmp_path / "s.db")])
    out = capsys.readouterr().out
    assert "projects.toml" in out or "0 errors" in out


# --- US1: the credentials file ------------------------------------------------------------


def test_the_credentials_file_is_readable_by_its_owner_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-005a — asked of the operating system, not trusted from the write."""
    space = tmp_path / "c"
    run_init(space)
    capsys.readouterr()

    report = permissions.check(paths_in(space)["credentials"])
    assert report.status is not permissions.PermissionStatus.OTHERS_CAN_READ, report.detail


def test_permissions_are_applied_before_any_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-015 — the window is the whole point, and the end state cannot show it.

    Write-then-restrict and restrict-then-write end identically. What differs is whether
    there was an instant in which a file intended to hold secrets was readable by anyone,
    so the *order* is what gets asserted.
    """
    order: list[str] = []
    real_restrict = permissions.restrict_to_owner

    def spy_restrict(path: Path) -> None:
        order.append(f"restrict:{path.name}")
        real_restrict(path)

    # Patched on the `permissions` module itself, which `bootstrap` holds a reference to,
    # so the spy is seen at the call site without reaching through another module.
    monkeypatch.setattr(permissions, "restrict_to_owner", spy_restrict)

    original_write = Path.write_text

    def spy_write(self: Path, *args: object, **kwargs: object) -> int:
        order.append(f"write:{self.name}")
        return original_write(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", spy_write)

    space = tmp_path / "c"
    create_all(space / "config.toml")

    for name in ("config.toml", "projects.toml", "credentials.toml"):
        assert order.index(f"restrict:{name}") < order.index(f"write:{name}"), (
            f"{name} was written before its permissions were restricted"
        )


def test_nothing_resembling_a_credential_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-005b — nothing is prompted for, generated, or invented."""
    space = tmp_path / "c"
    run_init(space)
    out = capsys.readouterr().out

    text = paths_in(space)["credentials"].read_text(encoding="utf-8")
    assert "REPLACE" in text, "it is a placeholder, not a value"
    assert "token" not in out.lower() or "REPLACE" in out


# --- US1: reporting -----------------------------------------------------------------------


def test_each_file_is_reported_with_its_outcome_and_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-011."""
    space = tmp_path / "c"
    run_init(space)
    out = capsys.readouterr().out

    assert out.count("created") >= 3
    assert "config.toml" in out and "projects.toml" in out and "credentials.toml" in out
    assert str(space) in out, "the directory is named, so the user knows where to look"


def test_the_output_says_what_to_do_next(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-018 — a command that leaves you wondering has not finished."""
    space = tmp_path / "c"
    run_init(space)
    out = capsys.readouterr().out

    assert "validate" in out
    assert "edit" in out


def test_the_json_form_reports_per_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    space = tmp_path / "c"
    main(["--json", "init", "--config", str(space / "config.toml")])
    payload = json.loads(capsys.readouterr().out)

    files = payload["data"]["files"]
    assert {f["name"] for f in files} == {"config.toml", "projects.toml", "credentials.toml"}
    assert all(f["outcome"] == "created" for f in files)
    assert payload["data"]["created"] == 3
    credentials = next(f for f in files if f["name"] == "credentials.toml")
    assert credentials["owner_only"] is True


# --- US2: never losing what was written -------------------------------------------------------


def test_existing_files_are_byte_identical_afterwards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """**The guarantee the requirement amendment rests on** (FR-002, SC-002)."""
    space = tmp_path / "c"
    space.mkdir()
    for name, path in paths_in(space).items():
        path.write_text(f"# mine: {name}\nkeep = true\n", encoding="utf-8")
    before = {name: digest(path) for name, path in paths_in(space).items()}

    exit_code = run_init(space)
    capsys.readouterr()

    assert exit_code == 0, "finding everything already there is not a failure"
    after = {name: digest(path) for name, path in paths_in(space).items()}
    assert after == before


def test_an_existing_credentials_file_holding_a_secret_is_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-016 — the highest-stakes case.

    Overwriting `config.toml` costs a preference. Overwriting this costs a secret the user
    cannot recover from a template.
    """
    space = tmp_path / "c"
    space.mkdir()
    credentials = paths_in(space)["credentials"]
    credentials.write_text(
        f'[credential.work]\ntoken = "{KNOWN_SECRET}"\n', encoding="utf-8"
    )
    before = digest(credentials)

    run_init(space)
    capsys.readouterr()

    assert digest(credentials) == before
    assert KNOWN_SECRET in credentials.read_text(encoding="utf-8")


def test_no_option_exists_that_would_overwrite() -> None:
    """FR-009 — what stops the narrowing quietly becoming a relaxation.

    Walks the parser rather than trusting the documentation: a `--force` added later would
    make [the amendment](../../specs/0005-config-bootstrap/contracts/amendments.md) a fig
    leaf, and this is the assertion that would catch it.
    """
    from iknowwhatyoudid.cli.main import build_parser

    parser = build_parser()
    dangerous = {"--force", "-f", "--overwrite", "--replace", "--clobber", "--reset"}
    found: list[str] = []

    def walk(p: object, path: str = "") -> None:
        for action in getattr(p, "_actions", []):
            for option in getattr(action, "option_strings", []):
                if option in dangerous:
                    found.append(f"{path} {option}")
            choices = getattr(action, "choices", None) or {}
            if hasattr(choices, "items"):
                for name, sub in choices.items():
                    if hasattr(sub, "_actions"):
                        walk(sub, f"{path} {name}")

    walk(parser)
    assert not found, f"an overwriting option exists: {found}"


def test_one_present_and_two_absent_creates_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-010 — each file decided on its own; there is no all-or-nothing."""
    space = tmp_path / "c"
    space.mkdir()
    paths_in(space)["config"].write_text("# mine\n", encoding="utf-8")
    before = digest(paths_in(space)["config"])

    run_init(space)
    out = capsys.readouterr().out

    assert digest(paths_in(space)["config"]) == before
    assert paths_in(space)["projects"].is_file()
    assert paths_in(space)["credentials"].is_file()
    assert "left alone" in out and "created" in out


def test_running_it_twice_changes_nothing_the_second_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-003 — and exits zero, or `ikwyd init && ikwyd sources validate` would break."""
    space = tmp_path / "c"
    run_init(space)
    capsys.readouterr()
    before = {name: digest(path) for name, path in paths_in(space).items()}

    exit_code = run_init(space)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert {name: digest(path) for name, path in paths_in(space).items()} == before
    assert "0 created" in out


def test_an_existing_file_is_never_opened_for_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked *before* the file is touched, not by catching an error afterwards.

    The difference matters: an exclusive-create that fails has already reached for the
    file, and a future refactor could turn that into a truncate.
    """
    space = tmp_path / "c"
    space.mkdir()
    target = paths_in(space)["config"]
    target.write_text("# mine\n", encoding="utf-8")

    opened: list[str] = []
    original = Path.write_text

    def spy(self: Path, *args: object, **kwargs: object) -> int:
        opened.append(str(self))
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", spy)
    results = create_all(target)

    assert str(target) not in opened
    assert results[0].outcome is Outcome.LEFT_ALONE


# --- T044/T045: the real directories, and the network ----------------------------------


def snapshot(directory: Path) -> dict[str, tuple[int, float]]:
    """Every file under *directory*, by size and modification time.

    Contents are deliberately **not** read: this runs against the developer's own
    configuration directory, which may hold real credentials.
    """
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(directory)): (path.stat().st_size, path.stat().st_mtime)
        for path in directory.rglob("*")
        if path.is_file()
    }


def every_command(space: Path, store: Path) -> list[list[str]]:
    """Every command this feature adds, each pointed at a temporary directory."""
    config = str(space / "config.toml")
    return [
        ["init", "--config", config],
        ["init", "--config", config],  # twice: the second run is the no-op path
        ["sources", "edit", "--config", config],
        ["projects", "edit", "--config", config],
    ]


def test_isolation_from_the_real_configuration_and_data_directories(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing in the directories the user actually uses is touched.

    `0001` wrote its log to the real data directory once despite `--store`, which no test
    noticed because every test passed `--store` and looked only there. The same mistake is
    available here — `init` creates files, and a default that leaked through would create
    them in the user's own configuration directory during the test run.
    """
    from iknowwhatyoudid.config.location import config_dir
    from iknowwhatyoudid.store.location import data_dir

    real_config = config_dir()
    real_data = data_dir()
    before = (snapshot(real_config), snapshot(real_data))
    existed = (real_config.exists(), real_data.exists())

    space = tmp_path / "c"
    store = tmp_path / "store.db"
    monkeypatch.setattr(editor, "launch", lambda command, path: editor.Outcome(exit_code=0))
    monkeypatch.setenv("EDITOR", "notepad")

    for argv in every_command(space, store):
        main(argv)
        capsys.readouterr()

    assert (snapshot(real_config), snapshot(real_data)) == before
    assert (real_config.exists(), real_data.exists()) == existed, (
        "a directory the user was not using was created"
    )


def test_offline_and_without_a_store(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-028, FR-029 — this feature opens neither a socket nor the store.

    Both are asserted in one test because they are the same claim from two sides: these
    commands are about files on disk, and a user who has not configured anything yet must
    be able to run them on a train.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a command in this feature opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(editor, "launch", lambda command, path: editor.Outcome(exit_code=0))
    monkeypatch.setenv("EDITOR", "notepad")

    space = tmp_path / "c"
    store = tmp_path / "definitely-absent.db"

    for argv in every_command(space, store):
        assert main(argv) == 0, argv
        capsys.readouterr()

    assert not store.exists(), "no command in this feature may create a store"
    assert not list(tmp_path.glob("*.db")), "no store was created anywhere"


# --- SC-009: failures name the path, and leave nothing behind --------------------------


def test_a_failed_write_leaves_no_file_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-009 — half a file is worse than none.

    An empty `config.toml` looks like a configuration: `init` would report it as left
    alone from then on, and the user would never be told why nothing works. The failure
    has to undo itself.
    """
    def refuse(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", refuse)

    space = tmp_path / "c"
    results = create_all(space / "config.toml")

    assert all(r.outcome is Outcome.FAILED for r in results), results
    for result in results:
        assert not result.path.exists(), f"{result.name} was left behind"


def test_a_failed_write_says_which_file_and_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-009 — the message names the path and the reason, and the exit code is non-zero."""

    def refuse(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "write_text", refuse)

    space = tmp_path / "c"
    exit_code = run_init(space)
    captured = capsys.readouterr()
    text = captured.out + captured.err

    assert exit_code != 0
    assert "config.toml" in text
    assert "Permission denied" in text


def test_a_directory_that_cannot_be_created_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-009 — the other failure that is not the user's fault and must not be a traceback."""
    original = Path.mkdir

    def refuse(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", refuse)

    space = tmp_path / "unwritable" / "c"
    exit_code = run_init(space)
    captured = capsys.readouterr()
    text = captured.out + captured.err

    assert exit_code != 0
    assert "directory" in text.lower()
    assert not space.exists()
    monkeypatch.setattr(Path, "mkdir", original)


# --- SC-012: fast enough that nobody wonders whether it ran ------------------------------


def test_init_completes_in_well_under_a_second(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-012.

    Generous by two orders of magnitude on purpose: the point is to catch a future `init`
    that opens the store, contacts something, or scans a directory tree, not to police
    milliseconds on a busy machine.
    """
    space = tmp_path / "c"

    started = time.perf_counter()
    run_init(space)
    elapsed = time.perf_counter() - started
    capsys.readouterr()

    assert elapsed < 1.0, f"init took {elapsed:.2f}s"
