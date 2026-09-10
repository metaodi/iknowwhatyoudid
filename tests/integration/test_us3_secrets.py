"""User Story 3 — secrets are named, never pasted (FR-006, FR-020 to FR-025, SC-007)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import sources_commands
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.config import findings as f
from iknowwhatyoudid.config import secret_scan
from iknowwhatyoudid.credentials import redaction
from iknowwhatyoudid.credentials.store import CredentialPresence, CredentialStore
from iknowwhatyoudid.protection.permissions import PermissionStatus, interpret_sddl

FIXTURES = Path("tests/fixtures/configs")
RECORDED = Path("tests/fixtures/recorded/day.jsonl")

SENTINEL = "SUPER-SECRET-VALUE-a1b2c3d4e5f6"
OWNER = "S-1-5-21-2541456660-2113479907-1373168818-13577"


@pytest.fixture(autouse=True)
def _clean_redaction() -> None:
    redaction.clear()


def _config_with_credential(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(
        '[[source]]\nname = "work-mail"\nkind = "mail.outlook"\n'
        'credential = "outlook-work"\naddresses = ["me@example.com"]\n',
        encoding="utf-8",
    )
    return config


# --- FR-021: a missing credential is named, with how to supply it -------------------


def test_a_missing_credential_is_reported_by_name(tmp_path: Path) -> None:
    session = sources_commands.open_config(str(_config_with_credential(tmp_path)))
    status = session.report.status_for("work-mail")

    assert status is not None
    assert status.readiness is f.Readiness.CREDENTIAL_MISSING
    finding = next(p for p in status.findings if p.code == f.CREDENTIAL_MISSING)
    assert "outlook-work" in finding.message
    assert finding.remedy is not None and "credentials.toml" in finding.remedy


def test_a_present_credential_makes_the_source_ready_or_not_readable(
    tmp_path: Path,
) -> None:
    config = _config_with_credential(tmp_path)
    (tmp_path / "credentials.toml").write_text(
        f'[credential.outlook-work]\ntoken = "{SENTINEL}"\n', encoding="utf-8"
    )

    session = sources_commands.open_config(str(config))
    status = session.report.status_for("work-mail")

    assert status is not None
    # mail.outlook has no reader yet, so the honest verdict is NOT_READABLE — but it is
    # no longer blocked on the credential.
    assert status.readiness is f.Readiness.NOT_READABLE


def test_the_store_reports_presence_and_never_returns_a_value(tmp_path: Path) -> None:
    """FR-021 — presence is the whole requirement; a store that cannot return a value
    cannot leak one."""
    path = tmp_path / "credentials.toml"
    path.write_text(f'[credential.a]\ntoken = "{SENTINEL}"\n', encoding="utf-8")
    store = CredentialStore(path)

    assert store.status("a").presence is CredentialPresence.PRESENT
    assert store.status("b").presence is CredentialPresence.ABSENT
    assert not hasattr(store, "value")
    assert not hasattr(store, "get_secret")


def test_an_unreadable_credential_store_is_distinguished_from_absent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "credentials.toml"
    path.write_text("[credential.a\nbroken", encoding="utf-8")
    assert CredentialStore(path).status("a").presence is CredentialPresence.UNREADABLE


# --- SC-007: the whole-surface assertion --------------------------------------------


def test_no_credential_value_reaches_any_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every command, both forms, then search everything for the sentinel."""
    config = tmp_path / "config.toml"
    config.write_text(
        '[[source]]\nname = "work-mail"\nkind = "mail.outlook"\n'
        'credential = "outlook-work"\naddresses = ["me@example.com"]\n\n'
        '[[source]]\nname = "recorded"\nkind = "fixture"\n'
        f'recorded = ["{RECORDED.as_posix()}"]\n',
        encoding="utf-8",
    )
    (tmp_path / "credentials.toml").write_text(
        f'[credential.outlook-work]\ntoken = "{SENTINEL}"\n', encoding="utf-8"
    )
    store = str(tmp_path / "store.db")

    invocations = [
        ["sources", "list"],
        ["sources", "validate"],
        ["sources", "check", "work-mail"],
        ["sources", "check", "work-mail", "--live"],
        ["sources", "kinds"],
        ["sources", "destinations"],
        ["ingest"],
    ]
    collected: list[str] = []
    for argv in invocations:
        for extra in ([], ["--json"]):
            main([*argv, "--config", str(config), "--store", store, *extra])
            captured = capsys.readouterr()
            collected.append(captured.out)
            collected.append(captured.err)

    haystack = "\n".join(collected)
    assert SENTINEL not in haystack, "a credential value reached output"
    assert "outlook-work" in haystack, "the credential NAME is still reportable"

    log = tmp_path / "iknowwhatyoudid.log"
    if log.exists():
        assert SENTINEL not in log.read_text(encoding="utf-8")
    assert SENTINEL not in (tmp_path / "store.db").read_bytes().decode(
        "utf-8", errors="ignore"
    )


def test_redaction_applies_to_the_json_form_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A --json path that skipped redaction would be the obvious leak."""
    redaction.register(SENTINEL)
    from iknowwhatyoudid.cli.render import envelope

    text = envelope("t", ok=True, store_path="p", data={"leaked": SENTINEL})
    assert SENTINEL not in text
    assert redaction.MASK in text
    assert json.loads(text)["data"]["leaked"] == redaction.MASK


# --- FR-023: inline secrets warn, never block ---------------------------------------


def test_an_inline_secret_is_a_warning_never_a_refusal() -> None:
    """FR-023 with FR-017: the heuristic warns, so a false positive cannot stop work."""
    session = sources_commands.open_config(str(FIXTURES / "inline-secret.toml"))
    secret_findings = [
        p for p in session.report.findings if p.code == f.INLINE_SECRET
    ]

    assert secret_findings, "the pasted secret was noticed"
    assert all(not p.blocks for p in secret_findings)
    assert secret_findings[0].remedy is not None


def test_a_pasted_secret_also_blocks_as_an_undeclared_setting() -> None:
    """The two findings do different jobs and both are wanted.

    `password` is not a setting `fixture` declares, so it blocks — refusing rather than
    ignoring a key the user believes is doing something. The secret warning alongside it
    explains *why* that particular key is worth not ignoring.
    """
    session = sources_commands.open_config(str(FIXTURES / "inline-secret.toml"))
    blocking = {p.code for p in session.report.blocking}

    assert f.UNKNOWN_SETTING in blocking
    assert f.INLINE_SECRET not in blocking


@pytest.mark.parametrize(
    "key,value",
    [
        ("password", "hunter2-and-more"),
        ("api_key", "abcdefghijklmnop"),
        ("client_secret", "shhhhhhhhhhhh"),
        ("anything", "ghp_0123456789abcdefghijABCDEFGHIJ"),
        ("anything", "-----BEGIN RSA PRIVATE KEY-----"),
        ("anything", "xoxb-1234567890-abcdefghij"),
    ],
)
def test_secrets_are_recognised(key: str, value: str) -> None:
    assert secret_scan.looks_like_secret(key, value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("paths", "~/dev/some/quite/long/path/to/a/repository"),
        ("identities", "stefan@example.com"),
        ("calendars", "primary"),
        # A commit hash and a SID are high-entropy but must not warn.
        ("revision", "9b108871f2c3d4e5a6b7c8d9e0f1a2b3c4d5e6f7"),
        ("owner", "S-1-5-21-2541456660-2113479907-1373168818-13577"),
        ("folders", "Inbox"),
    ],
)
def test_ordinary_values_do_not_warn(key: str, value: str) -> None:
    """False positives are what make a heuristic unusable."""
    assert not secret_scan.looks_like_secret(key, value)


# --- FR-006: file permissions, reusing 0001's checker -------------------------------


def test_permission_findings_are_warnings_not_refusals(tmp_path: Path) -> None:
    """T059 — mapped onto findings at this feature's boundary."""
    config = tmp_path / "config.toml"
    config.write_text("version = 1\n", encoding="utf-8")

    session = sources_commands.open_config(str(config))
    permission_findings = [
        p
        for p in session.report.findings
        if p.code in {f.FILE_PERMISSIONS, f.FILE_PERMISSIONS_UNVERIFIED}
    ]
    assert all(not p.blocks for p in permission_findings)


def test_an_unverifiable_file_is_never_reported_as_safe() -> None:
    """T060 — the assertion must hold here, not only inside protection/."""
    assert interpret_sddl("").status is PermissionStatus.UNVERIFIED
    assert interpret_sddl("D:(A;;FA;;;WD)").status is PermissionStatus.UNVERIFIED
    assert (
        interpret_sddl(f"O:{OWNER}D:(A;;FR;;;WD)").status
        is PermissionStatus.OTHERS_CAN_READ
    )


# --- FR-025: required access is visible before granting -----------------------------


def test_a_kind_declares_the_access_it_needs() -> None:
    from iknowwhatyoudid.kinds import registry

    outlook = registry.get("mail.outlook")
    assert outlook is not None
    assert outlook.required_access, "the user must see this before granting anything"
    assert outlook.as_dict()["required_access"]


def test_a_disabled_source_does_not_block_on_its_credential(tmp_path: Path) -> None:
    """A parked source must not fail the whole run over a credential it will not use.

    Structural faults are still reported for a disabled source — those are wrong
    whatever its state — but a missing credential is a readiness concern, not a
    structural one.
    """
    config = tmp_path / "config.toml"
    config.write_text(
        '[[source]]\nname = "parked"\nkind = "mail.hey"\nenabled = false\n'
        'credential = "not-supplied"\naddresses = ["me@example.com"]\n',
        encoding="utf-8",
    )
    session = sources_commands.open_config(str(config))

    assert session.report.ok, "a disabled source must not block the run"
    assert f.CREDENTIAL_MISSING not in {p.code for p in session.report.findings}
    assert session.report.status_for("parked").readiness is f.Readiness.DISABLED  # type: ignore[union-attr]


def test_a_disabled_source_still_reports_structural_faults(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[[source]]\nname = "parked"\nkind = "git.local"\nenabled = false\n'
        'identities = ["me@example.com"]\n',
        encoding="utf-8",
    )
    session = sources_commands.open_config(str(config))

    assert f.MISSING_REQUIRED_SETTING in {p.code for p in session.report.blocking}
