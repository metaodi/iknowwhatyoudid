"""Nothing is written where it was not asked to write (FR-008, FR-019, SC-015).

Three properties, all of them the kind that quietly stop being true:

* the real configuration and data directories are untouched by the test suite;
* `tokens.toml` is the **only** thing this feature writes outside the data directory, and
  it is created readable by the owner alone;
* everything already ingested answers with no network at all.

`0001` had to be corrected once for writing its log to the real data directory even when
given `--store`, which is why the first of these is asserted rather than assumed.
"""

from __future__ import annotations

import socket
import sqlite3
from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from iknowwhatyoudid.cli.main import main


def fingerprint(path: Path) -> tuple[bool, float | None, int | None]:
    try:
        stat = path.stat()
    except OSError:
        return (False, None, None)
    return (True, stat.st_mtime, stat.st_size)


def workspace(tmp_path: Path) -> Path:
    archive = fx.attribution_cases().write_mbox(tmp_path / "export.mbox")
    (tmp_path / "config.toml").write_text(
        f'[[source]]\nname = "mail"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{archive.as_posix()}"]\n',
        encoding="utf-8",
    )
    (tmp_path / "projects.toml").write_text(
        '[[project]]\nname = "acme"\ncorrespondents = ["acme.example"]\n',
        encoding="utf-8",
    )
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


# --- the real directories ---------------------------------------------------------------


def test_no_command_touches_the_real_configuration_or_data_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`0001` wrote its log to the real data directory once, despite `--store`.

    A test suite that quietly edits the machine it runs on is exactly what Principle I
    forbids, and it is invisible until someone looks.
    """
    from iknowwhatyoudid.auth import tokens as token_store
    from iknowwhatyoudid.config.location import default_config_path
    from iknowwhatyoudid.store.location import default_log_path, default_store_path

    watched = {
        "config": default_config_path(),
        "config dir": default_config_path().parent,
        "store": default_store_path(),
        "data dir": default_store_path().parent,
        "log": default_log_path(),
        "tokens": token_store.path_for(default_config_path()),
    }
    before = {name: fingerprint(path) for name, path in watched.items()}

    space = workspace(tmp_path)
    # `sources validate` takes no `--projects`, so it is run on its own.
    main(
        ["sources", "validate", "--config", str(space / "config.toml"),
         "--store", str(space / "store.db")]
    )
    for command in (
        ["ingest"],
        ["ingest", "--sweep"],
        ["projects", "list"],
        ["projects", "rederive"],
    ):
        run(space, *command)
    main(["mail", "list", "--store", str(space / "store.db")])
    main(["mail", "correspondents", "--store", str(space / "store.db")])
    capsys.readouterr()

    after = {name: fingerprint(path) for name, path in watched.items()}
    changed = [name for name in watched if before[name] != after[name]]
    assert not changed, f"the run touched the real {', '.join(changed)}"
    assert (space / "store.db").exists(), "it did write where it was told to"


def test_the_archive_itself_is_never_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An export belongs to the user. Reading it must not touch it."""
    space = workspace(tmp_path)
    archive = space / "export.mbox"
    before = fingerprint(archive)
    digest_before = archive.read_bytes()

    run(space, "ingest")
    run(space, "ingest", "--sweep")
    capsys.readouterr()

    assert fingerprint(archive) == before
    assert archive.read_bytes() == digest_before


# --- the one file this feature does write ------------------------------------------------


def test_tokens_toml_is_the_only_new_file_outside_the_store(tmp_path: Path) -> None:
    """FR-008 — called out because the constitution requires a PR to flag exactly this."""
    from iknowwhatyoudid.auth import tokens as token_store

    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    before = {p.name for p in tmp_path.iterdir()}

    token_store.save(
        token_store.path_for(config),
        token_store.StoredToken(account="work", refresh_token="secret"),
    )

    added = {p.name for p in tmp_path.iterdir()} - before
    assert added == {"tokens.toml"}


def test_a_written_token_file_is_not_readable_by_others(tmp_path: Path) -> None:
    from iknowwhatyoudid.auth import tokens as token_store
    from iknowwhatyoudid.protection import permissions

    path = tmp_path / "tokens.toml"
    token_store.save(path, token_store.StoredToken(account="w", refresh_token="s"))

    report = permissions.check(path)
    assert report.status is not permissions.PermissionStatus.OTHERS_CAN_READ


def test_the_token_file_is_ignored_by_git() -> None:
    """A refresh token in a commit is the worst outcome this feature can produce."""
    root = Path(__file__).resolve().parents[2]
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    assert "tokens.toml" in ignored
    assert "credentials.toml" in ignored


# --- offline ----------------------------------------------------------------------------------


def test_everything_already_ingested_answers_with_no_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-051, SC-015 — the promise that the store is the system of record locally."""
    space = workspace(tmp_path)
    run(space, "ingest")
    capsys.readouterr()

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a query opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    assert run(space, "projects", "list") == 0
    assert run(space, "projects", "rederive") == 0
    assert main(["mail", "list", "--store", str(space / "store.db")]) == 0
    assert main(["mail", "correspondents", "--store", str(space / "store.db")]) == 0
    assert main(["records", "query", "--store", str(space / "store.db")]) == 0
    capsys.readouterr()


def test_the_sentinels_never_reach_the_store_or_the_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-004, end to end and across every column of every table."""
    space = workspace(tmp_path)
    box = fx.Mailbox()
    box.add(fx.message("With everything", to=(fx.ANNA,), with_attachment=True))
    box.write_mbox(space / "export.mbox")

    run(space, "ingest")
    capsys.readouterr()

    from iknowwhatyoudid.store.location import log_path_for

    hits = fx.find_sentinels(space / "store.db", log_path_for(space / "store.db"))
    assert hits == [], hits


def test_the_store_holds_no_duration_for_any_mail_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-005 — a message is a point in time, and hours are a later feature's job."""
    space = workspace(tmp_path)
    run(space, "ingest")
    capsys.readouterr()

    connection = sqlite3.connect(space / "store.db")
    durations = connection.execute(
        "SELECT count(*) FROM raw_record "
        "WHERE json_extract(payload, '$.kind') = 'mail_sent' "
        "AND duration_us IS NOT NULL"
    ).fetchone()[0]
    connection.close()
    assert durations == 0
