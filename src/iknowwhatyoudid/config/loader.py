"""Reading the configuration file (FR-001 to FR-006).

`tomllib` is read-only by construction, which is exactly FR-002: there is no write path
to reach for, so the tool cannot rewrite or reformat the user's file even by accident.
"""

from __future__ import annotations

import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import ConfigNotFoundError, ConfigParseError
from ..protection import permissions
from . import findings as f
from .locate import find_key_line, find_source_line, find_top_level_key_line
from .model import ConfiguredSource, CredentialReference, SourceConfiguration

#: Keys allowed at the top level of the file.
TOP_LEVEL_KEYS = frozenset({"version", "source"})

#: Keys that mean the user is trying to declare project attribution here (FR-041).
ATTRIBUTION_KEYS = frozenset({"projects", "attribution", "mapping"})

#: Keys a source declares itself, as opposed to kind-specific settings.
RESERVED_SOURCE_KEYS = frozenset({"name", "kind", "enabled", "since", "credential"})

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_POSITION = re.compile(r"at line (\d+), column (\d+)")


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


def read_text(path: Path) -> str:
    if not path.exists():
        raise ConfigNotFoundError(
            f"no configuration file at {path}",
            remedy=(
                "Create it, or point at another with --config PATH. "
                "The tool never creates this file for you."
            ),
        )
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigParseError(
            f"{path} could not be read: {exc}",
            remedy="Check the file's permissions.",
        ) from exc


def parse(text: str, path: Path) -> dict[str, Any]:
    """Parse TOML, turning a syntax error into a located, fatal failure (FR-004)."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        line = column = None
        match = _POSITION.search(str(exc))
        if match:
            line, column = int(match.group(1)), int(match.group(2))
        where = f" (line {line}, column {column})" if line else ""
        raise ConfigParseError(
            f"{path} is not valid TOML{where}: {exc}",
            remedy=(
                "Fix the syntax error. Nothing was read from any source and the file "
                "has not been modified."
            ),
            line=line,
            column=column,
        ) from exc


def _flatten(prefix: str, table: dict[str, Any]) -> dict[str, Any]:
    """Turn nested tables back into the dotted keys the user wrote."""
    flat: dict[str, Any] = {}
    for key, value in table.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(dotted, value))
        else:
            flat[dotted] = value
    return flat


def _source_from_table(
    index: int, table: dict[str, Any], text: str, problems: list[f.Finding]
) -> ConfiguredSource | None:
    name = table.get("name")
    line = find_source_line(text, index)
    if not isinstance(name, str) or not name:
        problems.append(
            f.blocking(
                f.INVALID_SOURCE_NAME,
                "a source must have a name",
                key_path=f"source[{index}].name",
                line=line,
                remedy="Add `name = \"...\"` to this source.",
            )
        )
        return None
    if not valid_name(name):
        problems.append(
            f.blocking(
                f.INVALID_SOURCE_NAME,
                f"{name!r} is not a usable source name",
                source_name=name,
                key_path=f"source[{index}].name",
                line=find_key_line(text, index, "name") or line,
                remedy=(
                    "Names identify a source in the store. Use letters, digits, "
                    "dot, dash or underscore, starting with a letter or digit."
                ),
            )
        )
        return None

    kind = table.get("kind")
    if not isinstance(kind, str) or not kind:
        problems.append(
            f.blocking(
                f.UNKNOWN_KIND,
                f"source {name!r} does not say what kind it is",
                source_name=name,
                key_path=f"source[{index}].kind",
                line=find_key_line(text, index, "kind") or line,
                remedy="Add `kind = \"...\"`. Run `ikwyd sources kinds` to see the options.",
            )
        )
        return None

    enabled = table.get("enabled", True)
    if not isinstance(enabled, bool):
        problems.append(
            f.blocking(
                f.SETTING_TYPE_MISMATCH,
                "`enabled` must be true or false",
                source_name=name,
                key_path=f"source[{index}].enabled",
                line=find_key_line(text, index, "enabled"),
            )
        )
        enabled = True

    since = table.get("since")
    if since is not None and not isinstance(since, datetime):
        problems.append(
            f.blocking(
                f.SETTING_TYPE_MISMATCH,
                "`since` must be a date-time",
                source_name=name,
                key_path=f"source[{index}].since",
                line=find_key_line(text, index, "since"),
                remedy="Write it as e.g. 2026-01-01T00:00:00+01:00.",
            )
        )
        since = None

    credential_name = table.get("credential")
    credential = None
    if credential_name is not None:
        if isinstance(credential_name, str) and credential_name:
            credential = CredentialReference(credential_name)
        else:
            problems.append(
                f.blocking(
                    f.SETTING_TYPE_MISMATCH,
                    "`credential` must be the name of a credential",
                    source_name=name,
                    key_path=f"source[{index}].credential",
                    line=find_key_line(text, index, "credential"),
                    remedy="It is a name, never a secret value.",
                )
            )

    settings = _flatten(
        "", {k: v for k, v in table.items() if k not in RESERVED_SOURCE_KEYS}
    )

    return ConfiguredSource(
        name=name,
        kind=kind,
        index=index,
        enabled=enabled,
        since=since if isinstance(since, datetime) else None,
        credential=credential,
        settings=settings,
    )


def load(path: Path) -> tuple[SourceConfiguration, list[f.Finding]]:
    """Read and structurally parse the configuration.

    Raises on a file that is absent or unparseable — both are fatal for the run and
    distinguishable by exit code. Everything softer comes back as findings.
    """
    text = read_text(path)
    document = parse(text, path)
    problems: list[f.Finding] = []

    permission_report = permissions.check(path)
    if permission_report.status is permissions.PermissionStatus.OTHERS_CAN_READ:
        problems.append(
            f.warning(
                f.FILE_PERMISSIONS,
                f"{path.name} is readable by other accounts on this machine "
                f"({permission_report.detail})",
                key_path=path.name,
                remedy="Restrict it to your own account.",
            )
        )
    elif permission_report.status is permissions.PermissionStatus.UNVERIFIED:
        problems.append(
            f.warning(
                f.FILE_PERMISSIONS_UNVERIFIED,
                f"could not verify who can read {path.name} "
                f"({permission_report.detail})",
                key_path=path.name,
                remedy="Check the file's permissions yourself.",
            )
        )

    for key in document:
        if key in ATTRIBUTION_KEYS:
            problems.append(
                f.blocking(
                    f.ATTRIBUTION_NOT_ALLOWED,
                    f"`{key}` does not belong in the source configuration",
                    key_path=key,
                    line=find_top_level_key_line(text, key),
                    remedy=(
                        "This file says where to read from. Mapping people or "
                        "repositories to projects is attribution, and belongs to a "
                        "later feature — it is rejected here rather than ignored."
                    ),
                )
            )
        elif key not in TOP_LEVEL_KEYS:
            problems.append(
                f.blocking(
                    f.UNKNOWN_TOP_LEVEL_KEY,
                    f"unknown top-level key `{key}`",
                    key_path=key,
                    line=find_top_level_key_line(text, key),
                    remedy=(
                        "A misspelled key is a source you believe is configured and "
                        "that would be silently skipped, so it is refused."
                    ),
                )
            )

    version = document.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        problems.append(
            f.blocking(
                f.SETTING_TYPE_MISMATCH,
                "`version` must be an integer",
                key_path="version",
                line=find_top_level_key_line(text, "version"),
            )
        )
        version = 1

    raw_sources = document.get("source", [])
    sources: list[ConfiguredSource] = []
    if raw_sources and not isinstance(raw_sources, list):
        problems.append(
            f.blocking(
                f.UNKNOWN_TOP_LEVEL_KEY,
                "`source` must be a list of [[source]] blocks",
                key_path="source",
            )
        )
        raw_sources = []

    for index, table in enumerate(raw_sources):
        if not isinstance(table, dict):
            problems.append(
                f.blocking(
                    f.UNKNOWN_TOP_LEVEL_KEY,
                    f"source[{index}] is not a table",
                    key_path=f"source[{index}]",
                )
            )
            continue
        source = _source_from_table(index, table, text, problems)
        if source is not None:
            sources.append(source)

    # FR-007: duplicate names, reported once per collision.
    seen: dict[str, int] = {}
    for source in sources:
        if source.name in seen:
            problems.append(
                f.blocking(
                    f.DUPLICATE_SOURCE_NAME,
                    f"duplicate source name (also at source[{seen[source.name]}])",
                    source_name=source.name,
                    key_path=source.setting_path("name"),
                    line=find_key_line(text, source.index, "name"),
                    remedy=(
                        "Names identify a source in the store; give one of them a "
                        "different name."
                    ),
                )
            )
        else:
            seen[source.name] = source.index

    configuration = SourceConfiguration(
        path=path,
        raw_text=text,
        sources=tuple(sources),
        version=version,
        permissions=permission_report,
    )
    return configuration, problems
