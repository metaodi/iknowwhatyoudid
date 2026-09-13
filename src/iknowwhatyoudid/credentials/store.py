"""Credential resolution: presence for every source, and one readable value.

## Two questions, two answers

This file is asked two different things, and they are guarded differently on purpose:

* **"Is this credential name known?"** — asked by every source, on every `sources list` and
  `sources validate`. The answer discloses nothing, so a file other accounts can read is
  reported as a warning and the question is still answered.
* **"What is this value?"** — added by `0006`, and used only to send a client secret to a
  token endpoint. Here a file other accounts can read is **refused**, because handing a
  secret out of a file just shown to be world-readable is the one case where continuing
  makes things worse.

`tokens.toml` refuses on every read because it contains nothing but secrets. This file
answers both kinds of question, so it gives both kinds of answer. That asymmetry is
deliberate and is pinned by
`tests/unit/test_credential_value.py::test_the_presence_check_still_only_warns_when_others_can_read`
— tidying the two paths into agreement would break `sources list` for anyone whose file is
loose, and protect nothing.

## What used to be here

Until `0006` this class said, in as many words, that it exposed no method returning a value
— "a future feature that must actually authenticate adds one behind this boundary; until
then the type cannot leak what it does not expose". That future arrived: Google's token
endpoint refuses a Gmail sign-in without a client secret.

The guarantee therefore had to move. It used to rest on there being no way to get a value
at all. It now rests on `value()` being the **only** way, and on `value()` registering
whatever it returns with the redaction filter *before* returning it — so no caller can hold
an unmaskable secret, even briefly, even by mistake. That is enforced here rather than
asked of callers, because a general accessor cannot rely on its own narrowness.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..errors import IkwydError
from ..protection import permissions
from . import redaction


class CredentialFileExposedError(IkwydError):
    """A value was asked for from a file other accounts can read.

    Deliberately not raised by the presence check. See the module docstring.
    """


class CredentialPresence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    name: str
    presence: CredentialPresence
    detail: str = ""


class CredentialStore:
    """Presence for every source, and one value for the one thing that needs it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._names: frozenset[str] | None = None
        self._entries: dict[str, dict[str, str]] = {}
        self._error: str | None = None

    def __repr__(self) -> str:
        """Never the contents. A store in a traceback must not print what it holds."""
        return f"CredentialStore(path={self.path!r}, redacted)"

    def _load(self) -> None:
        if self._names is not None or self._error is not None:
            return
        if not self.path.exists():
            self._names = frozenset()
            return
        try:
            document = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            self._error = str(exc)
            self._names = frozenset()
            return

        table = document.get("credential", {})
        if not isinstance(table, dict):
            self._error = "`credential` is not a table"
            self._names = frozenset()
            return

        self._names = frozenset(str(name) for name in table)
        # Register any values so the render chokepoint can mask them if they ever
        # reach output. Values are also registered again in `value()`, which is not
        # redundant: registration must be the accessor's own guarantee rather than a
        # side effect of when the file happened to be parsed.
        for name, entry in table.items():
            if isinstance(entry, dict):
                fields: dict[str, str] = {}
                for key, item in entry.items():
                    if isinstance(item, str):
                        redaction.register(item)
                        fields[str(key)] = item
                self._entries[str(name)] = fields
            elif isinstance(entry, str):
                redaction.register(entry)

    def permissions(self) -> permissions.PermissionReport:
        return permissions.check(self.path)

    def status(self, name: str) -> CredentialStatus:
        """Is this name known? Answered whatever the file's permissions are (FR-003a)."""
        self._load()
        if self._error is not None:
            return CredentialStatus(
                name, CredentialPresence.UNREADABLE, f"{self.path}: {self._error}"
            )
        assert self._names is not None
        if name in self._names:
            return CredentialStatus(name, CredentialPresence.PRESENT, str(self.path))
        return CredentialStatus(
            name, CredentialPresence.ABSENT, f"not found in {self.path}"
        )

    def known_names(self) -> frozenset[str]:
        self._load()
        return self._names or frozenset()

    def value(self, name: str, key: str) -> str | None:
        """The one way to obtain a credential value (FR-001, FR-001a).

        Returns `None` for every shape of absence — unknown name, unknown key, empty
        string, whitespace only. They are one outcome rather than four because a caller
        distinguishing them would be writing code against an accident: all four mean the
        same thing to the person who has to fix it.

        Refuses, rather than returning, when the file can be read by other accounts
        (FR-003). The refusal happens before anything is returned and therefore before any
        caller could put the value in a request.

        Registers the value before returning it (FR-004). Note the order: a value returned
        first and registered afterwards is, for that instant, something a caller could
        print and the filter could not mask.
        """
        if self.path.exists():
            report = permissions.check(self.path)
            if report.status is permissions.PermissionStatus.OTHERS_CAN_READ:
                # Only OTHERS_CAN_READ refuses. `UNVERIFIED` is the normal answer on
                # systems where the check needs rights the tool does not have, and
                # refusing on "could not tell" would be a refusal based on ignorance.
                raise CredentialFileExposedError(
                    f"{self.path} can be read by other accounts, and holds a value "
                    f"this command needs to send",
                    remedy=(
                        "Restrict it to your own account, then run this again. "
                        "Nothing was read and nothing was sent."
                    ),
                )

        self._load()
        found = self._entries.get(name, {}).get(key)
        if found is None or not found.strip():
            return None

        redaction.register(found)
        return found
