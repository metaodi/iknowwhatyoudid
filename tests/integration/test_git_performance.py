"""Performance of reading git (SC-004's scale, FR-003's cheapness).

Two properties, both about the tool staying usable on a real developer's machine:

* reading a long history streams, so peak memory does not grow with the number of
  commits — a repository with twenty thousand commits must not become twenty thousand
  objects held at once;
* deciding *which* repositories to read is cheap, because it reads no history at all.

Timing budgets here are deliberately loose. They exist to catch an accidental quadratic
or a per-commit subprocess, not to police a few hundred milliseconds on a busy machine.
"""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures import gitrepos
from iknowwhatyoudid.git import discovery, history

LONG_HISTORY = 20_000
MANY_REPOSITORIES = 100

#: Peak memory may not grow more than this between reading a tenth of the history and
#: reading all of it. Streaming is flat; accumulating is linear, and would be ~10x.
GROWTH_TOLERANCE = 1.6


def _peak_bytes_reading(repository: Path, limit: int) -> int:
    tracemalloc.start()
    tracemalloc.reset_peak()
    count = 0
    for _commit in history.commits(repository):
        count += 1
        if count >= limit:
            break
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert count == limit
    return peak


@pytest.mark.slow
def test_a_long_history_streams_with_flat_peak_memory(tmp_path: Path) -> None:
    """SC-004's scale — twenty thousand commits, held one at a time."""
    repository = gitrepos.large(tmp_path, LONG_HISTORY)

    part = _peak_bytes_reading(repository, LONG_HISTORY // 10)
    whole = _peak_bytes_reading(repository, LONG_HISTORY)

    assert whole < part * GROWTH_TOLERANCE, (
        f"peak memory grew from {part:,} to {whole:,} bytes reading ten times as many "
        "commits; history is being accumulated rather than streamed"
    )


@pytest.mark.slow
def test_a_long_history_is_read_in_one_pass(tmp_path: Path) -> None:
    """One `git log`, not one invocation per commit."""
    repository = gitrepos.large(tmp_path, 2_000)

    from iknowwhatyoudid.git import binary

    calls: list[str] = []
    original = binary.stream_lines

    def spy(repo: Path, subcommand: str, *args: str) -> Iterator[str]:
        calls.append(subcommand)
        return original(repo, subcommand, *args)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(binary, "stream_lines", spy)
    try:
        read = sum(1 for _ in history.commits(repository))
    finally:
        monkey.undo()

    assert read == 2_000
    assert calls.count("log") == 1, calls


@pytest.mark.slow
def test_listing_a_hundred_repositories_reads_no_history(tmp_path: Path) -> None:
    """FR-003, SC-008 — deciding what to read must be cheap enough to run often."""
    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.many(dev, MANY_REPOSITORIES)

    from iknowwhatyoudid.git import binary

    used: list[str] = []
    original = binary.run

    def spy(repo: Path, subcommand: str, *args: str, **kwargs: object) -> str:
        used.append(subcommand)
        return original(repo, subcommand, *args, **kwargs)  # type: ignore[arg-type]

    monkey = pytest.MonkeyPatch()
    monkey.setattr(binary, "run", spy)
    began = time.perf_counter()
    try:
        found = discovery.discover([str(dev)])
    finally:
        monkey.undo()
    elapsed = time.perf_counter() - began

    assert len(found.repositories) == MANY_REPOSITORIES
    assert "log" not in used, "listing must not read history"
    assert elapsed < 60.0, f"listing {MANY_REPOSITORIES} repositories took {elapsed:.1f}s"
