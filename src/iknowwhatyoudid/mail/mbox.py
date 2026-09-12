"""Reading an exported archive.

The simplest of the four providers, and deliberately the first one built: it proves the
whole pipeline — shape, store, attribution, querying — before any network code exists.

It is also the fallback for every other provider. Mail older than a provider's history
window, a work tenant that refuses consent, a Gmail token that has to be renewed weekly:
in each case an export is the way through.

**The file is opened read-only and never written, moved, renamed or truncated.**
`mailbox.mbox` is used with `create=False` so the library cannot bring a file into being
as a side effect of being asked about one.

**Only the header block is parsed.** The body is in the file. It is never taken.
"""

from __future__ import annotations

import mailbox
import os
from collections.abc import Iterator
from pathlib import Path

from ..errors import MailReadError
from .message import READABLE_HEADERS


def read(path: Path) -> Iterator[tuple[dict[str, str], bool]]:
    """Yield each message's readable headers, and whether it had an attachment.

    Nothing else crosses this boundary. The caller receives a dict that has no key a body
    could occupy, so `message.build` is not trusted to discard one — there is none to
    discard.
    """
    if not path.is_file():
        raise MailReadError(
            f"{path} is not a file",
            remedy="Check the path in `paths`. Nothing was read.",
        )

    try:
        # create=False: asking about a file must never bring one into existence.
        box = mailbox.mbox(str(path), create=False)
    except OSError as exc:
        raise MailReadError(
            f"{path} could not be opened: {exc}",
            remedy="The file is unchanged. This source was skipped.",
        ) from exc

    try:
        for key in box.iterkeys():
            try:
                raw = box.get_message(key)
            except (KeyError, OSError):  # pragma: no cover — a truncated archive
                continue
            headers = {
                name: str(raw[name]) for name in READABLE_HEADERS if raw[name] is not None
            }
            yield headers, _has_attachment(raw)
    finally:
        box.close()


def _has_attachment(raw: mailbox.mboxMessage) -> bool:
    """Whether the message carried an attachment — the fact, and nothing about it.

    Walks the part structure and reads a disposition. No filename, no size, no bytes:
    FR-024 forbids all three, and there is no reason to hold them even briefly.
    """
    if not raw.is_multipart():
        return False
    for part in raw.walk():
        if part.get_content_disposition() == "attachment":
            return True
    return False


def is_unchanged(path: Path, before: tuple[float, int]) -> bool:
    """Whether the file is exactly as it was — used by the read-only test.

    Modification time and size together. A read that altered either would mean this
    module had written to the user's own archive, which Principle II forbids outright.
    """
    stat = os.stat(path)
    return (stat.st_mtime, stat.st_size) == before


def fingerprint(path: Path) -> tuple[float, int]:
    stat = os.stat(path)
    return (stat.st_mtime, stat.st_size)
