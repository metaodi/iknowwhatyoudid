"""The `git.local` kind — declaration only (FR-035).

Reading arrives with feature 0003. This ships as a declaration so the configuration can
express it today, and reports `NOT_READABLE` rather than claiming a source will be read
when it will not.
"""

from __future__ import annotations

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
    ),
    credential_required=False,
    destinations=(),
    reading=ReadingAvailability.NOT_YET_IMPLEMENTED,
    arrives_in="0003",
)
