"""The `git.local` kind.

Declared by `0002`; the reader arrives with `0003`. Reads commits, branches and merges
from local repositories — never over a network, and never writing to one.
"""

from __future__ import annotations

from ..git.reader import GitReader
from .spec import ReadingAvailability, SettingSpec, SettingType, SourceKind

KIND = SourceKind(
    name="git.local",
    summary="commits, branches and merges in local git repositories",
    settings=(
        SettingSpec(
            key="paths",
            type=SettingType.PATH_LIST,
            required=True,
            help="Repositories to read. Accepts a path or a glob over a containing folder.",
        ),
        SettingSpec(
            key="identities",
            type=SettingType.IDENTITY_LIST,
            required=True,
            help="Author or committer identities that are yours.",
        ),
        SettingSpec(
            key="exclude",
            type=SettingType.PATH_LIST,
            help="Locations to skip, so a broad pattern can be narrowed.",
        ),
    ),
    credential_required=False,
    # Local only. A repository's remotes are never contacted, even where configured.
    destinations=(),
    reading=ReadingAvailability.AVAILABLE,
    reader=GitReader(),
)
