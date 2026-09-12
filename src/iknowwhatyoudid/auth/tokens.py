"""Where refresh tokens live between runs (research R8).

**This is the only file outside the data directory that this feature writes**, and the
only place a credential is persisted. Called out here because the constitution requires a
pull request to flag exactly that.

The constitution permits "the OS keyring or a local configuration file outside version
control with user-only permissions". A keyring means a third-party dependency on every
platform; the permission-checked file means none, and the checking code already exists —
`protection/permissions.py`, built by `0001` for the store, including the Windows SDDL
parsing that took two corrections to get right.

Permissions are checked on **every read**, not only at creation. A file that was created
user-only and later opened up is exactly the case worth catching, and it is cheap to ask.

Every token loaded is registered with `credentials/redaction.py`, so if one ever reaches a
log line through some path nobody predicted, it is masked on the way out.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..credentials import redaction
from ..errors import IkwydError
from ..protection import permissions

FILENAME = "tokens.toml"


class TokenStoreUnreadableError(IkwydError):
    """The token file exists but must not be trusted.

    Distinct from "absent": a file anyone can read is a different problem from no file at
    all, and telling the user to authorise again would not fix it.
    """


@dataclass(frozen=True, slots=True)
class StoredToken:
    account: str
    refresh_token: str
    client_id: str = ""
    tenant: str = ""

    def __repr__(self) -> str:
        return f"StoredToken(account={self.account!r}, redacted)"


def path_for(config_path: Path) -> Path:
    """Beside `config.toml`, as `credentials.toml` already is."""
    return config_path.parent / FILENAME


def load(path: Path) -> dict[str, StoredToken]:
    """Every stored token, or an empty mapping if the file is absent.

    Absent is normal — it is the state before the first `sources authorise` — so it is
    not an error. Unreadable permissions *are*.
    """
    if not path.exists():
        return {}

    report = permissions.check(path)
    if report.status is permissions.PermissionStatus.OTHERS_CAN_READ:
        raise TokenStoreUnreadableError(
            f"{path} can be read by other users",
            remedy=(
                "It holds refresh tokens for your mail accounts. Restrict it to your own "
                "user, or delete it and authorise again."
            ),
        )

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TokenStoreUnreadableError(
            f"{path} could not be read: {exc}",
            remedy="Delete it and run `ikwyd sources authorise` again.",
        ) from exc

    found: dict[str, StoredToken] = {}
    for account, entry in document.items():
        if not isinstance(entry, dict):
            continue
        token = entry.get("refresh_token")
        if not isinstance(token, str) or not token:
            continue
        redaction.register(token)
        found[account] = StoredToken(
            account=account,
            refresh_token=token,
            client_id=str(entry.get("client_id", "")),
            tenant=str(entry.get("tenant", "")),
        )
    return found


def save(path: Path, token: StoredToken) -> None:
    """Write one account's token, leaving the others alone.

    The file is written whole because `tomllib` only reads; the other entries are loaded
    first and written back. Permissions are restricted **before** anything is written, so
    there is no window in which a token sits in a world-readable file.
    """
    existing = _read_quietly(path)
    existing[token.account] = token

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    permissions.restrict_to_owner(path)

    path.write_text(_render(existing), encoding="utf-8")
    redaction.register(token.refresh_token)


def forget(path: Path, account: str) -> bool:
    """Drop one account's token. Used when a refresh is rejected for good."""
    existing = _read_quietly(path)
    if account not in existing:
        return False
    del existing[account]
    path.write_text(_render(existing), encoding="utf-8")
    return True


def _read_quietly(path: Path) -> dict[str, StoredToken]:
    try:
        return load(path)
    except TokenStoreUnreadableError:
        # Being unable to read the old file must not stop a fresh authorisation from
        # succeeding; the bad file is replaced rather than appended to.
        return {}


def _render(tokens: dict[str, StoredToken]) -> str:
    lines = [
        "# iknowwhatyoudid — refresh tokens. Written by `ikwyd sources authorise`.",
        "#",
        "# This file holds credentials. It is created readable by you alone, and the tool",
        "# refuses to use it if that stops being true. It is never committed: `tokens.toml`",
        "# is in .gitignore.",
        "",
    ]
    for account in sorted(tokens):
        token = tokens[account]
        lines.append(f"[{account}]")
        lines.append(f'refresh_token = "{_escape(token.refresh_token)}"')
        if token.client_id:
            lines.append(f'client_id = "{_escape(token.client_id)}"')
        if token.tenant:
            lines.append(f'tenant = "{_escape(token.tenant)}"')
        lines.append("")
    return "\n".join(lines)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
