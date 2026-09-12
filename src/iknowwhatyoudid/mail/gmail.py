"""Reading a Gmail account through the Gmail API (research R2, R3).

**Not IMAP**, and the reason is Principle II rather than preference. Gmail's IMAP needs the
scope `https://mail.google.com/`, which grants full mailbox access *including send and
delete*. Choosing it would mean holding a credential that could destroy the thing we
promised only to observe, and no amount of careful client code makes that acceptable —
the guarantee would rest on our restraint rather than on what the token can do.

`gmail.metadata` grants **headers and labels only**. No body, no attachments. FR-023 and
FR-024 become facts about the token.

Two consequences of that scope, both from research R3:

* **Search is unavailable.** `q="in:sent after:…"` cannot be used, so the start date is
  applied client-side on a first run. Listing by label is supported and is what bounds the
  read to sent mail.
* **`format=metadata` cannot return a body even if asked**, and the header list is named
  explicitly on top of that.

Incremental runs use `users.history.list` from a stored `historyId`. Gmail expires old
history, so a `404` is expected rather than exceptional: it falls back to a full listing,
which the store deduplicates.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Protocol

from ..errors import MailReadError
from .message import READABLE_HEADERS

#: Headers and labels only. The narrowest read-only scope Gmail offers for this purpose.
SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/gmail.metadata",)

GMAIL_HOST = "gmail.googleapis.com"
OAUTH_HOST = "oauth2.googleapis.com"
ACCOUNTS_HOST = "accounts.google.com"

_BASE = f"https://{GMAIL_HOST}/gmail/v1/users/me"

#: The label that *is* the sent folder. Asking by label means received mail is never
#: fetched, rather than fetched and discarded (FR-048).
SENT_LABEL = "SENT"

#: Exactly which headers `format=metadata` should return. The scope already forbids a
#: body; naming these keeps the response to what a record needs.
METADATA_HEADERS: tuple[str, ...] = ("Message-ID", "Date", "From", "To", "Cc", "Subject")

PAGE_SIZE = 100
MAX_PAGES = 1000


class Fetcher(Protocol):
    def get(self, url: str, *, headers: dict[str, str] | None = None) -> Any: ...


def list_url(page_token: str | None = None) -> str:
    query = {"labelIds": SENT_LABEL, "maxResults": str(PAGE_SIZE)}
    if page_token:
        query["pageToken"] = page_token
    return f"{_BASE}/messages?{urllib.parse.urlencode(query)}"


def message_url(message_id: str) -> str:
    query = [("format", "metadata")]
    query += [("metadataHeaders", header) for header in METADATA_HEADERS]
    return f"{_BASE}/messages/{message_id}?{urllib.parse.urlencode(query)}"


def history_url(start_history_id: str, page_token: str | None = None) -> str:
    query = {
        "startHistoryId": start_history_id,
        "labelId": SENT_LABEL,
        "historyTypes": "messageAdded",
        "maxResults": str(PAGE_SIZE),
    }
    if page_token:
        query["pageToken"] = page_token
    return f"{_BASE}/history?{urllib.parse.urlencode(query)}"


def headers_from(payload: dict[str, Any]) -> dict[str, str]:
    """One Gmail message as the header dict `message.build` expects.

    Gmail returns headers as a list of `{name, value}`. Only the allow-list is kept, and
    the comparison is case-insensitive because Gmail does not promise a casing.
    """
    inner = payload.get("payload")
    if not isinstance(inner, dict):
        return {}

    wanted = {header.casefold(): header for header in READABLE_HEADERS}
    found: dict[str, str] = {}
    for entry in inner.get("headers", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).casefold()
        canonical = wanted.get(name)
        if canonical and entry.get("value") is not None:
            found[canonical] = str(entry["value"])
    return found


def has_attachment(payload: dict[str, Any]) -> bool:
    """Whether the message carried one — the fact, and nothing about it (FR-024).

    Under `gmail.metadata` the part structure comes back without data, which is exactly
    enough to answer this and not enough to store anything.
    """
    inner = payload.get("payload")
    if not isinstance(inner, dict):
        return False

    def walk(part: dict[str, Any]) -> bool:
        if part.get("filename"):
            return True
        for child in part.get("parts", []):
            if isinstance(child, dict) and walk(child):
                return True
        return False

    return walk(inner)


def read(
    client: Fetcher,
    *,
    token: str,
    since: datetime | None,
    resumption_point: str | None,
) -> Iterator[tuple[dict[str, str], bool, str | None]]:
    """Yield `(headers, has_attachments, new_history_id)` for each sent message.

    The history id is carried on the **first** message rather than the last, because
    Gmail reports it per message and the newest one is what a later run resumes from.
    """
    auth = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    if resumption_point:
        identifiers, newest = _incremental(client, auth, resumption_point)
    else:
        identifiers, newest = _full(client, auth)

    emitted_point = False
    for identifier in identifiers:
        payload = client.get(message_url(identifier), headers=auth)
        if not isinstance(payload, dict):
            continue

        headers = headers_from(payload)
        if since is not None and not _at_or_after(headers.get("Date"), since):
            # The metadata scope disables the search parameter, so the start date is
            # applied here rather than server-side (research R3). Headers are small, and
            # every later run is driven by `historyId`, so this costs the first run only.
            continue

        point = None
        if not emitted_point and newest:
            point = newest
            emitted_point = True
        yield headers, has_attachment(payload), point

    if not emitted_point and newest:
        yield {}, False, newest


def _at_or_after(raw: str | None, since: datetime) -> bool:
    from .message import parse_instant

    if not raw:
        return True
    try:
        return parse_instant(raw, "filter") >= since
    except Exception:  # noqa: BLE001 — an unparseable date is the shape's problem, not ours
        return True


def _full(client: Fetcher, auth: dict[str, str]) -> tuple[list[str], str | None]:
    """Every message with the SENT label, newest first."""
    identifiers: list[str] = []
    newest: str | None = None
    page_token: str | None = None

    for _ in range(MAX_PAGES):
        body = client.get(list_url(page_token), headers=auth)
        if not isinstance(body, dict):
            raise MailReadError("Gmail returned something that is not a message list")
        for entry in body.get("messages", []):
            if isinstance(entry, dict) and entry.get("id"):
                identifiers.append(str(entry["id"]))
        newest = str(body.get("historyId")) if body.get("historyId") else newest
        page_token = body.get("nextPageToken")
        if not page_token:
            return identifiers, newest

    raise MailReadError(f"Gmail did not finish paging after {MAX_PAGES} pages")


def _incremental(
    client: Fetcher, auth: dict[str, str], start: str
) -> tuple[list[str], str | None]:
    """What has been added since `start`.

    Gmail expires old history. A `404` here is documented behaviour, not a fault, and the
    answer is to list everything again — the store deduplicates by `source_id`, so the
    cost is time rather than correctness.
    """
    from ..net.http import HttpStatusError

    identifiers: list[str] = []
    newest: str | None = None
    page_token: str | None = None

    for _ in range(MAX_PAGES):
        try:
            body = client.get(history_url(start, page_token), headers=auth)
        except HttpStatusError as exc:
            if exc.status == 404:
                return _full(client, auth)
            raise
        if not isinstance(body, dict):
            raise MailReadError("Gmail returned something that is not a history page")

        for entry in body.get("history", []):
            if not isinstance(entry, dict):
                continue
            for added in entry.get("messagesAdded", []):
                if not isinstance(added, dict):
                    continue
                message = added.get("message")
                if isinstance(message, dict) and message.get("id"):
                    if SENT_LABEL in (message.get("labelIds") or [SENT_LABEL]):
                        identifiers.append(str(message["id"]))

        newest = str(body.get("historyId")) if body.get("historyId") else newest
        page_token = body.get("nextPageToken")
        if not page_token:
            return identifiers, newest

    raise MailReadError(f"Gmail did not finish paging after {MAX_PAGES} pages")
