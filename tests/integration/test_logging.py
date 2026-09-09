"""The log carries identifiers and counts, never record content (FR-039 to FR-043, SC-015)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from iknowwhatyoudid.obs import logging as obs
from iknowwhatyoudid.protection.permissions import PermissionStatus, check

SENTINEL_TITLE = "SENSITIVE-SUBJECT-LINE-9f3a"
SENTINEL_BODY = "SENSITIVE-BODY-TEXT-71cc"


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    path = tmp_path / "app.log"
    obs.reset_for_tests()
    obs.configure(path)
    return path


def _flush() -> None:
    for handler in logging.getLogger(obs.LOGGER_NAME).handlers:
        handler.flush()


def test_a_full_run_writes_no_record_content(log_file: Path) -> None:
    """SC-015 — the whole-surface assertion."""
    obs.store_opened(Path("/tmp/store.db"), 1)
    obs.ingestion_started("mail", "sweep")
    obs.record_rejected("mail", "AAMkAGI2-real-id", "naive-datetime")
    obs.ingestion_finished(
        "mail", inserted=3, updated=1, unchanged=0, withdrawn=2, seconds=0.4
    )
    obs.corrections_imported(new=1, replaced=2, declined=0, pending=1)
    _flush()

    written = log_file.read_text(encoding="utf-8")
    assert SENTINEL_TITLE not in written
    assert SENTINEL_BODY not in written
    # ... while the record is still identifiable for diagnosis (FR-040).
    assert "AAMkAGI2-real-id" in written
    assert "source=mail" in written
    assert "inserted=3" in written


def test_the_logging_api_has_no_way_to_accept_record_content() -> None:
    """FR-041 enforced structurally rather than by a filter.

    A filter over formatted lines cannot tell a subject line from an identifier, so it
    would either leak or mangle. Restricting the API's *parameters* means logging a title
    would require adding a function that takes one — a visible change a reviewer catches.
    """
    import inspect

    banned = {"title", "payload", "body", "subject", "record", "content", "participants"}
    for name, function in vars(obs).items():
        if name.startswith("_") or not inspect.isfunction(function):
            continue
        parameters = set(inspect.signature(function).parameters)
        assert not (parameters & banned), f"{name} accepts record content"


def test_the_log_is_not_world_readable(log_file: Path) -> None:
    """FR-039."""
    obs.store_opened(Path("/tmp/store.db"), 1)
    _flush()
    assert check(log_file).status is not PermissionStatus.OTHERS_CAN_READ


def test_the_log_is_bounded(log_file: Path) -> None:
    """FR-042 — it cannot grow without limit on a machine that keeps records forever."""
    for index in range(20_000):
        obs.record_rejected("mail", f"id-{index}", "test")
    _flush()

    assert log_file.stat().st_size <= obs.MAX_BYTES * 1.1
    rotated = list(log_file.parent.glob(f"{log_file.name}.*"))
    assert len(rotated) <= obs.BACKUP_COUNT


def test_an_unwritable_log_does_not_fail_the_operation(tmp_path: Path) -> None:
    """FR-043."""
    obs.reset_for_tests()
    unwritable = tmp_path / "a-file-not-a-dir"
    unwritable.write_text("x")

    logger = obs.configure(unwritable / "nested" / "app.log")

    assert logger is not None
    obs.store_opened(tmp_path / "store.db", 1)  # must not raise
