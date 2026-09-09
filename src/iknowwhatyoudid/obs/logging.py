"""The diagnostic log (FR-039 to FR-043).

FR-041 forbids record content in the log. That is enforced *structurally* rather than by
a filter: every function here takes identifiers, counts and durations, and none takes a
record, a title, or a payload. To log a subject line, a future author would have to add a
function that accepts one — a visible change a reviewer can catch. A regex filter over
formatted lines cannot tell a subject from an identifier, so it would either leak or
mangle.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from ..protection import permissions

LOGGER_NAME = "iknowwhatyoudid"

#: FR-042 — bounded, so it cannot grow without limit on a machine whose records are
#: retained indefinitely. Size-based rather than time-based: a time rotation still
#: produces an unbounded file when a heavy backlog is ingested in one day.
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3

_configured = False


def configure(log_path: Path | None, *, verbose: bool = False) -> logging.Logger:
    """Attach the rotating file handler, falling back to stderr alone if it cannot be.

    FR-043: a log that cannot be written must not prevent an operation from completing.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if _configured:
        return logger

    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")

    stream = logging.StreamHandler()
    stream.setLevel(logging.DEBUG if verbose else logging.WARNING)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
            )
            handler.setLevel(logging.INFO)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            permissions.restrict_to_owner(log_path)
        except OSError as exc:
            logger.warning("log file unavailable (%s); continuing without it", exc)

    _configured = True
    return logger


def _log() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def reset_for_tests() -> None:
    global _configured
    logger = _log()
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _configured = False


# --- The logging API. Identifiers, counts and durations only. -----------------------
# Deliberately no function here accepts a record, a title, or a payload (FR-041).


def store_opened(path: Path, schema_version: int) -> None:
    _log().info("store opened path=%s schema=v%d", path, schema_version)


def migration_applied(from_version: int, to_version: int) -> None:
    _log().info("migration applied v%d -> v%d", from_version, to_version)


def migration_failed(from_version: int, to_version: int, reason: str) -> None:
    _log().error(
        "migration failed v%d -> v%d; store unchanged (%s)", from_version, to_version, reason
    )


def ingestion_started(source: str, mode: str) -> None:
    _log().info("ingestion started source=%s mode=%s", source, mode)


def ingestion_finished(
    source: str,
    *,
    inserted: int,
    updated: int,
    unchanged: int,
    withdrawn: int,
    seconds: float,
) -> None:
    _log().info(
        "ingestion finished source=%s inserted=%d updated=%d unchanged=%d "
        "withdrawn=%d seconds=%.3f",
        source,
        inserted,
        updated,
        unchanged,
        withdrawn,
        seconds,
    )


def record_rejected(source: str, source_id: str, reason_code: str) -> None:
    """A record could not be stored.

    `source_id` is the source's own identifier — an identifier, not content (FR-040) —
    and `reason_code` is a fixed code, never a message built from record data.
    """
    _log().warning(
        "record rejected source=%s source_id=%s reason=%s", source, source_id, reason_code
    )


def corrections_imported(*, new: int, replaced: int, declined: int, pending: int) -> None:
    _log().info(
        "corrections imported new=%d replaced=%d declined=%d pending=%d",
        new,
        replaced,
        declined,
        pending,
    )


def integrity_problem(path: Path, problem_count: int) -> None:
    _log().error("integrity check failed path=%s problems=%d", path, problem_count)
