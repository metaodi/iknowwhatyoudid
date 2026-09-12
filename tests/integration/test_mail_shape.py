"""One shape, whatever produced it (FR-020 to FR-028, SC-004, SC-014).

The assertions here are written once and run against every provider. If any provider
needs its own version of one, FR-028 has been broken.
"""

from __future__ import annotations

import ast
import email
import inspect
from datetime import timedelta
from typing import Any

import pytest

from fixtures.mail import messages as fx
from iknowwhatyoudid.mail import message as msg
from iknowwhatyoudid.mail.message import MessageRejected, Provider


def headers_of(built: fx.Built) -> dict[str, str]:
    """Read a fixture back as the header dict a provider module would produce."""
    parsed = email.message_from_bytes(built.raw)
    return {
        name: str(parsed[name])
        for name in ("Message-ID", "Date", "From", "To", "Cc", "Subject", "Bcc")
        if parsed[name] is not None
    }


def build(built: fx.Built, **kwargs: Any) -> msg.Message:
    return msg.build(
        headers=headers_of(built),
        account=kwargs.pop("account", "test-account"),
        provider=kwargs.pop("provider", Provider.MBOX),
        own_addresses=kwargs.pop("own_addresses", [fx.ME]),
        **kwargs,
    )


# --- the instant ------------------------------------------------------------------


def test_the_original_offset_is_preserved() -> None:
    """FR-022 — a message sent at 9am local time must read as 9am.

    Storing it as UTC would be lossless for the instant and lossy for the day: 00:30
    +0200 is the previous day in UTC, and a timesheet line would land on the wrong date.
    """
    message = build(fx.message("Morning note", tz_offset="+0100"))
    assert message.sent_at.utcoffset() == timedelta(hours=1)
    assert message.sent_at.hour == 9


def test_a_message_with_no_date_is_rejected_by_identifier() -> None:
    """Never given an invented time — only a missing message gets noticed."""
    built = fx.message("No date", date_header=False)
    with pytest.raises(MessageRejected) as raised:
        build(built)
    assert raised.value.identifier == built.message_id
    assert "Date" in raised.value.reason


def test_a_message_with_an_unparseable_date_is_rejected() -> None:
    with pytest.raises(MessageRejected):
        build(fx.message("Bad date", date_header="not a date"))


# --- the subject --------------------------------------------------------------------


def test_an_empty_subject_stays_empty() -> None:
    """A blank subject is information about the kind of message it was."""
    assert build(fx.message("")).subject == ""


def test_an_encoded_word_subject_is_decoded() -> None:
    assert build(fx.message("Grüße und Küsse")).subject == "Grüße und Küsse"


# --- recipients ---------------------------------------------------------------------


def test_a_broadcast_keeps_every_recipient() -> None:
    """Truncating would hide that this was a broadcast rather than an exchange."""
    many = tuple(f"p{i}@acme.example" for i in range(50))
    assert len(build(fx.message("Broadcast", to=many)).recipients) == 50


def test_cc_is_recorded_with_its_role() -> None:
    message = build(fx.message("With a copy", to=(fx.ANNA,), cc=(fx.BOB,)))
    roles = {r.address: r.role for r in message.recipients}
    assert roles[fx.ANNA] == msg.Role.TO
    assert roles[fx.BOB] == msg.Role.CC


def test_bcc_is_never_recorded() -> None:
    """It names people the other recipients were not told about.

    Attribution never needs it, so it is not stored. The fixture carries one precisely so
    this can be asserted rather than assumed.
    """
    built = fx.message("Secretly copied", to=(fx.ANNA,), bcc=(fx.CAROL,))
    assert "Bcc" in headers_of(built), "the fixture really does carry one"

    message = build(built)
    assert fx.CAROL not in message.recipient_addresses
    assert fx.CAROL not in str(msg.to_record(message).payload)


# --- what must never be stored ------------------------------------------------------


def test_no_body_reaches_the_record() -> None:
    """FR-023 — asserted on the payload, not on the code's intentions."""
    message = build(fx.message("Has a body"))
    assert fx.SENTINEL_BODY not in str(msg.to_record(message).payload)


def test_no_attachment_content_or_name_reaches_the_record() -> None:
    """FR-024 — the fact of an attachment may be recorded; nothing about it may be."""
    built = fx.message("With attachment", with_attachment=True)
    record = msg.to_record(build(built, has_attachments=True))
    assert record.payload["has_attachments"] is True
    assert fx.SENTINEL_ATTACHMENT not in str(record.payload)


def test_no_duration_is_ever_set() -> None:
    """FR-025, SC-005 — a message is a point in time."""
    record = msg.to_record(build(fx.message("Anything")))
    assert record.duration is None
    assert "duration" not in record.payload


def test_the_header_dict_has_no_place_to_put_a_body() -> None:
    """The structural half of FR-023.

    `build` reads six named headers. There is no key a body could arrive under, so the
    guarantee does not depend on anyone remembering to leave one out.
    """
    assert msg.READABLE_HEADERS == {
        "Message-ID", "Date", "From", "To", "Cc", "Subject",
    }, "the allow-list changed; a body or an attachment may now have a way in"


def test_a_provider_cannot_widen_what_is_read() -> None:
    """The allow-list is applied, not merely declared.

    A provider module that grew careless and passed a body along would find it dropped
    here rather than stored — the guarantee does not depend on four provider modules each
    remembering.
    """
    built = fx.message("Careless provider")
    headers = headers_of(built)
    headers["Body"] = fx.SENTINEL_BODY
    headers["bodyPreview"] = fx.SENTINEL_BODY

    message = msg.build(
        headers=headers,
        account="a",
        provider=Provider.GRAPH,
        own_addresses=[fx.ME],
    )
    assert fx.SENTINEL_BODY not in str(msg.to_record(message).payload)


# --- identity -----------------------------------------------------------------------


def test_identity_is_the_message_id_not_the_providers() -> None:
    """Research R10 — the same message from two sources is one record."""
    built = fx.message("Sent once", message_id="<shared@fixture.example>")
    from_graph = build(built, provider=Provider.GRAPH, provider_id="AAMkAGI2")
    from_archive = build(built, provider=Provider.MBOX)
    assert from_graph.source_id == from_archive.source_id
    assert from_graph.source_id == "mail:shared@fixture.example"


def test_a_missing_message_id_falls_back_visibly() -> None:
    """A weaker identifier is marked as one rather than passed off as the real thing."""
    headers = headers_of(fx.message("No id"))
    del headers["Message-ID"]
    message = msg.build(
        headers=headers,
        account="a",
        provider=Provider.GRAPH,
        own_addresses=[fx.ME],
        provider_id="AAMkAGI2",
    )
    assert message.message_id_is_derived is True
    assert message.source_id == "mail:graph:aamkagi2"


# --- only sent mail -----------------------------------------------------------------


def test_a_message_from_someone_else_is_refused() -> None:
    """FR-048 — reaching here means a provider returned outside the Sent folder."""
    built = fx.message("Not mine", sender=fx.ANNA, to=(fx.ME,))
    with pytest.raises(MessageRejected) as raised:
        build(built)
    assert "not one of this account" in raised.value.reason


def test_which_of_my_addresses_sent_it_is_recorded() -> None:
    """FR-021 — useful where an account holds several, and free to record."""
    message = build(
        fx.message("From the other one", sender=fx.ME_OTHER),
        own_addresses=[fx.ME, fx.ME_OTHER],
    )
    assert message.sent_by == fx.ME_OTHER
    assert msg.to_record(message).payload["sent_by"] == fx.ME_OTHER


# --- the same assertions, every provider --------------------------------------------


@pytest.mark.parametrize("provider", list(Provider))
def test_the_shape_is_identical_whatever_produced_it(provider: Provider) -> None:
    """SC-014 — if a provider needs its own assertion, FR-028 is broken."""
    built = fx.message("[ACME] rollout", to=(fx.ANNA,), cc=(fx.BOB,))
    record = msg.to_record(build(built, provider=provider, provider_id="x"))

    assert set(record.payload) >= {
        "kind",
        "account",
        "provider",
        "message_id",
        "sent_by",
        "subject",
        "recipient_count",
        "has_attachments",
    }
    assert record.payload["kind"] == "mail_sent"
    assert record.duration is None
    assert record.source_id == f"mail:{built.message_id}"


# --- Microsoft 365 (US1) ---------------------------------------------------------------


def graph_message(**kwargs: Any) -> msg.Message:
    """One recorded Graph message, through the same `build` every provider uses."""
    from fixtures.responses import graph as recorded
    from iknowwhatyoudid.mail import graph

    entry = recorded.message(**kwargs)
    return msg.build(
        headers=graph.headers_from(entry),
        account="work-mail",
        provider=Provider.GRAPH,
        own_addresses=[fx.ME],
        provider_id=str(entry["id"]),
        has_attachments=bool(entry.get("hasAttachments")),
    )


def test_a_graph_message_becomes_a_record() -> None:
    """T027 — recipients, instant, subject and `sent_by`, from a recorded response."""
    message = graph_message(
        message_id="one@fixture.example",
        subject="Rollout plan",
        to=(fx.ANNA,),
        cc=(fx.BOB,),
    )
    record = msg.to_record(message)

    assert record.source_id == "mail:one@fixture.example"
    assert message.subject == "Rollout plan"
    assert message.sent_by == fx.ME
    assert set(message.recipient_addresses) == {fx.ANNA, fx.BOB}
    assert record.payload["provider"] == "graph"


def test_graph_forbidden_fields_are_dropped_even_when_present() -> None:
    """T028 — the sentinel test, with the fields Graph would never send.

    `Mail.ReadBasic` does not return a body, a preview, attachments or `bcc`. The fixture
    includes all four anyway, so this proves the reader ignores them rather than merely
    never receiving them — the difference between a guarantee and a coincidence.
    """
    message = graph_message(
        message_id="two@fixture.example",
        subject="[ACME] status",
        with_forbidden_fields=True,
        has_attachments=True,
    )
    record = msg.to_record(message)

    rendered = str(record.payload)
    assert fx.SENTINEL_BODY not in rendered
    assert fx.SENTINEL_ATTACHMENT not in rendered
    assert fx.CAROL not in rendered, "bcc must never survive"
    assert record.payload["has_attachments"] is True, "the fact, and only the fact"


def test_graph_headers_never_include_a_forbidden_key() -> None:
    """The structural half: `headers_from` cannot emit a key outside the allow-list."""
    from fixtures.responses import graph as recorded
    from iknowwhatyoudid.mail import graph

    entry = recorded.message(
        message_id="three@fixture.example", subject="x", with_forbidden_fields=True
    )
    headers = graph.headers_from(entry)

    assert set(headers) <= msg.READABLE_HEADERS
    assert "Bcc" not in headers


def test_both_date_formats_are_understood() -> None:
    """An archive sends RFC 5322; Graph and Gmail send ISO 8601."""
    rfc = msg.parse_instant("Tue, 10 Mar 2026 09:14:00 +0100", "x")
    iso = msg.parse_instant("2026-03-10T08:14:00Z", "x")

    assert rfc.utcoffset() == timedelta(hours=1), "the sender's own offset survives"
    assert iso.utcoffset() == timedelta(0)
    assert rfc == iso, "the same moment, expressed two ways"


def test_a_date_without_any_zone_is_still_refused() -> None:
    """Hey's `thread read` returns exactly this shape; it must not become a record."""
    with pytest.raises(MessageRejected):
        msg.parse_instant("2026-08-27T21:07", "x")
