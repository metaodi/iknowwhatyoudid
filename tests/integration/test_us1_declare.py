"""User Story 1 — declare where my traces live (FR-001 to FR-019, FR-029, FR-041)."""

from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import sources_commands
from iknowwhatyoudid.config import findings as f
from iknowwhatyoudid.config import loader
from iknowwhatyoudid.config.validate import validate
from iknowwhatyoudid.errors import ConfigNotFoundError, ConfigParseError

FIXTURES = Path("tests/fixtures/configs")


def codes(findings: object) -> set[str]:
    return {finding.code for finding in findings}  # type: ignore[attr-defined]


def report_for(name: str) -> object:
    return sources_commands.open_config(str(FIXTURES / name)).report


# --- Scenario 1: nothing configured -------------------------------------------------


def test_absent_configuration_reports_its_path_and_creates_nothing(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nowhere" / "config.toml"

    with pytest.raises(ConfigNotFoundError) as caught:
        sources_commands.open_config(str(missing))

    assert str(missing) in caught.value.message
    assert not missing.exists(), "the tool must never create this file"
    assert not missing.parent.exists()


# --- Scenario 2: a valid configuration lists cleanly ---------------------------------


def test_every_source_is_listed_with_a_verdict() -> None:
    report = report_for("valid.toml")
    verdicts = {s.name: s.readiness for s in report.statuses}  # type: ignore[attr-defined]

    assert verdicts["recorded-day"] is f.Readiness.READY
    assert verdicts["personal-mail"] is f.Readiness.DISABLED
    assert verdicts["work-repos"] is f.Readiness.NOT_READABLE
    assert verdicts["work-mail"] is f.Readiness.CREDENTIAL_MISSING


def test_a_disabled_source_is_disabled_not_credential_missing() -> None:
    """A source switched off will not be read, so nagging about its credential is noise."""
    report = report_for("valid.toml")
    personal = report.status_for("personal-mail")  # type: ignore[attr-defined]
    assert personal.source.credential is not None, "it does name a credential"
    assert personal.readiness is f.Readiness.DISABLED


def test_validation_contacts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The load-bearing negative assertion (FR-014, SC-002)."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("validation opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    report = report_for("valid.toml")
    assert len(report.statuses) == 4  # type: ignore[attr-defined]


def test_an_empty_configuration_is_valid() -> None:
    """FR-005 — no sources is a state, not an error."""
    report = report_for("empty.toml")
    assert report.statuses == ()  # type: ignore[attr-defined]
    assert report.ok  # type: ignore[attr-defined]


# --- Scenario 3: every fault at once -------------------------------------------------


def test_all_faults_are_reported_in_one_run() -> None:
    """FR-016, SC-004 — never stop at the first."""
    report = report_for("many-faults.toml")
    found = codes(report.findings)  # type: ignore[attr-defined]

    assert f.DUPLICATE_SOURCE_NAME in found
    assert f.UNKNOWN_KIND in found
    assert f.MISSING_REQUIRED_SETTING in found
    assert f.UNKNOWN_SETTING in found
    assert f.INLINE_SECRET in found


def test_an_unknown_kind_does_not_stop_the_others_validating() -> None:
    """FR-029."""
    report = report_for("unknown-kind.toml")
    by_name = {s.name: s for s in report.statuses}  # type: ignore[attr-defined]

    assert by_name["mystery"].readiness is f.Readiness.UNKNOWN_KIND
    assert by_name["fine"].readiness is f.Readiness.READY, "still validated"


def test_unknown_kind_finding_lists_what_is_available() -> None:
    report = report_for("unknown-kind.toml")
    finding = next(
        p for p in report.findings if p.code == f.UNKNOWN_KIND  # type: ignore[attr-defined]
    )
    assert finding.remedy is not None
    assert "fixture" in finding.remedy


def test_findings_name_the_source_and_the_setting() -> None:
    """FR-016 — located by source name and by setting."""
    report = report_for("many-faults.toml")
    missing = next(
        p
        for p in report.findings  # type: ignore[attr-defined]
        if p.code == f.MISSING_REQUIRED_SETTING
    )
    assert missing.source_name == "no-paths"
    assert missing.key_path is not None and missing.key_path.endswith(".paths")


def test_blocking_is_separated_from_warning() -> None:
    """FR-017."""
    report = report_for("many-faults.toml")
    assert codes(report.blocking) & {f.DUPLICATE_SOURCE_NAME, f.UNKNOWN_KIND}  # type: ignore[attr-defined]
    assert f.INLINE_SECRET in codes(report.warnings)  # type: ignore[attr-defined]
    assert f.INLINE_SECRET not in codes(report.blocking)  # type: ignore[attr-defined]


# --- Scenario 4: a broken file is fatal and distinguishable --------------------------


def test_a_broken_file_is_fatal_with_a_location_and_exit_2() -> None:
    """FR-004 — a broken file and a broken source are different problems."""
    with pytest.raises(ConfigParseError) as caught:
        loader.load(FIXTURES / "broken.toml")

    assert caught.value.exit_code == 2
    assert caught.value.line is not None, "tomllib gives a position; keep it"


def test_a_broken_file_is_never_rewritten(tmp_path: Path) -> None:
    """FR-002."""
    target = tmp_path / "config.toml"
    shutil.copy(FIXTURES / "broken.toml", target)
    before = target.read_bytes()

    with pytest.raises(ConfigParseError):
        loader.load(target)

    assert target.read_bytes() == before


def test_a_valid_file_is_never_rewritten(tmp_path: Path) -> None:
    """FR-002, the positive case: reading must not reformat."""
    target = tmp_path / "config.toml"
    shutil.copy(FIXTURES / "valid.toml", target)
    before = target.read_bytes()

    configuration, problems = loader.load(target)
    validate(configuration, problems)

    assert target.read_bytes() == before


# --- FR-041: attribution is refused, not ignored -------------------------------------


def test_a_project_mapping_is_rejected_rather_than_ignored() -> None:
    report = report_for("with-attribution.toml")
    assert f.ATTRIBUTION_NOT_ALLOWED in codes(report.blocking)  # type: ignore[attr-defined]


def test_an_unknown_top_level_key_blocks(tmp_path: Path) -> None:
    """A misspelled key is a source you believe is configured; refusing is safer."""
    target = tmp_path / "config.toml"
    target.write_text('sources = []\n', encoding="utf-8")

    configuration, problems = loader.load(target)
    assert f.UNKNOWN_TOP_LEVEL_KEY in {p.code for p in problems}


# --- Names ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "-leading", "has space", "has/slash"])
def test_unusable_source_names_are_rejected(tmp_path: Path, name: str) -> None:
    """FR-007, FR-008 — the name becomes an identifier in the store."""
    target = tmp_path / "config.toml"
    target.write_text(
        f'[[source]]\nname = "{name}"\nkind = "fixture"\n', encoding="utf-8"
    )
    _, problems = loader.load(target)
    assert f.INVALID_SOURCE_NAME in {p.code for p in problems}
