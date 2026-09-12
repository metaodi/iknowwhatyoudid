"""Only mail the user sent is recorded (FR-048, FR-049, SC-004a).

Two halves, and the second is what makes the first robust:

* received mail does not become a record;
* received mail is **never fetched**, because the request names the Sent folder.

The second means the requirement holds even if the filtering code is wrong, and less data
crosses the network to begin with.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from fixtures.responses import graph as recorded
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.mail import graph, message as msg
from iknowwhatyoudid.mail.message import MessageRejected, Provider


def workspace(tmp_path: Path) -> Path:
    """An archive holding mail in both directions."""
    archive = fx.sent_and_received().write_mbox(tmp_path / "export.mbox")
    (tmp_path / "config.toml").write_text(
        f'[[source]]\nname = "mail"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{archive.as_posix()}"]\n',
        encoding="utf-8",
    )
    return tmp_path


def subjects_in(space: Path) -> list[str]:
    connection = sqlite3.connect(space / "store.db")
    rows = connection.execute(
        "SELECT json_extract(payload, '$.subject') FROM raw_record"
    ).fetchall()
    connection.close()
    return [str(row[0]) for row in rows]


# --- what becomes a record ------------------------------------------------------------


def test_only_sent_mail_is_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fixture holds one sent message and two received, so this cannot pass idly."""
    space = workspace(tmp_path)
    main(["ingest", "--config", str(space / "config.toml"),
          "--store", str(space / "store.db")])
    capsys.readouterr()

    assert subjects_in(space) == ["Rollout plan"]


def test_a_message_from_someone_else_is_refused_by_the_shape() -> None:
    """Reaching here means a provider returned outside the Sent folder."""
    entry = recorded.message(
        message_id="theirs@x", subject="Not mine", sender=fx.ANNA, to=(fx.ME,)
    )
    with pytest.raises(MessageRejected) as raised:
        msg.build(
            headers=graph.headers_from(entry),
            account="work",
            provider=Provider.GRAPH,
            own_addresses=[fx.ME],
        )
    assert "not one of this account" in raised.value.reason


def test_a_second_declared_address_still_counts_as_mine() -> None:
    """An account may hold several; FR-021 records which one sent it."""
    entry = recorded.message(
        message_id="other@x", subject="From the other one", sender=fx.ME_OTHER
    )
    message = msg.build(
        headers=graph.headers_from(entry),
        account="work",
        provider=Provider.GRAPH,
        own_addresses=[fx.ME, fx.ME_OTHER],
    )
    assert message.sent_by == fx.ME_OTHER


# --- what is asked for ------------------------------------------------------------------


def test_the_request_names_the_sent_folder_rather_than_filtering_afterwards() -> None:
    """SC-004a's structural half."""
    url = graph.starting_url(None, None)
    assert "sentitems" in url.lower()
    assert "inbox" not in url.lower()


# --- and the output says so ----------------------------------------------------------------


def test_every_mail_listing_says_received_mail_is_not_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-049 — a day that looks empty must be distinguishable from a day that was.

    Without this line, a user whose Tuesday was all replies would see nothing and
    conclude they did nothing, which is exactly the invisible gap this project exists to
    prevent.
    """
    space = workspace(tmp_path)
    main(["ingest", "--config", str(space / "config.toml"),
          "--store", str(space / "store.db")])
    capsys.readouterr()

    main(["mail", "list", "--store", str(space / "store.db")])
    out = capsys.readouterr().out

    assert "sent mail only" in out
    assert "received mail is not read" in out
