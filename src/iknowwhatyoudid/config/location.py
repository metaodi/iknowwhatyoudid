"""Where the configuration and credentials files live (FR-002, FR-003).

Note this is the *configuration* directory, which differs from the store's data
directory on Windows: configuration is hand-authored and belongs in roaming `APPDATA`,
while the store is a large rebuildable cache and belongs in `LOCALAPPDATA`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..errors import UsageError

APP_NAME = "iknowwhatyoudid"
CONFIG_FILENAME = "config.toml"
CREDENTIALS_FILENAME = "credentials.toml"
PROJECTS_FILENAME = "projects.toml"


def config_dir(env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    environ = os.environ if env is None else env
    system = sys.platform if platform is None else platform

    if system == "win32":
        base = environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME

    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg = environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def default_config_path(
    env: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    return config_dir(env, platform) / CONFIG_FILENAME


def resolve_config_path(
    override: str | os.PathLike[str] | None,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """``--config PATH`` if given, else the one documented default (FR-002, FR-003).

    An empty override is refused for the same reason as `--store`: it is an unset shell
    variable, not a request to read the current directory.
    """
    if override is not None:
        text = str(override).strip()
        if not text:
            raise UsageError(
                "--config was given an empty path",
                remedy="Give a path, or omit --config to use the default configuration.",
            )
        return Path(text).expanduser()
    return default_config_path(env, platform)


def projects_path_for(config: Path) -> Path:
    """The project mapping that belongs with *config* — beside it.

    Kept out of `config.toml` because `0002` FR-041 rejects a project mapping there:
    attribution rules change often and are expected to be wrong at first, and a bad rule
    must not be able to break the configuration that says where to read from.
    """
    return config.parent / PROJECTS_FILENAME


def resolve_projects_path(
    override: str | os.PathLike[str] | None,
    config: Path,
) -> Path:
    """``--projects PATH`` if given, else the file beside the configuration."""
    if override is not None:
        text = str(override).strip()
        if not text:
            raise UsageError(
                "--projects was given an empty path",
                remedy="Give a path, or omit --projects to use the default mapping.",
            )
        return Path(text).expanduser()
    return projects_path_for(config)


def credentials_path_for(config: Path) -> Path:
    """The credentials file that belongs with *config* — beside it.

    Keeping them together means ``--config`` selects a whole configuration, not a file
    whose secrets still come from somewhere else.
    """
    return config.parent / CREDENTIALS_FILENAME
