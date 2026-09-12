"""Reading incrementally, and surviving a lost cursor (FR-015, FR-016, SC-006).

Graph's delta chain makes resumption the server's problem rather than ours, which is the
whole reason it was chosen. What is tested here is the two ways that can go wrong: a run
that re-reads what it already has, and a cursor the provider no longer accepts.

The second is the one worth care. Losing a resumption point must cost **time**, never
data — a wider read that the store deduplicates, not a gap nobody notices.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fixtures.mail import messages as fx
from fixtures.responses import graph as recorded
from iknowwhatyoudid.errors import MailReadError
from iknowwhatyoudid.mail import graph


class Scripted:
    """A client that answers with queued pages and records every URL it was given."""

    def __init__(self, *pages: object, fail_on: str | None = None) -> None:
        self.pages = list(pages)
        self.urls: list[str] = []
        self.fail_on = fail_on

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> object:
        self.urls.append(url)
        if self.fail_on and self.fail_on in url:
            raise MailReadError("the delta token is no longer valid")
        return self.pages.pop(0) if self.pages else recorded.page()


def read_all(client: Scripted, **kwargs: object) -> list[tuple[dict[str, str], bool, str | None]]:
    return list(
        graph.read(
            client,
            token="access",
            since=kwargs.get("since"),  # type: ignore[arg-type]
            resumption_point=kwargs.get("resumption_point"),  # type: ignore[arg-type]
        )
    )


# --- the ordinary path --------------------------------------------------------------


def test_a_first_read_starts_from_the_configured_window() -> None:
    """FR-005 — nothing older than `since` is asked for."""
    client = Scripted(
        recorded.page(recorded.message(message_id="a@x", subject="One"))
    )
    read_all(client, since=datetime(2026, 1, 1, tzinfo=UTC))

    assert "sentitems" in client.urls[0]
    assert "%24filter" in client.urls[0] or "$filter" in client.urls[0]
    assert "2026-01-01" in client.urls[0]


def test_the_delta_link_comes_back_with_the_last_message() -> None:
    """It is what the next run resumes from, so it must survive the read."""
    client = Scripted(
        recorded.page(
            recorded.message(message_id="a@x", subject="One"),
            recorded.message(message_id="b@x", subject="Two", graph_id="B"),
        )
    )
    results = read_all(client)

    points = [point for _, _, point in results]
    assert points[:-1] == [None] * (len(points) - 1), "only the last carries the cursor"
    assert points[-1] == recorded.DELTA_LINK


def test_paging_follows_next_link_then_yields_the_delta_link() -> None:
    client = Scripted(
        recorded.page(
            recorded.message(message_id="a@x", subject="One"),
            next_link=recorded.NEXT_LINK,
            delta_link=None,
        ),
        recorded.page(recorded.message(message_id="b@x", subject="Two", graph_id="B")),
    )
    results = read_all(client)

    assert len(client.urls) == 2
    assert client.urls[1] == recorded.NEXT_LINK
    assert results[-1][2] == recorded.DELTA_LINK


def test_a_second_run_with_nothing_changed_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-006 — an empty delta page still advances the cursor, so it stays cheap."""
    client = Scripted(recorded.page())
    results = read_all(client, resumption_point=recorded.DELTA_LINK)

    assert client.urls == [recorded.DELTA_LINK], "the stored link is used verbatim"
    messages = [headers for headers, _, _ in results if headers]
    assert messages == [], "nothing new"
    assert results[-1][2] == recorded.DELTA_LINK, "and the cursor is still carried forward"


def test_a_stored_link_is_used_exactly_as_given() -> None:
    """Graph requires it. Rebuilding the query would silently restart the chain."""
    client = Scripted(recorded.page())
    read_all(client, resumption_point=recorded.DELTA_LINK, since=datetime(2020, 1, 1, tzinfo=UTC))

    assert client.urls == [recorded.DELTA_LINK]
    assert "2020" not in client.urls[0], "`since` must not be re-applied over a cursor"


# --- when the cursor is refused -------------------------------------------------------


def test_a_rejected_delta_link_raises_so_the_caller_can_widen() -> None:
    """The reader's job is to report it; recovering is `MailReader`'s."""
    client = Scripted(fail_on="deltatoken")
    with pytest.raises(MailReadError):
        read_all(client, resumption_point=recorded.DELTA_LINK)


def test_a_removed_message_is_not_a_record() -> None:
    """A delta reports deletions as tombstones. They are not messages.

    Concluding from a tombstone would also be wrong for an incremental run, which has no
    business deciding anything is gone — that is a sweep's judgement (FR-022).
    """
    client = Scripted(
        recorded.page(
            recorded.message(message_id="a@x", subject="Still here"),
            recorded.removed("AAMkDELETED"),
        )
    )
    results = read_all(client)

    subjects = [headers.get("Subject") for headers, _, _ in results if headers]
    assert subjects == ["Still here"]


def test_a_runaway_page_chain_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page that always points at another page is a loop, not a long history."""
    monkeypatch.setattr(graph, "MAX_PAGES", 5)

    class Endless:
        urls: list[str] = []

        def get(self, url: str, *, headers: dict[str, str] | None = None) -> object:
            Endless.urls.append(url)
            return recorded.page(
                recorded.message(message_id=f"{len(Endless.urls)}@x", subject="x"),
                next_link=recorded.NEXT_LINK,
                delta_link=None,
            )

    with pytest.raises(MailReadError) as raised:
        list(graph.read(Endless(), token="t", since=None, resumption_point=None))
    assert "paging" in str(raised.value)


# --- streaming ----------------------------------------------------------------------------


def test_reading_streams_rather_than_accumulating() -> None:
    """The fault `0003` shipped and had to correct, asserted here from the start.

    `read` is a generator, and the delta link is emitted with the final message rather
    than returned at the end — which is what lets it stay one.
    """
    import inspect

    assert inspect.isgeneratorfunction(graph.read)

    client = Scripted(
        recorded.page(*[
            recorded.message(message_id=f"{i}@x", subject=str(i), graph_id=str(i))
            for i in range(100)
        ])
    )
    stream = graph.read(client, token="t", since=None, resumption_point=None)

    first = next(stream)
    assert first[0]["Subject"] == "0", "the first message arrives before the last is read"


def test_the_sent_items_folder_is_the_only_one_asked_for() -> None:
    """FR-048 — received mail is never fetched, not fetched and discarded."""
    client = Scripted(recorded.page(recorded.message(message_id="a@x", subject="One")))
    read_all(client)

    assert all("sentitems" in url for url in client.urls)
    for folder in ("inbox", "archive", "junkemail", "drafts"):
        assert not any(folder in url.lower() for url in client.urls), folder


def test_the_select_travels_with_the_request() -> None:
    """A request without it would return every field, body included."""
    client = Scripted(recorded.page())
    read_all(client)

    url = client.urls[0]
    assert "select" in url.lower()
    for field in graph.SELECT:
        assert field in url, field
    assert "body" not in url.lower().replace("nobody", "")
