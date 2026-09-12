"""Recorded Microsoft Graph responses.

Shaped as the documented `/messages/delta` response: a `value` array, and either an
`@odata.nextLink` to continue a page chain or an `@odata.deltaLink` to resume next time.

Every body here carries a sentinel, in a field Graph would **never** send under
`Mail.ReadBasic`. That is deliberate: if a sentinel ever reaches the store, either the
scope was widened or the reader started taking fields it was not given, and both are
worth failing loudly for.
"""

from __future__ import annotations

from typing import Any

from fixtures.mail import messages as fx

DELTA_LINK = "https://graph.microsoft.com/v1.0/me/mailFolders/sentitems/messages/delta?$deltatoken=RECORDED"
NEXT_LINK = "https://graph.microsoft.com/v1.0/me/mailFolders/sentitems/messages/delta?$skiptoken=RECORDED"


def message(
    *,
    message_id: str,
    subject: str,
    sent: str = "2026-03-10T08:14:00Z",
    sender: str = fx.ME,
    to: tuple[str, ...] = (fx.ANNA,),
    cc: tuple[str, ...] = (),
    has_attachments: bool = False,
    graph_id: str = "AAMkAGI2",
    with_forbidden_fields: bool = False,
) -> dict[str, Any]:
    """One message as Graph returns it."""
    payload: dict[str, Any] = {
        "id": graph_id,
        "internetMessageId": f"<{message_id}>",
        "sentDateTime": sent,
        "subject": subject,
        "hasAttachments": has_attachments,
        "from": {"emailAddress": {"name": "Test Person", "address": sender}},
        "toRecipients": [
            {"emailAddress": {"name": "", "address": address}} for address in to
        ],
        "ccRecipients": [
            {"emailAddress": {"name": "", "address": address}} for address in cc
        ],
    }
    if with_forbidden_fields:
        # Graph will not send these under `Mail.ReadBasic`. They are here so a test can
        # prove the reader ignores them even when handed them.
        payload["body"] = {"contentType": "text", "content": fx.SENTINEL_BODY}
        payload["bodyPreview"] = fx.SENTINEL_BODY
        payload["attachments"] = [{"name": fx.SENTINEL_ATTACHMENT, "size": 12}]
        payload["bccRecipients"] = [
            {"emailAddress": {"name": "", "address": fx.CAROL}}
        ]
    return payload


def page(
    *messages: dict[str, Any],
    next_link: str | None = None,
    delta_link: str | None = DELTA_LINK,
) -> dict[str, Any]:
    body: dict[str, Any] = {"value": list(messages)}
    if next_link:
        body["@odata.nextLink"] = next_link
    elif delta_link:
        body["@odata.deltaLink"] = delta_link
    return body


def removed(graph_id: str) -> dict[str, Any]:
    """How a delta reports a message that has gone."""
    return {"id": graph_id, "@removed": {"reason": "deleted"}}


# --- a simple scripted conversation, for tests that just need pages -------------------

_QUEUE: list[dict[str, Any]] = []


def reset(*pages: dict[str, Any]) -> None:
    """Queue the pages a spy client should return, in order."""
    global _QUEUE
    _QUEUE = list(pages) if pages else [
        page(
            message(message_id="one@fixture.example", subject="Rollout plan"),
            message(
                message_id="two@fixture.example",
                subject="[ACME] status",
                graph_id="AAMkAGI3",
                with_forbidden_fields=True,
            ),
        )
    ]


def next_page() -> dict[str, Any]:
    if not _QUEUE:
        return page(delta_link=DELTA_LINK)
    return _QUEUE.pop(0)
