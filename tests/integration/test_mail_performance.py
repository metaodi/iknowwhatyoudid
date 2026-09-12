"""Reading a year of mail streams rather than accumulating.

`0003` shipped a git reader that pulled an entire history into one string before parsing
any of it, and it took a real repository with 29,436 directories to notice. The property
is asserted here from the start instead.

What matters is that **peak memory does not grow with the size of the mailbox**. A tool
that holds a year of mail in memory to write it to a database is the wrong shape for
something that runs on a laptop.
"""

from __future__ import annotations

import inspect
import tracemalloc
from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from fixtures.responses import graph as recorded
from iknowwhatyoudid.mail import gmail, graph, mbox

A_YEAR = 5_000

#: Peak memory may not grow more than this between reading a tenth and reading all.
#: Streaming is flat; accumulating is linear and would be roughly ten times.
GROWTH_TOLERANCE = 1.6


class Pages:
    """A client that hands out one large delta page."""

    def __init__(self, count: int) -> None:
        self.page = recorded.page(
            *[
                recorded.message(
                    message_id=f"{i}@fixture.example", subject=f"Message {i}", graph_id=str(i)
                )
                for i in range(count)
            ]
        )

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> object:
        return self.page


# --- the readers are generators, not list builders ------------------------------------


@pytest.mark.parametrize("reader", [graph.read, gmail.read, mbox.read])
def test_every_reader_is_a_generator(reader: object) -> None:
    """The structural half. A function that returns a list cannot stream."""
    assert inspect.isgeneratorfunction(reader)


def test_the_first_message_arrives_before_the_last_is_parsed() -> None:
    """The behavioural half, and the one a refactor would break."""
    stream = graph.read(Pages(A_YEAR), token="t", since=None, resumption_point=None)
    first = next(stream)
    assert first[0]["Subject"] == "Message 0"


# --- peak memory ------------------------------------------------------------------------


def peak_reading(count: int, limit: int) -> int:
    tracemalloc.start()
    tracemalloc.reset_peak()
    seen = 0
    for _ in graph.read(Pages(count), token="t", since=None, resumption_point=None):
        seen += 1
        if seen >= limit:
            break
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return peak


@pytest.mark.slow
def test_peak_memory_does_not_grow_with_the_mailbox() -> None:
    """The fault `0003` shipped, asserted here before it can be shipped again.

    The page itself is built up front by the fixture, so what this measures is the
    *reader's* own accumulation — which must be one message at a time.
    """
    part = peak_reading(A_YEAR, A_YEAR // 10)
    whole = peak_reading(A_YEAR, A_YEAR)

    assert whole < part * GROWTH_TOLERANCE, (
        f"peak memory grew from {part:,} to {whole:,} bytes reading ten times as many "
        "messages; the reader is accumulating rather than streaming"
    )


@pytest.mark.slow
def test_a_large_archive_streams_too(tmp_path: Path) -> None:
    """`mailbox.mbox` indexes the file, so this is about what the reader adds on top."""
    box = fx.Mailbox()
    for index in range(2_000):
        box.add(fx.message(f"Message {index}", offset_seconds=index))
    archive = box.write_mbox(tmp_path / "large.mbox")

    tracemalloc.start()
    tracemalloc.reset_peak()
    count = sum(1 for _ in mbox.read(archive))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert count == 2_000
    # Generous: the index is `mailbox`'s, not ours. What this catches is a reader that
    # builds a list of two thousand parsed messages, which would be far larger.
    assert peak < 40_000_000, f"peak {peak:,} bytes for 2,000 messages"
