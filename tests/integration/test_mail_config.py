"""Configuring a mail account, and being told what is wrong offline (FR-001 to FR-007).

`sources validate` contacts nothing and is run constantly, so every check here is a
question about the text of the file. Every fault is reported in one pass: a user fixing
a configuration one error per run is a user who gives up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.config import loader, validate
from iknowwhatyoudid.mail import reader as mail_reader


def write(space: Path, body: str) -> Path:
    path = space / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def findings_for(space: Path, body: str) -> list[str]:
    configuration, file_findings = loader.load(write(space, body))
    report = validate.validate(configuration, file_findings)
    return [f.code for f in report.findings]


ARCHIVE = '[[source]]\nname = "a"\nkind = "mail.mbox"\n'


# --- addresses ---------------------------------------------------------------------


def test_an_account_with_no_addresses_is_blocked(tmp_path: Path) -> None:
    """FR-003 — without them the connector cannot tell your mail from anyone else's.

    Blocking rather than warning: a source that would record nothing, silently, is the
    failure this project cares about most.
    """
    codes = findings_for(tmp_path, ARCHIVE + 'paths = ["x.mbox"]\n')
    assert mail_reader.MISSING_ADDRESSES in codes


def test_a_malformed_address_is_blocked(tmp_path: Path) -> None:
    """It can never match, so it is a typo rather than an intention."""
    codes = findings_for(
        tmp_path, ARCHIVE + 'addresses = ["not-an-address"]\npaths = ["x.mbox"]\n'
    )
    assert mail_reader.MALFORMED_ADDRESS in codes


def test_a_well_formed_address_passes(tmp_path: Path) -> None:
    codes = findings_for(
        tmp_path, ARCHIVE + f'addresses = ["{fx.ME}"]\npaths = ["x.mbox"]\n'
    )
    assert mail_reader.MALFORMED_ADDRESS not in codes
    assert mail_reader.MISSING_ADDRESSES not in codes


# --- archive paths ------------------------------------------------------------------


def test_an_archive_without_paths_is_blocked(tmp_path: Path) -> None:
    codes = findings_for(tmp_path, ARCHIVE + f'addresses = ["{fx.ME}"]\n')
    assert mail_reader.MISSING_PATHS in codes


def test_paths_on_a_non_archive_kind_is_blocked(tmp_path: Path) -> None:
    """`paths` is declared by `mail.mbox` alone, so elsewhere it is a misunderstanding."""
    codes = findings_for(
        tmp_path,
        '[[source]]\nname = "g"\nkind = "mail.gmail"\ncredential = "c"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["x.mbox"]\n',
    )
    assert any("unknown" in code or "setting" in code for code in codes), codes


# --- every fault in one pass ---------------------------------------------------------


def test_every_fault_is_reported_in_one_run(tmp_path: Path) -> None:
    codes = findings_for(tmp_path, ARCHIVE + 'addresses = ["nope"]\n')
    assert mail_reader.MALFORMED_ADDRESS in codes
    assert mail_reader.MISSING_PATHS in codes


# --- validation contacts nothing -----------------------------------------------------


def test_validation_does_not_read_the_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-006 — `sources validate` is fast and offline, and stays that way.

    It names a file it never opens. Reading the archive is `ingest`'s job, and a
    validation that walked a year of mail would stop being something people run.
    """
    absent = tmp_path / "never-created.mbox"
    write(
        tmp_path,
        ARCHIVE + f'addresses = ["{fx.ME}"]\npaths = ["{absent.as_posix()}"]\n',
    )
    exit_code = main(
        ["sources", "validate", "--config", str(tmp_path / "config.toml"),
         "--store", str(tmp_path / "s.db")]
    )
    capsys.readouterr()

    assert exit_code == 0, "a missing archive is not a configuration fault"
    assert not absent.exists()


# --- the corrected Hey declaration ---------------------------------------------------


def test_the_hey_kind_no_longer_claims_imap() -> None:
    """`0002` shipped a declaration that was factually wrong.

    Hey offers no IMAP, no POP and no third-party API. Saying so in a shipped kind
    promised reading that could never arrive; the correction is part of this feature.
    """
    from iknowwhatyoudid.kinds import mail as kinds

    declared = " ".join(kinds.HEY.required_access) + " ".join(kinds.HEY.destinations)
    assert "IMAP" not in declared
    assert kinds.HEY.credential_required is False, "an export needs no credential"


def test_the_hey_kind_reads_an_export(tmp_path: Path) -> None:
    """Research R1, verified: the CLI cannot supply what a record needs.

    `hey search --json` returns no recipients and no `Message-ID`, so correspondent
    attribution and cross-provider identity are both impossible from it. An export gives
    real headers, and Hey mail then obeys every rule unchanged.
    """
    from iknowwhatyoudid.kinds import mail as kinds

    assert kinds.HEY.destinations == (), "nothing is contacted"
    assert kinds.HEY.credential_required is False
    assert {s.key for s in kinds.HEY.settings} == {"addresses", "paths"}


def test_hey_mail_is_read_and_marked_as_hey(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The provider is still recorded, so a record says where the mail came from."""
    import sqlite3

    from fixtures.mail import messages as fixtures

    box = fixtures.Mailbox()
    box.add(fixtures.message("From Hey", to=(fixtures.ANNA,)))
    archive = box.write_mbox(tmp_path / "hey-export.mbox")
    write(
        tmp_path,
        f'[[source]]\nname = "hey"\nkind = "mail.hey"\n'
        f'addresses = ["{fixtures.ME}"]\npaths = ["{archive.as_posix()}"]\n',
    )

    main(
        ["ingest", "--config", str(tmp_path / "config.toml"),
         "--store", str(tmp_path / "store.db")]
    )
    capsys.readouterr()

    connection = sqlite3.connect(tmp_path / "store.db")
    payload = connection.execute(
        "SELECT json_extract(payload, '$.provider') FROM raw_record"
    ).fetchone()[0]
    connection.close()
    assert payload == "hey"
