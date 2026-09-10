"""Mail kinds — declarations only (FR-036). Reading arrives with feature 0004."""

from __future__ import annotations

from .spec import ReadingAvailability, SettingSpec, SettingType, SourceKind

_ADDRESSES = SettingSpec(
    key="addresses",
    type=SettingType.IDENTITY_LIST,
    required=True,
    help="Mail addresses that are yours, so sent can be told from received.",
)


def _folder_settings(word: str) -> tuple[SettingSpec, ...]:
    return (
        SettingSpec(
            key=f"{word}.include",
            type=SettingType.STRING_LIST,
            help=f"Only these {word} are read. Omit to read all of them.",
        ),
        SettingSpec(
            key=f"{word}.exclude",
            type=SettingType.STRING_LIST,
            help=f"These {word} are never read.",
        ),
    )


OUTLOOK = SourceKind(
    name="mail.outlook",
    summary="mail sent and received through an Outlook or Microsoft 365 account",
    settings=(_ADDRESSES, *_folder_settings("folders")),
    credential_required=True,
    required_access=("Read your mail, and nothing else",),
    destinations=("Microsoft Graph",),
    reading=ReadingAvailability.NOT_YET_IMPLEMENTED,
    arrives_in="0004",
)

GMAIL = SourceKind(
    name="mail.gmail",
    summary="mail sent and received through a Gmail account",
    settings=(_ADDRESSES, *_folder_settings("labels")),
    credential_required=True,
    required_access=("Read your mail, and nothing else",),
    destinations=("Google Gmail API",),
    reading=ReadingAvailability.NOT_YET_IMPLEMENTED,
    arrives_in="0004",
)

HEY = SourceKind(
    name="mail.hey",
    summary="mail sent and received through a Hey account",
    settings=(_ADDRESSES, *_folder_settings("folders")),
    credential_required=True,
    required_access=("Read your mail over IMAP, and nothing else",),
    destinations=("Hey IMAP",),
    reading=ReadingAvailability.NOT_YET_IMPLEMENTED,
    arrives_in="0004",
)
