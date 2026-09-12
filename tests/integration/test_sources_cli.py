"""The sources CLI contract: exit codes, streams, and --json (FR-019, Principle VI)."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import editor
from iknowwhatyoudid.cli.main import main

FIXTURES = Path("tests/fixtures/configs")


def run(
    capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def base(tmp_path: Path, config: str = "valid.toml") -> list[str]:
    return ["--config", str(FIXTURES / config), "--store", str(tmp_path / "store.db")]


def test_sources_list_reports_every_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "sources", "list", *base(tmp_path))
    assert code == 0
    for name in ("work-repos", "work-mail", "personal-mail", "recorded-day"):
        assert name in out


def test_json_parses_standalone_with_the_shared_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "sources", "list", *base(tmp_path), "--json")
    payload = json.loads(out)

    assert code == 0
    assert payload["schema"] == "iknowwhatyoudid/v1"
    assert payload["command"] == "sources.list"
    assert len(payload["data"]["sources"]) == 5
    assert "findings" in payload


def test_validate_exits_1_on_blocking_findings_and_keys_on_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(
        capsys, "sources", "validate", *base(tmp_path, "many-faults.toml"), "--json"
    )
    payload = json.loads(out)

    assert code == 1
    codes = {finding["code"] for finding in payload["findings"]}
    assert "duplicate-source-name" in codes
    assert "unknown-kind" in codes


def test_a_broken_file_exits_2_not_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A broken file and a valid file describing a broken source differ."""
    code, out, err = run(capsys, "sources", "validate", *base(tmp_path, "broken.toml"))
    assert code == 2
    assert out.strip() == "", "diagnostics belong on stderr"
    assert "TOML" in err or "line" in err


def test_a_missing_file_reports_its_path_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.toml"
    code, out, err = run(
        capsys, "sources", "list", "--config", str(missing), "--store", str(tmp_path / "s.db")
    )
    assert code != 0
    assert str(missing) in err
    assert out.strip() == ""


def test_sources_kinds_works_without_any_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Asking what can be configured must work before anything is configured."""
    code, out, _ = run(
        capsys,
        "sources",
        "kinds",
        "--config",
        str(tmp_path / "absent.toml"),
        "--store",
        str(tmp_path / "s.db"),
    )
    assert code == 0
    assert "git.local" in out
    assert "fixture" in out


def test_destinations_lists_the_whole_egress_surface(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-010 — inspectable before anything is contacted."""
    code, out, _ = run(capsys, "sources", "destinations", *base(tmp_path), "--json")
    payload = json.loads(out)

    assert code == 0
    reachable = {
        row["destination"]
        for row in payload["data"]["destinations"]
        if row["destination"] != "none (local only)"
    }
    # `0004` replaced the placeholder destinations with the real ones, and corrected
    # "Hey IMAP" — Hey has no IMAP, and the kind is read through its official CLI.
    assert reachable == {
        "graph.microsoft.com",
        "login.microsoftonline.com",
        "gmail.googleapis.com",
        "oauth2.googleapis.com",
    }
    assert not any("IMAP" in destination for destination in reachable), (
        "a destination that does not exist was being advertised"
    )


def test_listing_destinations_contacts_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("listing destinations opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert run(capsys, "sources", "destinations", *base(tmp_path))[0] == 0


def test_ingest_exits_non_zero_when_a_source_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-044."""
    code, out, _ = run(capsys, "ingest", *base(tmp_path, "one-failing.toml"), "--json")
    payload = json.loads(out)

    assert code == 1
    outcomes = {o["source"]: o for o in payload["data"]["outcomes"]}
    assert outcomes["good"]["result"] == "succeeded"
    assert outcomes["bad"]["result"] == "failed"
    assert outcomes["bad"]["failure"] == "credential"


def test_ingest_defaults_to_incremental(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The safe direction: nothing is withdrawn unless a sweep is asked for."""
    _, out, _ = run(capsys, "ingest", *base(tmp_path), "--json")
    assert json.loads(out)["data"]["mode"] == "incremental"


def test_ingest_records_reach_the_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = str(tmp_path / "store.db")
    run(capsys, "ingest", "--config", str(FIXTURES / "valid.toml"), "--store", store)

    _, out, _ = run(capsys, "records", "query", "--store", store, "--json")
    assert json.loads(out)["data"]["count"] == 2


def test_check_names_the_destination_before_contacting_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-045."""
    code, out, _ = run(
        capsys, "sources", "check", "recorded-day", *base(tmp_path), "--live"
    )
    assert code == 0
    assert "about to contact" in out


def test_check_on_an_unknown_source_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run(capsys, "sources", "check", "nobody", *base(tmp_path))
    assert code == 2
    assert "nobody" in err


def test_global_flags_work_before_or_after_the_subcommand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = str(tmp_path / "store.db")
    config = str(FIXTURES / "valid.toml")
    after = run(capsys, "sources", "list", "--config", config, "--store", store, "--json")[1]
    before = run(capsys, "--json", "--store", store, "sources", "list", "--config", config)[1]

    assert json.loads(before)["command"] == json.loads(after)["command"]


def test_nothing_the_user_wrote_is_ever_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-004, asserted across the whole surface rather than one command.

    `0002` FR-002 and `0003` FR-029 said the tool never writes these files at all. `0005`
    [narrowed that](../../specs/0005-config-bootstrap/contracts/amendments.md) so `init`
    may create one that is absent — and this test is what keeps the narrowing from
    quietly becoming a relaxation. The property it asserts is the one those requirements
    were protecting all along: **a file the user wrote comes back exactly as they left
    it**, byte for byte, comments and ordering intact.

    So all three files are present before anything runs, and all three are compared
    afterwards — including `credentials.toml`, which no command may open and none may
    replace.
    """
    config = tmp_path / "config.toml"
    shutil.copy(FIXTURES / "valid.toml", config)
    projects = tmp_path / "projects.toml"
    projects.write_text(
        "# a comment the user wrote\n[[projects]]\nname = 'Something'\n", encoding="utf-8"
    )
    credentials = tmp_path / "credentials.toml"
    credentials.write_text("# not a real secret\ntoken = 'left-alone'\n", encoding="utf-8")

    before = {path: path.read_bytes() for path in (config, projects, credentials)}
    store = str(tmp_path / "store.db")

    # `edit` hands the file to an editor; substituted, so the suite spawns nothing.
    monkeypatch.setattr(editor, "launch", lambda command, path: editor.Outcome(exit_code=0))
    monkeypatch.setenv("EDITOR", "notepad")

    for argv in (
        ["sources", "list"],
        ["sources", "validate"],
        ["sources", "destinations"],
        ["sources", "check", "recorded-day"],
        ["sources", "kinds"],
        ["ingest"],
        ["init"],  # every file already exists: it must leave all three alone
        ["sources", "edit"],
        ["projects", "edit"],
        ["projects", "list"],
        ["projects", "validate"],
    ):
        main([*argv, "--config", str(config), "--store", store])
        capsys.readouterr()

    for path, content in before.items():
        assert path.read_bytes() == content, path.name
