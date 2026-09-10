"""Calendar kinds — declarations only (FR-037). Reading arrives with feature 0005."""

from __future__ import annotations

from .spec import ReadingAvailability, SettingSpec, SettingType, SourceKind

_CALENDARS = SettingSpec(
    key="calendars",
    type=SettingType.STRING_LIST,
    required=True,
    help="Which of the account's calendars are in scope.",
)

OUTLOOK = SourceKind(
    name="calendar.outlook",
    summary="meetings and events in an Outlook or Microsoft 365 calendar",
    settings=(_CALENDARS,),
    credential_required=True,
    required_access=("Read your calendars, and nothing else",),
    destinations=("Microsoft Graph",),
    reading=ReadingAvailability.NOT_YET_IMPLEMENTED,
    arrives_in="0005",
)

GOOGLE = SourceKind(
    name="calendar.google",
    summary="meetings and events in a Google calendar",
    settings=(_CALENDARS,),
    credential_required=True,
    required_access=("Read your calendars, and nothing else",),
    destinations=("Google Calendar API",),
    reading=ReadingAvailability.NOT_YET_IMPLEMENTED,
    arrives_in="0005",
)
