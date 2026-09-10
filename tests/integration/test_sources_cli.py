"""The sources CLI contract: exit codes, streams, and --json (FR-019, Principle VI)."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

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
    assert len(payload["data"]["sources"]) == 4
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
    assert reachable == {"Microsoft Graph", "Hey IMAP"}


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


def test_no_command_ever_writes_the_configuration_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-002, asserted across the whole surface rather than one command."""
    config = tmp_path / "config.toml"
    shutil.copy(FIXTURES / "valid.toml", config)
    before = config.read_bytes()
    store = str(tmp_path / "store.db")

    for argv in (
        ["sources", "list"],
        ["sources", "validate"],
        ["sources", "destinations"],
        ["sources", "check", "recorded-day"],
        ["sources", "kinds"],
        ["ingest"],
    ):
        main([*argv, "--config", str(config), "--store", store])
        capsys.readouterr()

    assert config.read_bytes() == before
