"""Mail kinds.

Four of them, two ways in: an HTTP API this tool calls (`mail.outlook`, `mail.gmail`), and
a file it reads (`mail.hey`, `mail.mbox`).

**`mail.hey` is corrected here, not removed.** `0002` declared it with destination "Hey
IMAP" and required access "Read your mail over IMAP". That was wrong — Hey offers no IMAP,
no POP and no third-party API.

37signals do ship an official CLI, and reading Hey through it was the plan until it was
tried: `hey search --json` returns no recipients and no `Message-ID`, which are exactly
what attribution and cross-provider identity need (research R1, verified against a real
account). So Hey mail arrives the only way it can — from an export.

The name stays because someone may already have written it into a configuration on the
strength of the old declaration. What changes is that it now says something true.
"""

from __future__ import annotations

from ..mail.reader import MailReader
from .spec import ReadingAvailability, SettingSpec, SourceKind, SettingType

_ADDRESSES = SettingSpec(
    key="addresses",
    type=SettingType.IDENTITY_LIST,
    required=True,
    help="Mail addresses that are yours. Only mail sent from one of these is recorded.",
)

#: Public, not secret — a client_id appears in every authorisation URL. It lives here
#: rather than in credentials.toml for a concrete reason: that file registers every value
#: it holds with the redaction filter, so a client_id kept there would be masked out of
#: the very URL `sources authorise --no-browser` asks the user to open.
_CLIENT_ID = SettingSpec(
    key="client_id",
    type=SettingType.STRING,
    help="The application registration this account signs in through.",
)

_TENANT = SettingSpec(
    key="tenant",
    type=SettingType.STRING,
    help="Directory to sign in against. Defaults to `organizations`.",
)

_PATHS = SettingSpec(
    key="paths",
    type=SettingType.PATH_LIST,
    required=True,
    help="Exported `.mbox` files. `~` and globs expand.",
)


def _folder_settings(word: str) -> tuple[SettingSpec, ...]:
    return (
        SettingSpec(
            key=f"{word}.include",
            type=SettingType.STRING_LIST,
            help=f"Only these {word} are read. Defaults to the account's sent {word}.",
        ),
        SettingSpec(
            key=f"{word}.exclude",
            type=SettingType.STRING_LIST,
            help=f"These {word} are never read.",
        ),
    )


#: One reader serves every mail kind — nothing above it knows which provider ran.
_READER = MailReader()

OUTLOOK = SourceKind(
    name="mail.outlook",
    summary="mail you sent from an Outlook or Microsoft 365 account",
    settings=(_ADDRESSES, _CLIENT_ID, _TENANT, *_folder_settings("folders")),
    credential_required=True,
    required_access=(
        "Mail.ReadBasic — read your mail, without message bodies or attachments",
        "This grant cannot send, delete, move, or mark anything as read",
    ),
    destinations=("graph.microsoft.com", "login.microsoftonline.com"),
    reading=ReadingAvailability.AVAILABLE,
    reader=_READER,
)

GMAIL = SourceKind(
    name="mail.gmail",
    summary="mail you sent from a Gmail account",
    settings=(_ADDRESSES, _CLIENT_ID, _TENANT, *_folder_settings("labels")),
    credential_required=True,
    required_access=(
        "gmail.metadata — read message headers and labels, never a body or an attachment",
        "IMAP is deliberately not used: its only Gmail scope also grants send and delete",
    ),
    destinations=("gmail.googleapis.com", "oauth2.googleapis.com"),
    reading=ReadingAvailability.AVAILABLE,
    reader=_READER,
)

HEY = SourceKind(
    name="mail.hey",
    summary="mail you sent from a Hey account, from an export (Hey offers no other route)",
    settings=(_ADDRESSES, _PATHS),
    credential_required=False,
    required_access=("Opens the exported file read-only, and never writes or moves it",),
    destinations=(),
    reading=ReadingAvailability.AVAILABLE,
    reader=_READER,
)

MBOX = SourceKind(
    name="mail.mbox",
    summary="mail you sent, from an exported `.mbox` archive",
    settings=(_ADDRESSES, _PATHS),
    credential_required=False,
    required_access=("Opens the file read-only, and never writes, moves or renames it",),
    destinations=(),
    reading=ReadingAvailability.AVAILABLE,
    reader=_READER,
)
