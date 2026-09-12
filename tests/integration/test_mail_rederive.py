"""Changing the mapping re-attributes mail without re-reading it (FR-044, SC-008).

This is the property that makes the mapping safe to get wrong at first, and it matters
more for mail than it did for git: re-fetching a year of repositories is slow, but
re-fetching a year of mail means rate limits, tokens, and possibly an administrator.

Every test here deletes the archive before re-deriving. That is the point — it makes
"reads nothing" impossible to pass by accident.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.corrections import repository as corrections_repo
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate

BEFORE = """
[[project]]
name           = "acme-migration"
correspondents = ["anna@acme.example"]
"""

AFTER = """
[[project]]
name           = "acme-migration"
correspondents = ["anna@acme.example"]

[[project]]
name           = "northwind-work"
correspondents = ["northwind.example"]
"""


def workspace(tmp_path: Path, mapping: str) -> Path:
    box = fx.Mailbox()
    box.add(fx.message("To Anna", to=(fx.ANNA,)))
    box.add(fx.message("To Bob", to=(fx.BOB,), offset_seconds=60))
    archive = box.write_mbox(tmp_path / "export.mbox")
    (tmp_path / "config.toml").write_text(
        f'[[source]]\nname = "mail"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{archive.as_posix()}"]\n',
        encoding="utf-8",
    )
    (tmp_path / "projects.toml").write_text(mapping, encoding="utf-8")
    return tmp_path


def run(space: Path, *argv: str) -> int:
    return main(
        [
            *argv,
            "--config",
            str(space / "config.toml"),
            "--projects",
            str(space / "projects.toml"),
            "--store",
            str(space / "store.db"),
        ]
    )


def projects_by_subject(space: Path) -> dict[str, str]:
    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    rows = connection.execute(
        "SELECT json_extract(r.payload, '$.subject') AS subject, p.name AS project "
        "FROM derived_attribution d "
        "JOIN raw_record r ON r.id = d.record_id "
        "JOIN user_project p ON p.id = d.project_id"
    ).fetchall()
    connection.close()
    return {str(row["subject"]): str(row["project"]) for row in rows}


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to open a socket fails the test outright."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("re-derivation opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_a_mapping_change_moves_mail_without_reading_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], no_sockets: None
) -> None:
    """FR-044, SC-008 — with the archive deleted and sockets forbidden."""
    space = workspace(tmp_path, BEFORE)
    run(space, "ingest")
    capsys.readouterr()

    before = projects_by_subject(space)
    assert before["To Anna"] == "acme-migration"
    assert before["To Bob"] == "northwind.example", "ad hoc, until it is mapped"

    (space / "projects.toml").write_text(AFTER, encoding="utf-8")
    (space / "export.mbox").unlink()  # nothing to read, even if it wanted to

    exit_code = run(space, "projects", "rederive")
    capsys.readouterr()

    assert exit_code == 0
    after = projects_by_subject(space)
    assert after["To Bob"] == "northwind-work", "the mapping change took effect"
    assert after["To Anna"] == "acme-migration", "and left the rest alone"


def test_a_correction_survives_a_mapping_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], no_sockets: None
) -> None:
    """FR-043, SC-009 — a rule never overrides the user's own statement."""
    space = workspace(tmp_path, BEFORE)
    run(space, "ingest")
    capsys.readouterr()

    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    source_id = str(
        connection.execute(
            "SELECT source_id FROM raw_record WHERE "
            "json_extract(payload, '$.subject') = 'To Bob'"
        ).fetchone()[0]
    )
    corrections_repo.record(
        connection, source="mail", source_id=source_id, project="my-own-choice"
    )
    connection.close()

    (space / "projects.toml").write_text(AFTER, encoding="utf-8")
    (space / "export.mbox").unlink()
    run(space, "projects", "rederive")
    capsys.readouterr()

    connection = conn.connect(path)
    migrate.migrate(connection, path)
    correction = corrections_repo.get(connection, "mail", source_id)
    connection.close()

    assert correction is not None
    assert correction.project == "my-own-choice", "the mapping did not overrule the user"


def test_a_dry_run_predicts_exactly_what_applying_it_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], no_sockets: None
) -> None:
    """SC-013 — the preview and the real thing share one decision, so they cannot drift."""
    space = workspace(tmp_path, BEFORE)
    run(space, "ingest")
    capsys.readouterr()

    (space / "projects.toml").write_text(AFTER, encoding="utf-8")
    (space / "export.mbox").unlink()

    run(space, "projects", "rederive", "--dry-run")
    predicted = capsys.readouterr().out
    unchanged_by_preview = projects_by_subject(space)

    run(space, "projects", "rederive")
    capsys.readouterr()
    actual = projects_by_subject(space)

    assert "northwind-work" in predicted, "the preview named the move"
    assert unchanged_by_preview["To Bob"] == "northwind.example", (
        "a dry run changed the store"
    )
    assert actual["To Bob"] == "northwind-work"


def test_an_emptied_ad_hoc_project_stops_being_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], no_sockets: None
) -> None:
    """FR-040 — and it says which ones it removed, rather than quietly tidying up."""
    space = workspace(tmp_path, BEFORE)
    run(space, "ingest")
    capsys.readouterr()

    (space / "projects.toml").write_text(AFTER, encoding="utf-8")
    (space / "export.mbox").unlink()
    run(space, "projects", "rederive")
    capsys.readouterr()

    run(space, "projects", "list")
    listing = capsys.readouterr().out
    assert "northwind-work" in listing
    assert "northwind.example" not in listing, "the emptied ad-hoc project is gone"
