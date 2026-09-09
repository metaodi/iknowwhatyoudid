"""Where the store and the log live, and creating the data directory (FR-001 to FR-005)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "iknowwhatyoudid"
STORE_FILENAME = "store.db"
LOG_FILENAME = "iknowwhatyoudid.log"


def data_dir(env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    """The tool's own data directory.

    Windows uses LOCALAPPDATA rather than roaming APPDATA: the store is a large,
    rebuildable, machine-local cache and has no business roaming. The *configuration*
    file (feature 0002) is hand-authored and does belong in roaming APPDATA.
    """
    environ = os.environ if env is None else env
    system = sys.platform if platform is None else platform

    if system == "win32":
        base = environ.get("LOCALAPPDATA") or environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME

    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg = environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def default_store_path(env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    return data_dir(env, platform) / STORE_FILENAME


def default_log_path(env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    return data_dir(env, platform) / LOG_FILENAME


def log_path_for(store: Path) -> Path:
    """The log that belongs with *store*.

    Beside the store rather than always in the default data directory, so that
    ``--store`` is self-contained: pointing the tool at another store does not leave
    diagnostics scattered in a directory the user was not using.
    """
    return store.parent / LOG_FILENAME


def resolve_store_path(
    override: str | os.PathLike[str] | None,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """The store to use: ``--store PATH`` if given, else the platform default (FR-004)."""
    if override is not None:
        return Path(override).expanduser()
    return default_store_path(env, platform)


def ensure_parent_dir(path: Path) -> Path:
    """Create the containing directory, owner-only where the platform expresses that.

    On POSIX the mode is set explicitly; on Windows a directory created under the
    user's profile inherits an owner-only ACL, and `protection.permissions` is what
    reports whether that actually held (FR-005).
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        try:
            parent.chmod(0o700)
        except OSError:
            # Reported by `store protection` rather than failing the command here.
            pass
    return parent
