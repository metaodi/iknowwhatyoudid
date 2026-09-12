"""Builders for fixture mail.

Every message a test reads is assembled here, in `tmp_path`. The constitution forbids
testing connector logic against the developer's own mailbox, and this is the feature
most likely to be pointed at one by accident.

Two sentinels run through everything. `SENTINEL_BODY` is planted in every body and
`SENTINEL_ATTACHMENT` names every attachment; `find_sentinels` then searches an entire
store and the log for either. That is how FR-023 and FR-024 are asserted — not by
checking that the code looks careful, but by looking for the text afterwards.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

#: Planted in every fixture body. If this ever reaches the store, FR-023 is broken.
SENTINEL_BODY = "SENTINEL-BODY-MUST-NEVER-BE-STORED"

#: Names every fixture attachment. If this ever reaches the store, FR-024 is broken.
SENTINEL_ATTACHMENT = "SENTINEL-ATTACHMENT.pdf"

ME_NAME = "Test Person"
ME = "me@example.com"
ME_OTHER = "me.other@example.com"

ANNA = "anna@acme.example"
OPS = "ops@mail.acme.example"
BOB = "bob@northwind.example"
CAROL = "carol@northwind.example"

#: Kept deterministic so tests can assert on exact instants. 2026-03-10T09:14:00+01:00.
BASE_EPOCH = 1_773_130_440


@dataclass(frozen=True, slots=True)
class Built:
    """One fixture message, and the identifier a test will assert on."""

    message_id: str
    raw: bytes
    subject: str
    sender: str
    to: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()


@dataclass(slots=True)
class Mailbox:
    """A set of fixture messages, writable as an mbox and readable as raw headers."""

    messages: list[Built] = field(default_factory=list)

    def add(self, built: Built) -> Built:
        self.messages.append(built)
        return built

    def write_mbox(self, path: Path) -> Path:
        """Write a real mbox file — `From ` separator lines and all."""
        with path.open("wb") as handle:
            for built in self.messages:
                handle.write(b"From " + built.sender.encode("ascii") + b" Tue Mar 10 09:14:00 2026\n")
                handle.write(built.raw.replace(b"\nFrom ", b"\n>From "))
                handle.write(b"\n\n")
        return path


def message(
    subject: str,
    *,
    sender: str = ME,
    to: tuple[str, ...] = (ANNA,),
    cc: tuple[str, ...] = (),
    bcc: tuple[str, ...] = (),
    offset_seconds: int = 0,
    tz_offset: str = "+0100",
    message_id: str | None = None,
    with_attachment: bool = False,
    body: str | None = None,
    sender_name: str = ME_NAME,
    date_header: str | None | bool = None,
) -> Built:
    """One message, with a body that must never be stored.

    `date_header` is three-valued deliberately: None means "generate one", a string means
    "use exactly this" (for testing an unparseable date), and False means "omit it".
    """
    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = f"{sender_name} <{sender}>" if sender_name else sender
    if to:
        email["To"] = ", ".join(to)
    if cc:
        email["Cc"] = ", ".join(cc)
    if bcc:
        # Present in the fixture precisely so a test can assert it is never stored.
        email["Bcc"] = ", ".join(bcc)

    if date_header is False:
        pass
    elif isinstance(date_header, str):
        email["Date"] = date_header
    else:
        email["Date"] = _formatted_date(offset_seconds, tz_offset)

    identifier = message_id or make_msgid(domain="fixture.example")
    email["Message-ID"] = identifier

    email.set_content(body if body is not None else f"Hello.\n\n{SENTINEL_BODY}\n")
    if with_attachment:
        email.add_attachment(
            b"%PDF-1.4 fixture",
            maintype="application",
            subtype="pdf",
            filename=SENTINEL_ATTACHMENT,
        )

    return Built(
        message_id=identifier.strip("<>").lower(),
        raw=email.as_bytes(),
        subject=subject,
        sender=sender,
        to=to,
        cc=cc,
    )


def _formatted_date(offset_seconds: int, tz_offset: str) -> str:
    """An RFC 5322 date with an explicit offset, so FR-022 can be asserted."""
    from datetime import datetime, timedelta, timezone

    sign = 1 if tz_offset[0] == "+" else -1
    hours, minutes = int(tz_offset[1:3]), int(tz_offset[3:5])
    zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
    when = datetime.fromtimestamp(BASE_EPOCH + offset_seconds, tz=zone)
    return format_datetime(when)


# --- ready-made mailboxes -------------------------------------------------------------


def sent_and_received(sender_is_me: str = ME) -> Mailbox:
    """Both directions, so "only sent mail" can be asserted rather than assumed."""
    box = Mailbox()
    box.add(message("Rollout plan", sender=sender_is_me, to=(ANNA,)))
    box.add(message("Re: rollout plan", sender=ANNA, to=(sender_is_me,), offset_seconds=3600))
    box.add(message("Weekly newsletter", sender="news@example.org", to=(sender_is_me,), offset_seconds=7200))
    return box


def attribution_cases() -> Mailbox:
    """One message for each row of the precedence table."""
    box = Mailbox()
    box.add(message("[ACME] rollout plan", to=(ANNA,)))          # subject and correspondent
    box.add(message("Status update", to=(ANNA,)))                 # address rule only
    box.add(message("Status update again", to=(OPS,)))            # domain rule only
    box.add(message("[ACME] unrelated recipient", to=(BOB,)))     # subject rule only
    box.add(message("A message", to=(BOB,)))                      # nothing matches
    return box


def awkward() -> Mailbox:
    """The edge cases the spec names, each one a message."""
    box = Mailbox()
    box.add(message("", to=(ANNA,)))                                        # empty subject
    box.add(message("Broadcast", to=tuple(f"p{i}@acme.example" for i in range(50))))
    box.add(message("Grüße und Küsse", to=(ANNA,)))                         # encoded word
    box.add(message("No date at all", to=(ANNA,), date_header=False))
    box.add(message("Unparseable date", to=(ANNA,), date_header="not a date"))
    box.add(message("With attachment", to=(ANNA,), with_attachment=True))
    box.add(message("Secretly copied", to=(ANNA,), bcc=(CAROL,)))
    return box


# --- asserting the sentinels never arrive ---------------------------------------------


def find_sentinels(store: Path, *also: Path) -> list[str]:
    """Every place either sentinel appears in the store or the named files.

    Searches **every column of every table**, not the columns we expect to be at risk.
    A body reaching the store through a field nobody thought about is exactly the failure
    this is meant to catch.
    """
    hits: list[str] = []
    connection = sqlite3.connect(store)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ]
        for table in tables:
            columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
            for column in columns:
                for sentinel in (SENTINEL_BODY, SENTINEL_ATTACHMENT):
                    found = connection.execute(
                        f"SELECT count(*) FROM {table} "  # noqa: S608 — names come from sqlite_master
                        f"WHERE CAST({column} AS TEXT) LIKE ?",
                        (f"%{sentinel}%",),
                    ).fetchone()[0]
                    if found:
                        hits.append(f"{table}.{column}: {found} row(s) contain {sentinel}")
    finally:
        connection.close()

    for path in also:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for sentinel in (SENTINEL_BODY, SENTINEL_ATTACHMENT):
            if sentinel in text:
                hits.append(f"{path.name} contains {sentinel}")
    return hits
