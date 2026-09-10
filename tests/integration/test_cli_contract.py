"""The CLI contract: exit codes, stream separation, and --json (Principle VI)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.store import schema


def run(
    capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_store_info_creates_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store.db"
    code, out, _ = run(capsys, "store", "info", "--store", str(store))

    assert code == 0
    assert str(store) in out
    assert f"schema v{schema.SCHEMA_VERSION}" in out
    assert store.exists()


def test_json_parses_standalone_and_carries_the_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "store", "info", "--store", str(tmp_path / "s.db"), "--json")

    assert code == 0
    payload = json.loads(out)
    assert payload["schema"] == "iknowwhatyoudid/v1"
    assert payload["command"] == "store.info"
    assert payload["ok"] is True
    assert "data" in payload and "findings" in payload


def test_global_flags_work_before_or_after_the_subcommand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = str(tmp_path / "s.db")
    before = run(capsys, "--store", store, "--json", "store", "info")[1]
    after = run(capsys, "store", "info", "--store", store, "--json")[1]

    assert json.loads(before)["command"] == json.loads(after)["command"]


def test_a_newer_store_is_refused_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-022 — a refusal, not a failed operation."""
    from iknowwhatyoudid.store import connection as conn
    from iknowwhatyoudid.store import migrate

    store = tmp_path / "store.db"
    connection = conn.connect(store)
    migrate.migrate(connection, store)
    conn.set_user_version(connection, 99)
    connection.close()

    code, _, err = run(capsys, "store", "info", "--store", str(store))
    assert code == 2
    assert "99" in err or "newer" in err


def test_usage_errors_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["store", "nonsense"])
    assert caught.value.code == 2


def test_diagnostics_never_reach_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """So that `| jq` always works."""
    code, out, _ = run(
        capsys, "corrections", "import", "no-such-file.jsonl", "--store", str(tmp_path / "s.db")
    )
    assert code != 0
    assert out.strip() == ""


def test_records_query_and_corrections_round_trip_through_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from conftest import make_batch, make_record
    from iknowwhatyoudid.corrections import repository as corrections_repo
    from iknowwhatyoudid.records import repository as repo
    from iknowwhatyoudid.store import connection as conn
    from iknowwhatyoudid.store import migrate

    store = tmp_path / "store.db"
    connection = conn.connect(store)
    migrate.migrate(connection, store)
    repo.ingest(connection, make_batch("mail", records=[make_record("a", title="hi")]))
    corrections_repo.record(
        connection, source="mail", source_id="a", project="acme", made_at_utc=1
    )
    connection.close()

    code, out, _ = run(capsys, "records", "query", "--store", str(store), "--json")
    assert code == 0
    assert json.loads(out)["data"]["count"] == 1

    exported = tmp_path / "corrections.jsonl"
    code, _, _ = run(
        capsys, "corrections", "export", "--store", str(store), "--out", str(exported)
    )
    assert code == 0
    assert exported.read_text(encoding="utf-8").strip()

    code, out, _ = run(
        capsys, "corrections", "import", str(exported), "--store", str(store), "--json"
    )
    assert code == 0
    assert json.loads(out)["data"]["declined"] == 1, "identical made_at keeps the local one"


def test_store_protection_never_claims_unverified_encryption_is_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-031, SC-012."""
    code, out, _ = run(
        capsys, "store", "protection", "--store", str(tmp_path / "s.db"), "--json"
    )
    assert code == 0
    data = json.loads(out)["data"]
    assert data["permissions"]["status"] in {"OWNER_ONLY", "OTHERS_CAN_READ", "UNVERIFIED"}
    assert data["disk_encryption"]["status"] in {"ON", "OFF", "UNVERIFIED"}
    if data["disk_encryption"]["status"] == "UNVERIFIED":
        assert data["disk_encryption"]["how_to_check"], "a dead end must come with an action"
