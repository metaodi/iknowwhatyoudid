"""Recorded Gmail API responses.

Shaped as `users.messages.list`, `users.messages.get` with `format=metadata`, and
`users.history.list` return them.

Every fixture carries a sentinel in a `body` field the metadata scope would never send,
so a test can prove the reader ignores it rather than merely never receiving it.
"""

from __future__ import annotations

from typing import Any

from fixtures.mail import messages as fx

HISTORY_ID = "987654"


def listing(*ids: str, history_id: str = HISTORY_ID, next_token: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "messages": [{"id": identifier, "threadId": f"t-{identifier}"} for identifier in ids],
        "resultSizeEstimate": len(ids),
        "historyId": history_id,
    }
    if next_token:
        body["nextPageToken"] = next_token
    return body


def message(
    *,
    gmail_id: str = "18c0",
    message_id: str = "one@fixture.example",
    subject: str = "Rollout plan",
    sent: str = "Tue, 10 Mar 2026 09:14:00 +0100",
    sender: str = fx.ME,
    to: tuple[str, ...] = (fx.ANNA,),
    cc: tuple[str, ...] = (),
    with_attachment: bool = False,
    with_forbidden_fields: bool = False,
) -> dict[str, Any]:
    """One message as `format=metadata` returns it.

    Note the RFC 5322 `Date`: Gmail hands back the original header here, offset and all,
    unlike Graph's UTC `sentDateTime`.
    """
    headers = [
        {"name": "Message-ID", "value": f"<{message_id}>"},
        {"name": "Date", "value": sent},
        {"name": "From", "value": sender},
        {"name": "Subject", "value": subject},
    ]
    if to:
        headers.append({"name": "To", "value": ", ".join(to)})
    if cc:
        headers.append({"name": "Cc", "value": ", ".join(cc)})

    payload: dict[str, Any] = {"mimeType": "text/plain", "headers": headers}
    if with_attachment:
        payload["mimeType"] = "multipart/mixed"
        payload["parts"] = [
            {"mimeType": "text/plain", "filename": "", "headers": []},
            {
                "mimeType": "application/pdf",
                "filename": fx.SENTINEL_ATTACHMENT,
                "headers": [],
                "body": {"attachmentId": "a1", "size": 1024},
            },
        ]
    if with_forbidden_fields:
        # `gmail.metadata` never sends these. Present so a test can prove they are
        # ignored rather than merely absent.
        payload["body"] = {"size": 42, "data": fx.SENTINEL_BODY}
        headers.append({"name": "Bcc", "value": fx.CAROL})

    return {
        "id": gmail_id,
        "threadId": f"t-{gmail_id}",
        "labelIds": ["SENT"],
        "snippet": fx.SENTINEL_BODY if with_forbidden_fields else "",
        "historyId": HISTORY_ID,
        "payload": payload,
    }


def history(*ids: str, history_id: str = HISTORY_ID) -> dict[str, Any]:
    return {
        "history": [
            {
                "id": history_id,
                "messagesAdded": [
                    {"message": {"id": identifier, "labelIds": ["SENT"]}}
                    for identifier in ids
                ],
            }
        ],
        "historyId": history_id,
    }
