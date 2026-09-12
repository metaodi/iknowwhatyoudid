"""One message, in the shape everything downstream sees (FR-020 to FR-028).

Every provider funnels through here, so a bug in normalisation is one bug rather than
four, and no provider can leak a field the others cannot supply (FR-028).

What this module refuses to do is as important as what it does:

* it never reads a body, a body preview, or an attachment's content (FR-023, FR-024);
* it never stores `Bcc`, which names people the other recipients were not told about and
  which attribution has no use for;
* it never sets a duration, because a message is a point in time and turning points into
  hours belongs to a later feature (FR-025);
* it never invents an instant. A message whose date cannot be parsed is skipped and
  reported, because a wrong time in a timesheet is worse than a missing message: only the
  missing one gets noticed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from enum import StrEnum

from ..records.model import NormalizedRecord
from .. import addresses as addr


#: The only headers any provider may hand to `build`, and the only ones it reads.
#:
#: Declared rather than implied, for the same reason `git/binary.py` declares its
#: subcommands: it turns "we never read a body" from a claim about the code into a list a
#: reviewer can check in one glance, and a test asserts that `build` reads nothing else.
#: There is no entry a body, a body preview, or an attachment could arrive under.
READABLE_HEADERS: frozenset[str] = frozenset(
    {"Message-ID", "Date", "From", "To", "Cc", "Subject"}
)


class Role(StrEnum):
    SENDER = "sender"
    TO = "to"
    CC = "cc"


class Provider(StrEnum):
    GRAPH = "graph"
    GMAIL = "gmail"
    HEY = "hey"
    MBOX = "mbox"


class MessageRejected(Exception):
    """This message cannot become a record, and why.

    Not an `IkwydError`: it is not a failure of the run, it is one message being skipped
    and named. The account still ingests everything else.
    """

    def __init__(self, identifier: str, reason: str) -> None:
        super().__init__(f"{identifier}: {reason}")
        self.identifier = identifier
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Recipient:
    address: str
    role: Role


@dataclass(frozen=True, slots=True)
class Message:
    """A message the user sent. Never one they received (FR-048)."""

    message_id: str
    message_id_is_derived: bool
    sent_at: datetime
    sender: str
    sent_by: str
    subject: str
    account: str
    provider: Provider
    recipients: tuple[Recipient, ...] = ()
    has_attachments: bool = False
    withdrawable: bool = True
    display_names: dict[str, str] = field(default_factory=dict)

    @property
    def source_id(self) -> str:
        """`mail:<message-id>` — stable across providers (research R10).

        The same message read from Graph and again from an exported archive is one
        record, because a `Message-ID` is assigned once by the sending system and travels
        with the message. A provider's own id would make it look like two.
        """
        return f"mail:{self.message_id}"

    @property
    def recipient_addresses(self) -> tuple[str, ...]:
        return tuple(r.address for r in self.recipients)


def decode_subject(raw: str | None) -> str:
    """A subject, with encoded words resolved.

    An empty subject stays empty and is never given an invented title — a blank subject
    is itself information about the kind of message it was. A subject that cannot be
    decoded keeps its replacement characters rather than failing the message, the same
    trade `0003` settled on for commit subjects.
    """
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return raw.strip()


def normalise_message_id(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().strip("<>").strip().lower()
    return cleaned or None


def parse_instant(raw: str | None, identifier: str) -> datetime:
    """The instant the message was sent, with whatever offset the source supplied.

    Two formats arrive, because two kinds of source send them:

    * **RFC 5322** (`Tue, 10 Mar 2026 09:14:00 +0100`) from anything that hands over a
      real mail header — an archive, and IMAP if it were ever used. This carries the
      sender's **original offset**, which is what FR-022 asks for.
    * **ISO 8601** (`2026-03-10T08:14:00Z`) from Microsoft Graph and the Gmail API, which
      normalise to UTC before they answer.

    The second case is a genuine shortfall against FR-022 and is recorded as a known limit
    rather than papered over: Graph's `sentDateTime` is UTC and there is no offset to
    recover. Graph *can* return `internetMessageHeaders`, which would carry the original
    `Date`, but only by fetching the whole routing header set including originating IP
    addresses — more data, and more sensitive data, than one offset is worth under
    Principle I. A later feature that renders in the user's own zone fixes the display,
    which is where the difference is actually visible.

    An instant with **no** zone at all is still refused. A wrong time in a timesheet is
    worse than a missing message: only the missing one gets noticed.
    """
    if not raw:
        raise MessageRejected(identifier, "no Date header")

    text = raw.strip()
    when: datetime | None = None

    if "," in text or text.endswith(("+0000", "-0000")) or _looks_rfc5322(text):
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            when = None

    if when is None:
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            when = None

    if when is None:
        raise MessageRejected(identifier, f"unparseable date: {raw!r}")
    if when.tzinfo is None:
        raise MessageRejected(identifier, "the date carries no offset from UTC")
    return when


def _looks_rfc5322(text: str) -> bool:
    """A mail date starts with a weekday or a day number, never with a four-digit year."""
    head = text.split()[0] if text.split() else ""
    return not (len(head) >= 4 and head[:4].isdigit())


def build(
    *,
    headers: dict[str, str],
    account: str,
    provider: Provider,
    own_addresses: list[str],
    provider_id: str | None = None,
    has_attachments: bool = False,
    withdrawable: bool = True,
) -> Message:
    """Turn a provider's raw headers into a message, or reject it saying why.

    `headers` carries only `READABLE_HEADERS`. Anything else a provider passes is
    discarded here rather than trusted, so a provider module that later grows careless
    cannot widen what is stored.
    """
    headers = {k: v for k, v in headers.items() if k in READABLE_HEADERS}
    identifier = normalise_message_id(headers.get("Message-ID"))
    derived = False
    if identifier is None:
        if not provider_id:
            raise MessageRejected("<unknown>", "no Message-ID and no provider identifier")
        identifier = f"{provider.value}:{provider_id}".lower()
        derived = True

    sender = addr.normalise(headers.get("From", ""))
    if not sender:
        raise MessageRejected(identifier, "no From header")

    own = {addr.normalise(a) for a in own_addresses}
    if sender not in own:
        # Only mail the user sent is recorded (FR-048). Reaching here means a provider
        # returned something outside the Sent folder, which is worth refusing rather
        # than quietly storing.
        raise MessageRejected(
            identifier, f"sender {sender} is not one of this account's addresses"
        )

    sent_at = parse_instant(headers.get("Date"), identifier)

    recipients: list[Recipient] = []
    names: dict[str, str] = {}
    for header, role in (("To", Role.TO), ("Cc", Role.CC)):
        raw = headers.get(header)
        if not raw:
            continue
        for one in addr.parse_list(raw):
            recipients.append(Recipient(one, role))
    for header in ("From", "To", "Cc"):
        raw = headers.get(header)
        if not raw:
            continue
        for name, address in getaddresses([raw]):
            normalised = addr.normalise(address)
            if name.strip() and normalised:
                names[normalised] = decode_subject(name)

    return Message(
        message_id=identifier,
        message_id_is_derived=derived,
        sent_at=sent_at,
        sender=sender,
        sent_by=sender,
        subject=decode_subject(headers.get("Subject")),
        account=account,
        provider=provider,
        recipients=tuple(recipients),
        has_attachments=has_attachments,
        withdrawable=withdrawable,
        display_names=names,
    )


def to_record(message: Message) -> NormalizedRecord:
    """The store's shape. No duration, ever (FR-025)."""
    payload: dict[str, object] = {
        "kind": "mail_sent",
        "account": message.account,
        "provider": message.provider.value,
        "message_id": message.message_id,
        "message_id_is_derived": message.message_id_is_derived,
        "sent_by": message.sent_by,
        "subject": message.subject,
        "recipient_count": len(message.recipients),
        "has_attachments": message.has_attachments,
        # The addresses are also lifted into `raw_correspondent`, but they are kept here
        # because `sources/run.py` is source-agnostic and sees only records: a record has
        # to carry everything needed to rebuild the tables from it. It is the same
        # argument `_record_repositories` makes for git — driving the index from the
        # record means the index cannot disagree with what was stored, and Principle IV's
        # "delete the database and re-ingest" reproduces both.
        "recipients": [[r.address, r.role.value] for r in message.recipients],
        "display_names": message.display_names,
    }
    if not message.withdrawable:
        # An archive is one snapshot at one moment; its silence about a message proves
        # nothing about the mailbox. The store honours this flag (research R13).
        payload["withdrawable"] = False

    return NormalizedRecord(
        source_id=message.source_id,
        occurred=message.sent_at,
        title=message.subject,
        payload=payload,
        duration=None,
    )
