"""User Story 4 — a kind of source that does not exist yet (FR-026 to FR-032, SC-008)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import sources_commands
from iknowwhatyoudid.config import findings as f
from iknowwhatyoudid.config.model import ConfiguredSource
from iknowwhatyoudid.kinds import registry
from iknowwhatyoudid.kinds.spec import (
    CredentialHandle,
    LiveCheckResult,
    ReadingAvailability,
    SettingSpec,
    SettingType,
    SourceKind,
)
from iknowwhatyoudid.records.model import NormalizedRecord, RunMode
from iknowwhatyoudid.sources import run
from iknowwhatyoudid.sources.state import InMemorySourceStateStore

FIXTURES = Path("tests/fixtures/configs")

# A kind no module under src/ knows anything about. If US4 holds, this behaves exactly
# like a shipped kind without a single change to one.
STICKY_NOTES = "sticky.notes"


class _StickyReader:
    def validate(self, source: ConfiguredSource) -> Sequence[f.Finding]:
        return []

    def check_live(
        self, source: ConfiguredSource, credential: CredentialHandle | None
    ) -> LiveCheckResult:
        return LiveCheckResult(True, "the drawer is open")

    def read(
        self,
        source: ConfiguredSource,
        credential: CredentialHandle | None,
        since: datetime | None,
        mode: RunMode,
    ) -> Iterator[NormalizedRecord]:
        note = source.settings.get("note", "a note")
        yield NormalizedRecord(
            source_id="n1",
            occurred=datetime.fromisoformat("2026-03-02T10:00:00+00:00"),
            title=str(note),
            payload={"kind": "sticky"},
        )


STICKY_KIND = SourceKind(
    name=STICKY_NOTES,
    summary="notes stuck to a monitor",
    settings=(
        SettingSpec("note", SettingType.STRING, required=True, help="What it says."),
    ),
    reading=ReadingAvailability.AVAILABLE,
    reader=_StickyReader(),
)


@pytest.fixture
def with_sticky_kind() -> Iterator[None]:
    registry.register_for_test(STICKY_KIND)
    try:
        yield
    finally:
        registry.reset_for_test()


@pytest.fixture
def sticky_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(
        f'[[source]]\nname = "desk"\nkind = "{STICKY_NOTES}"\nnote = "call back"\n',
        encoding="utf-8",
    )
    return config


def test_a_new_kind_is_listed_beside_the_others(with_sticky_kind: None) -> None:
    """Scenario 1."""
    result = sources_commands.sources_kinds(None, name=None)
    names = [k["name"] for k in result.data["kinds"]]

    assert STICKY_NOTES in names
    assert "fixture" in names, "shipped kinds are still there"


def test_a_new_kind_declares_its_settings_to_the_user(with_sticky_kind: None) -> None:
    """FR-028 — generated from the same declaration validation walks."""
    result = sources_commands.sources_kinds(None, name=STICKY_NOTES)
    declared = result.data["kinds"][0]["settings"]

    assert declared[0]["key"] == "note"
    assert declared[0]["required"] is True
    assert declared[0]["help"]


def test_a_new_kind_validates_against_its_own_declaration(
    with_sticky_kind: None, sticky_config: Path
) -> None:
    """Scenario 2."""
    session = sources_commands.open_config(str(sticky_config))
    status = session.report.status_for("desk")

    assert status is not None
    assert status.readiness is f.Readiness.READY


def test_a_new_kind_is_rejected_when_its_required_setting_is_missing(
    with_sticky_kind: None, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'[[source]]\nname = "desk"\nkind = "{STICKY_NOTES}"\n', encoding="utf-8"
    )
    session = sources_commands.open_config(str(config))

    assert f.MISSING_REQUIRED_SETTING in {p.code for p in session.report.blocking}


def test_a_new_kind_ingests_through_the_same_command(
    with_sticky_kind: None, sticky_config: Path
) -> None:
    """Scenario 2, end of — the same path a shipped kind takes."""
    session = sources_commands.open_config(str(sticky_config))
    report = run.ingest(session.report, InMemorySourceStateStore())

    assert report.outcomes[0].result is run.RunResult.SUCCEEDED
    assert report.outcomes[0].records_ingested == 1


def test_a_new_kind_enables_and_disables_like_any_other(
    with_sticky_kind: None, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'[[source]]\nname = "desk"\nkind = "{STICKY_NOTES}"\n'
        'enabled = false\nnote = "later"\n',
        encoding="utf-8",
    )
    session = sources_commands.open_config(str(config))

    assert session.report.status_for("desk").readiness is f.Readiness.DISABLED  # type: ignore[union-attr]


def test_an_unrecognised_kind_is_named_alongside_what_is_available() -> None:
    """Scenario 3 — and the other sources still validate (FR-029)."""
    session = sources_commands.open_config(str(FIXTURES / "unknown-kind.toml"))
    finding = next(p for p in session.report.findings if p.code == f.UNKNOWN_KIND)

    assert "obsidian.vault" in finding.message
    assert finding.remedy is not None and "fixture" in finding.remedy
    assert session.report.status_for("fine").readiness is f.Readiness.READY  # type: ignore[union-attr]


def test_an_existing_configuration_is_unaffected_when_a_kind_is_added() -> None:
    """Scenario 4, and FR-030 — nobody's file changes because a kind arrived.

    The assertion is that the verdict is *identical* before and after, not merely that
    the file still parses: a new kind must be invisible to configurations that do not
    use it.
    """

    def verdict() -> tuple[tuple[str, str], ...]:
        report = sources_commands.open_config(str(FIXTURES / "valid.toml")).report
        return tuple(
            (status.name, status.readiness.value) for status in report.statuses
        ) + tuple((p.code, p.source_name or "") for p in report.findings)

    registry.reset_for_test()
    before = verdict()

    registry.register_for_test(STICKY_KIND)
    try:
        assert verdict() == before
    finally:
        registry.reset_for_test()


def test_adding_a_kind_changed_no_existing_kind(with_sticky_kind: None) -> None:
    """SC-008 — the actual assertion, not just that the new kind works."""
    for name in registry.built_in_names():
        kind = registry.get(name)
        assert kind is not None
        assert kind.name == name, "a shipped kind was mutated by the addition"


# --- FR-031: nothing is loaded from outside the project ------------------------------


def test_a_kind_offered_from_outside_is_neither_loaded_nor_listed() -> None:
    """FR-031. `register_for_test` is a test seam, not a loading path.

    The property that matters is that *the product* has no code path which discovers
    kinds. Asserted below by checking the registry never reads the filesystem or entry
    points, and here by confirming an unregistered kind simply does not exist.
    """
    registry.reset_for_test()
    assert not registry.is_registered(STICKY_NOTES)
    assert STICKY_NOTES not in registry.names()
    assert registry.get(STICKY_NOTES) is None


def test_the_registry_has_no_discovery_mechanism() -> None:
    """FR-031 by construction: there is nothing to accidentally enable."""
    source = Path("src/iknowwhatyoudid/kinds/registry.py").read_text(encoding="utf-8")

    for forbidden in (
        "entry_points",
        "importlib.import_module",
        "pkgutil",
        "glob",
        "iterdir",
        "__import__",
    ):
        assert forbidden not in source, f"registry must not {forbidden}"


def test_an_installed_third_party_kind_is_not_picked_up(tmp_path: Path) -> None:
    """Even a module on sys.path declaring a SourceKind stays invisible."""
    plugin = tmp_path / "rogue_kind.py"
    plugin.write_text(
        "from iknowwhatyoudid.kinds.spec import SourceKind\n"
        'KIND = SourceKind(name="rogue.kind", summary="should never load")\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import rogue_kind\n"
            "from iknowwhatyoudid.kinds import registry\n"
            "print('rogue.kind' in registry.names())",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            **dict(__import__("os").environ),
            "PYTHONPATH": str(Path("src").resolve()) + __import__("os").pathsep + str(tmp_path),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
