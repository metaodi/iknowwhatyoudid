"""Reading a Microsoft 365 account through Graph (research R5).

Three decisions carry this module, and each is a fact about the request rather than a rule
the code has to remember:

* **`Mail.ReadBasic`** returns messages *without body or attachments*. FR-023 and FR-024
  are therefore enforced by the token: no code path can store a body, because none arrives.
  `Mail.Read` would also work and is broader; `Mail.ReadWrite` is never requested.
* **The Sent Items folder** is what is read, so received mail is never fetched at all
  rather than fetched and thrown away (FR-048). The requirement holds even if the
  filtering below is wrong.
* **`$select`** names the seven fields explicitly. Widening what the server returns then
  means editing a list a reviewer reads, rather than deleting a filter they might miss.

Incremental reads use Graph's own `delta` chain, so resumption is the server's problem
rather than ours (FR-015, FR-016).

This module never touches the store, projects or the CLI. It yields header dicts.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Protocol

from ..errors import MailReadError
from .message import READABLE_HEADERS

#: The narrowest read-only authorisation Graph offers for mail, plus the grant that lets
#: a refresh token be issued. Asserted in `test_mail_readonly.py`.
SCOPES: tuple[str, ...] = ("Mail.ReadBasic", "offline_access")

#: Exactly what is asked for. Nothing here can carry a body or an attachment.
SELECT: tuple[str, ...] = (
    "internetMessageId",
    "sentDateTime",
    "from",
    "toRecipients",
    "ccRecipients",
    "subject",
    "hasAttachments",
)

GRAPH_HOST = "graph.microsoft.com"
LOGIN_HOST = "login.microsoftonline.com"

#: Read-only by construction: `delta` on a folder only ever reports what changed.
SENT_FOLDER_PATH = "/me/mailFolders/sentitems/messages/delta"
SENT_FOLDER_URL = f"https://{GRAPH_HOST}/v1.0{SENT_FOLDER_PATH}"

#: Graph caps a delta page; asking for more is ignored, asking for fewer costs round trips.
PAGE_SIZE = 100

#: Beyond this a run is looping rather than paging, and should fail rather than spin.
MAX_PAGES = 1000


class Fetcher(Protocol):
    """The slice of `net.http.Client` this module uses. GET only, deliberately."""

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> Any: ...


def starting_url(since: datetime | None, resumption_point: str | None) -> str:
    """Where to begin: a stored delta link, or a fresh window.

    A delta link already encodes everything — folder, selection, position — so it is used
    verbatim. Graph requires that.
    """
    if resumption_point:
        return resumption_point

    query = [f"$select={','.join(SELECT)}", f"$top={PAGE_SIZE}"]
    if since is not None:
        # `delta` accepts a filter only on the first call of a chain; afterwards the link
        # carries it. An invalid instant here would silently widen the read, so it is
        # formatted rather than interpolated from user text.
        stamp = since.astimezone().strftime("%Y-%m-%dT%H:%M:%SZ")
        query.append(f"$filter=sentDateTime ge {stamp}")
    return f"{SENT_FOLDER_URL}?{'&'.join(query)}"


def headers_from(entry: dict[str, Any]) -> dict[str, str]:
    """One Graph message as the header dict `message.build` expects.

    Only `READABLE_HEADERS` are produced. A Graph response carrying `body`, `bodyPreview`
    or `bccRecipients` — which `Mail.ReadBasic` will not send, but a widened scope would —
    has no route through this function.
    """
    headers: dict[str, str] = {}

    identifier = entry.get("internetMessageId")
    if isinstance(identifier, str) and identifier.strip():
        headers["Message-ID"] = identifier

    sent = entry.get("sentDateTime")
    if isinstance(sent, str) and sent.strip():
        headers["Date"] = sent

    sender = _address_of(entry.get("from"))
    if sender:
        headers["From"] = sender

    for key, header in (("toRecipients", "To"), ("ccRecipients", "Cc")):
        addresses = _addresses_of(entry.get(key))
        if addresses:
            headers[header] = ", ".join(addresses)

    subject = entry.get("subject")
    if isinstance(subject, str):
        headers["Subject"] = subject

    assert set(headers) <= READABLE_HEADERS  # noqa: S101 — a guard, not a check
    return headers


def _address_of(recipient: Any) -> str | None:
    if not isinstance(recipient, dict):
        return None
    inner = recipient.get("emailAddress")
    if not isinstance(inner, dict):
        return None
    address = inner.get("address")
    if not isinstance(address, str) or not address.strip():
        return None
    name = inner.get("name")
    if isinstance(name, str) and name.strip():
        return f"{name} <{address}>"
    return address


def _addresses_of(recipients: Any) -> list[str]:
    if not isinstance(recipients, list):
        return []
    found = [_address_of(entry) for entry in recipients]
    return [address for address in found if address]


def read(
    client: Fetcher,
    *,
    token: str,
    since: datetime | None,
    resumption_point: str | None,
) -> Iterator[tuple[dict[str, str], bool, str | None]]:
    """Yield `(headers, has_attachments, new_resumption_point)` for each message.

    The resumption point is `None` on every message except the last of the chain, where
    it carries the `deltaLink` to store. Emitting it with the final message rather than
    returning it keeps this a generator, so a long history streams rather than
    accumulating — the fault `0003` shipped and had to correct.
    """
    url: str | None = starting_url(since, resumption_point)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    pending: tuple[dict[str, str], bool] | None = None

    for _ in range(MAX_PAGES):
        if url is None:
            break
        body = client.get(url, headers=headers)
        if not isinstance(body, dict):
            raise MailReadError(
                "Graph returned something that is not a delta page",
                remedy="Nothing was changed at the source. The account was skipped.",
            )

        for entry in body.get("value", []):
            if not isinstance(entry, dict):
                continue
            if "@removed" in entry:
                # A sweep concludes from absence, not from a tombstone; an incremental
                # run has no business acting on one. Either way it is not a message.
                continue
            if pending is not None:
                yield (*pending, None)
            pending = (headers_from(entry), bool(entry.get("hasAttachments")))

        next_link = body.get("@odata.nextLink")
        delta_link = body.get("@odata.deltaLink")
        if isinstance(next_link, str) and next_link:
            url = next_link
            continue
        if pending is not None:
            yield (*pending, delta_link if isinstance(delta_link, str) else None)
            pending = None
        elif isinstance(delta_link, str):
            # An empty page still advances the cursor, which is how "nothing changed"
            # stays cheap on the next run.
            yield ({}, False, delta_link)
        return

    raise MailReadError(
        f"Graph did not finish paging after {MAX_PAGES} pages",
        remedy="This looks like a loop rather than a long history. Nothing was changed.",
    )
