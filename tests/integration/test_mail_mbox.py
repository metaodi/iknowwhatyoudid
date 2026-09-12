"""Reading an exported archive, and never writing one.

The archive reader carries a guarantee the API providers get from their scopes: it must
not touch the file. Since a local file is trivially writable, this is the one provider
where "read-only" rests on the code rather than on what a token permits — so it is tested
hardest here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from iknowwhatyoudid.errors import MailReadError
from iknowwhatyoudid.mail import mbox, message as msg
from iknowwhatyoudid.mail.message import Provider


def archive(tmp_path: Path, box: fx.Mailbox | None = None) -> Path:
    built = box or fx.sent_and_received()
    return built.write_mbox(tmp_path / "export.mbox")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def messages_from(path: Path, own: list[str] | None = None) -> list[msg.Message]:
    found = []
    for headers, has_attachment in mbox.read(path):
        try:
            found.append(
                msg.build(
                    headers=headers,
                    account="archive",
                    provider=Provider.MBOX,
                    own_addresses=own or [fx.ME],
                    has_attachments=has_attachment,
                    withdrawable=False,
                )
            )
        except msg.MessageRejected:
            continue
    return found


# --- the file is never touched --------------------------------------------------------


def test_reading_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    """Principle II for a local file.

    An API provider cannot write because its token forbids it. A file has no such
    protection, so this is asserted directly: same bytes, same modification time, same
    size, after a full read.
    """
    path = archive(tmp_path)
    before_digest = digest(path)
    before_stat = mbox.fingerprint(path)

    messages_from(path)

    assert digest(path) == before_digest
    assert mbox.is_unchanged(path, before_stat), "the archive was modified"


def test_reading_a_missing_file_creates_nothing(tmp_path: Path) -> None:
    """`mailbox.mbox` will happily create a file it was asked to open.

    That would mean writing into the user's export directory as a side effect of a typo
    in `paths`, so the reader passes `create=False` and this asserts it.
    """
    absent = tmp_path / "not-there.mbox"
    with pytest.raises(MailReadError):
        list(mbox.read(absent))
    assert not absent.exists(), "asking about a file brought one into existence"


def test_no_lock_or_temporary_file_is_left_behind(tmp_path: Path) -> None:
    """Some mailbox backends write a lock file beside the archive."""
    path = archive(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}

    messages_from(path)

    assert {p.name for p in tmp_path.iterdir()} == before


# --- what is read ----------------------------------------------------------------------


def test_only_sent_mail_becomes_a_message(tmp_path: Path) -> None:
    """FR-048 — the fixture holds both directions, so this cannot pass by accident."""
    path = archive(tmp_path)
    found = messages_from(path)

    assert len(found) == 1
    assert found[0].sender == fx.ME
    assert found[0].subject == "Rollout plan"


def test_no_body_or_attachment_content_is_taken(tmp_path: Path) -> None:
    """FR-023, FR-024 — the body is in the file; it must not leave it."""
    box = fx.Mailbox()
    box.add(fx.message("With attachment", with_attachment=True))
    path = archive(tmp_path, box)

    assert fx.SENTINEL_BODY in path.read_text(encoding="utf-8", errors="replace"), (
        "the fixture really does contain a body"
    )

    found = messages_from(path)
    assert len(found) == 1
    record = msg.to_record(found[0])
    assert record.payload["has_attachments"] is True
    assert fx.SENTINEL_BODY not in str(record.payload)
    assert fx.SENTINEL_ATTACHMENT not in str(record.payload)


def test_headers_are_limited_to_the_allow_list(tmp_path: Path) -> None:
    """The reader hands over `READABLE_HEADERS` and nothing else."""
    box = fx.Mailbox()
    box.add(fx.message("Secretly copied", to=(fx.ANNA,), bcc=(fx.CAROL,)))
    path = archive(tmp_path, box)

    for headers, _ in mbox.read(path):
        assert set(headers) <= msg.READABLE_HEADERS
        assert "Bcc" not in headers


# --- the withdrawal trap -----------------------------------------------------------------


def test_an_archive_never_produces_a_withdrawable_record(tmp_path: Path) -> None:
    """Research R13 — an export is a snapshot, and its silence proves nothing.

    Export a narrower date range next month and every message outside it would look
    deleted. The store honours this flag, so marking it here is what prevents a sweep
    from reporting an export's scope as data loss.

    This is the same trap `0003` hit with the git reflog, where a 90-day retention policy
    would have been recorded as real events disappearing.
    """
    path = archive(tmp_path)
    for message in messages_from(path):
        record = msg.to_record(message)
        assert record.payload["withdrawable"] is False


def test_re_reading_the_same_archive_yields_the_same_identifiers(tmp_path: Path) -> None:
    """SC-006 — an archive has no incremental read, so deduplication carries it.

    Every run re-reads the whole file. What must hold is that the second run records
    nothing new, and that rests on the identifier being stable.
    """
    path = archive(tmp_path)
    first = [m.source_id for m in messages_from(path)]
    second = [m.source_id for m in messages_from(path)]
    assert first == second
    assert all(sid.startswith("mail:") for sid in first)
