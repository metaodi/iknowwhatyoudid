"""Gmail (US3, FR-028, SC-014) — the same assertions, a different provider.

The point of this file is how little is in it. Everything about shape, attribution and
storage is already asserted once and runs unchanged against Gmail fixtures; what remains
here is the handful of things that are genuinely Gmail's own — the scope, the label, the
metadata format, and `historyId` expiry.

If this file needed to grow, FR-028 would be in trouble.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from fixtures.responses import gmail as recorded
from iknowwhatyoudid.mail import gmail, graph, message as msg
from iknowwhatyoudid.mail.message import Provider
from iknowwhatyoudid.net.http import HttpStatusError


class Scripted:
    """Answers listing, history and message requests from recorded payloads."""

    def __init__(
        self,
        listing: object | None = None,
        messages: dict[str, object] | None = None,
        history: object | None = None,
        history_status: int | None = None,
    ) -> None:
        self.listing = listing if listing is not None else recorded.listing()
        self.messages = messages or {}
        self.history = history
        self.history_status = history_status
        self.urls: list[str] = []

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> object:
        self.urls.append(url)
        if "/history" in url:
            if self.history_status:
                raise HttpStatusError(self.history_status, gmail.GMAIL_HOST)
            return self.history
        if "/messages/" in url:
            identifier = url.split("/messages/")[1].split("?")[0]
            return self.messages[identifier]
        return self.listing


def read_all(client: Scripted, **kwargs: object) -> list[tuple[dict[str, str], bool, str | None]]:
    return list(
        gmail.read(
            client,
            token="access",
            since=kwargs.get("since"),  # type: ignore[arg-type]
            resumption_point=kwargs.get("resumption_point"),  # type: ignore[arg-type]
        )
    )


# --- the scope decides it (research R2) -------------------------------------------------


def test_the_scope_is_metadata_and_imap_is_not_used() -> None:
    """Principle II applied literally.

    IMAP offers exactly one Gmail scope, `https://mail.google.com/`, and it grants send
    and delete. A credential that could destroy what we promised only to observe is not
    made acceptable by careful client code, so IMAP is not an option here at all.
    """
    assert gmail.SCOPES == ("https://www.googleapis.com/auth/gmail.metadata",)
    assert "mail.google.com" not in " ".join(gmail.SCOPES)
    assert "gmail.readonly" not in " ".join(gmail.SCOPES), (
        "readonly would restore search, at the price of body access we promised not to use"
    )


def test_the_request_asks_for_metadata_and_names_its_headers() -> None:
    """`format=metadata` cannot return a body even if asked; the header list narrows it further."""
    url = gmail.message_url("18c0")
    assert "format=metadata" in url
    for header in gmail.METADATA_HEADERS:
        assert header.replace("-", "-") in url.replace("%2D", "-"), header
    assert "format=full" not in url and "format=raw" not in url


def test_listing_is_bounded_to_the_sent_label() -> None:
    """FR-048 — received mail is never fetched."""
    url = gmail.list_url()
    assert "labelIds=SENT" in url
    assert "INBOX" not in url


# --- the shape, unchanged ----------------------------------------------------------------


def build(entry: dict[str, object]) -> msg.Message:
    return msg.build(
        headers=gmail.headers_from(entry),
        account="personal-mail",
        provider=Provider.GMAIL,
        own_addresses=[fx.ME],
        provider_id=str(entry["id"]),
        has_attachments=gmail.has_attachment(entry),
    )


def test_a_gmail_message_becomes_the_same_record_as_any_other() -> None:
    """SC-014 — and Gmail keeps the original offset, which Graph does not."""
    from datetime import timedelta

    message = build(recorded.message(to=(fx.ANNA,), cc=(fx.BOB,)))
    record = msg.to_record(message)

    assert record.source_id == "mail:one@fixture.example"
    assert set(message.recipient_addresses) == {fx.ANNA, fx.BOB}
    assert message.sent_at.utcoffset() == timedelta(hours=1)
    assert record.payload["provider"] == "gmail"
    assert record.duration is None


def test_forbidden_fields_are_ignored_even_when_present() -> None:
    """The scope will not send these. The fixture sends them anyway."""
    entry = recorded.message(with_forbidden_fields=True, with_attachment=True)
    record = msg.to_record(build(entry))

    rendered = str(record.payload)
    assert fx.SENTINEL_BODY not in rendered
    assert fx.SENTINEL_ATTACHMENT not in rendered
    assert fx.CAROL not in rendered, "bcc must never survive"
    assert record.payload["has_attachments"] is True


def test_headers_are_limited_to_the_allow_list() -> None:
    entry = recorded.message(with_forbidden_fields=True)
    headers = gmail.headers_from(entry)
    assert set(headers) <= msg.READABLE_HEADERS
    assert "Bcc" not in headers


def test_header_names_are_matched_case_insensitively() -> None:
    """Gmail does not promise a casing, and `message-id` is common."""
    entry = recorded.message()
    entry["payload"]["headers"] = [
        {"name": "message-id", "value": "<lower@fixture.example>"},
        {"name": "DATE", "value": "Tue, 10 Mar 2026 09:14:00 +0100"},
        {"name": "from", "value": fx.ME},
        {"name": "subject", "value": "Shouting"},
    ]
    headers = gmail.headers_from(entry)
    assert headers["Message-ID"] == "<lower@fixture.example>"
    assert headers["Subject"] == "Shouting"


# --- incremental, and losing the cursor ---------------------------------------------------


def test_a_first_run_lists_and_fetches_each_message() -> None:
    client = Scripted(
        listing=recorded.listing("a", "b"),
        messages={
            "a": recorded.message(gmail_id="a", message_id="a@x", subject="One"),
            "b": recorded.message(gmail_id="b", message_id="b@x", subject="Two"),
        },
    )
    results = read_all(client)

    subjects = [h.get("Subject") for h, _, _ in results if h]
    assert subjects == ["One", "Two"]
    assert any("labelIds=SENT" in url for url in client.urls)


def test_the_history_id_comes_back_for_the_next_run() -> None:
    client = Scripted(
        listing=recorded.listing("a"),
        messages={"a": recorded.message(gmail_id="a", message_id="a@x")},
    )
    points = [point for _, _, point in read_all(client) if point]
    assert points == [recorded.HISTORY_ID]


def test_a_second_run_asks_history_rather_than_listing_everything() -> None:
    client = Scripted(
        history=recorded.history("c"),
        messages={"c": recorded.message(gmail_id="c", message_id="c@x", subject="New")},
    )
    results = read_all(client, resumption_point="123")

    assert any("/history" in url for url in client.urls)
    assert not any("labelIds=SENT&" in url and "/messages?" in url for url in client.urls)
    assert [h.get("Subject") for h, _, _ in results if h] == ["New"]


def test_an_expired_history_id_falls_back_to_a_full_listing() -> None:
    """Research R3 — Gmail expires history, and a 404 is documented behaviour.

    Losing the cursor must cost **time**, never data: the wider read is deduplicated by
    the store, so nothing is lost and nothing is doubled.
    """
    client = Scripted(
        listing=recorded.listing("a"),
        messages={"a": recorded.message(gmail_id="a", message_id="a@x", subject="Recovered")},
        history_status=404,
    )
    results = read_all(client, resumption_point="stale")

    assert any("/history" in url for url in client.urls), "it tried the cursor first"
    assert any("labelIds=SENT" in url for url in client.urls), "then listed everything"
    assert [h.get("Subject") for h, _, _ in results if h] == ["Recovered"]


def test_any_other_history_failure_is_not_swallowed() -> None:
    """A 403 is a permission problem, and pretending it is expiry would hide it."""
    client = Scripted(history_status=403)
    with pytest.raises(HttpStatusError):
        read_all(client, resumption_point="123")


# --- the start date, applied where the scope forces it ------------------------------------


def test_the_since_date_is_applied_client_side() -> None:
    """Research R3 — `gmail.metadata` disables the search parameter.

    Asserted rather than assumed, because the obvious implementation would put
    `after:` in a `q` parameter that this scope rejects.
    """
    client = Scripted(
        listing=recorded.listing("old", "new"),
        messages={
            "old": recorded.message(
                gmail_id="old", message_id="old@x", subject="Last year",
                sent="Tue, 10 Mar 2025 09:14:00 +0100",
            ),
            "new": recorded.message(
                gmail_id="new", message_id="new@x", subject="This year",
                sent="Tue, 10 Mar 2026 09:14:00 +0100",
            ),
        },
    )
    results = read_all(client, since=datetime(2026, 1, 1, tzinfo=UTC))

    assert [h.get("Subject") for h, _, _ in results if h] == ["This year"]
    assert not any("q=" in url for url in client.urls), (
        "the metadata scope rejects the search parameter"
    )


# --- two accounts in one run (T061) -------------------------------------------------


def test_a_gmail_account_authorises_against_google_not_microsoft() -> None:
    """A wrong endpoint would send a Google code to Microsoft, or the reverse."""
    from iknowwhatyoudid.cli import mail_commands

    google = mail_commands.endpoints_for("mail.gmail", "")
    microsoft = mail_commands.endpoints_for("mail.outlook", "")

    assert "google" in google.authorise
    assert "microsoftonline" in microsoft.authorise
    assert google.token != microsoft.token
    assert mail_commands.scopes_for("mail.gmail") == gmail.SCOPES
    assert mail_commands.scopes_for("mail.outlook") != gmail.SCOPES


def test_each_provider_can_only_reach_its_own_hosts() -> None:
    """FR-019 — the allow-list is built per account, not once for everything."""
    from iknowwhatyoudid.cli import mail_commands

    google = mail_commands.hosts_for("mail.gmail")
    microsoft = mail_commands.hosts_for("mail.outlook")

    assert gmail.GMAIL_HOST in google
    assert graph.GRAPH_HOST not in google, "a Gmail account cannot reach Microsoft"
    assert gmail.GMAIL_HOST not in microsoft, "and the reverse"


def test_the_same_correspondent_in_two_accounts_reaches_one_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-030 — two accounts stay distinct, but a mapping rule spans both.

    Run through archives rather than live APIs, because what is being tested is what
    happens *after* reading, which is provider-agnostic by design.
    """
    import sqlite3

    work = fx.Mailbox()
    work.add(fx.message("From work", to=(fx.ANNA,), message_id="<w@x>"))
    personal = fx.Mailbox()
    personal.add(
        fx.message("From personal", to=(fx.ANNA,), message_id="<p@x>", offset_seconds=60)
    )

    (tmp_path / "config.toml").write_text(
        f'[[source]]\nname = "work"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{work.write_mbox(tmp_path / "w.mbox").as_posix()}"]\n'
        f'\n[[source]]\nname = "personal"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{personal.write_mbox(tmp_path / "p.mbox").as_posix()}"]\n',
        encoding="utf-8",
    )
    (tmp_path / "projects.toml").write_text(
        '[[project]]\nname = "acme"\ncorrespondents = ["anna@acme.example"]\n',
        encoding="utf-8",
    )

    from iknowwhatyoudid.cli.main import main

    main(
        ["ingest", "--config", str(tmp_path / "config.toml"),
         "--projects", str(tmp_path / "projects.toml"),
         "--store", str(tmp_path / "store.db")]
    )
    capsys.readouterr()

    connection = sqlite3.connect(tmp_path / "store.db")
    rows = connection.execute(
        "SELECT json_extract(r.payload, '$.account'), p.name "
        "FROM derived_attribution d "
        "JOIN raw_record r ON r.id = d.record_id "
        "JOIN user_project p ON p.id = d.project_id"
    ).fetchall()
    connection.close()

    assert {row[0] for row in rows} == {"work", "personal"}, "accounts stay distinct"
    assert {row[1] for row in rows} == {"acme"}, "one rule reached both"


def test_one_account_failing_does_not_stop_the_other(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-017, SC-011 — and the failed one is named, not silently skipped."""
    good = fx.Mailbox()
    good.add(fx.message("Readable", to=(fx.ANNA,)))
    (tmp_path / "config.toml").write_text(
        f'[[source]]\nname = "good"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{good.write_mbox(tmp_path / "g.mbox").as_posix()}"]\n'
        f'\n[[source]]\nname = "broken"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{(tmp_path / "absent.mbox").as_posix()}"]\n',
        encoding="utf-8",
    )

    from iknowwhatyoudid.cli.main import main

    main(
        ["ingest", "--config", str(tmp_path / "config.toml"),
         "--store", str(tmp_path / "store.db")]
    )
    out = capsys.readouterr().out

    assert "1 records" in out or "1 record" in out, "the good account still ingested"
    assert "broken" in out, "the failed one is named"
    assert "absent.mbox" in out, "and so is what went wrong"
