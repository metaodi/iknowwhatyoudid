"""Permission checks (FR-005, FR-006, FR-031).

Platform-split by necessity: st_mode is meaningless on Windows and SDDL does not exist
on POSIX. The Windows branch is tested against captured SDDL strings so it runs
everywhere, with one smoke test for the actual Win32 call.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iknowwhatyoudid.protection.permissions import (
    PermissionStatus,
    check,
    interpret_sddl,
    read_sddl,
)

OWNER = "S-1-5-21-2541456660-2113479907-1373168818-13577"


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits")
def test_posix_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_text("x")
    target.chmod(0o600)
    assert check(target).status is PermissionStatus.OWNER_ONLY


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits")
def test_posix_world_readable(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_text("x")
    target.chmod(0o644)
    assert check(target).status is PermissionStatus.OTHERS_CAN_READ


@pytest.mark.parametrize(
    ("sddl", "expected"),
    [
        (
            f"O:{OWNER}D:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;{OWNER})",
            PermissionStatus.OWNER_ONLY,
        ),
        (f"O:{OWNER}D:(A;ID;FA;;;SY)(A;;FR;;;WD)", PermissionStatus.OTHERS_CAN_READ),
        # A rights *mask* rather than a mnemonic. Real inherited ACEs look like this, and
        # a token-only check silently misses a file every local user can read.
        (
            f"O:{OWNER}D:(A;ID;FA;;;SY)(A;OICIID;0x1200a9;;;BU)",
            PermissionStatus.OTHERS_CAN_READ,
        ),
        (
            f"O:{OWNER}D:(A;;0x1200a9;;;S-1-5-21-9-9-9-1001)",
            PermissionStatus.OTHERS_CAN_READ,
        ),
        # Write-only for others is not a read exposure.
        (f"O:{OWNER}D:(A;;0x116;;;BU)", PermissionStatus.OWNER_ONLY),
        # A deny ACE grants nothing.
        (f"O:{OWNER}D:(D;;FR;;;WD)(A;ID;FA;;;{OWNER})", PermissionStatus.OWNER_ONLY),
        # A group section between owner and DACL must not confuse the parser.
        (f"O:{OWNER}G:{OWNER}D:(A;ID;FA;;;{OWNER})S:AI", PermissionStatus.OWNER_ONLY),
    ],
)
def test_interpret_sddl(sddl: str, expected: PermissionStatus) -> None:
    assert interpret_sddl(sddl).status is expected


@pytest.mark.parametrize("sddl", ["", "D:(A;;FA;;;WD)", f"O:{OWNER}"])
def test_unreadable_sddl_is_never_owner_only(sddl: str) -> None:
    """The load-bearing assertion: what cannot be verified is never reported as safe."""
    assert interpret_sddl(sddl).status is PermissionStatus.UNVERIFIED


@pytest.mark.skipif(os.name != "nt", reason="Win32 call")
def test_read_sddl_smoke(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_text("x")
    sddl = read_sddl(target)
    assert sddl.startswith("O:")
    assert "D:" in sddl


def test_missing_file_is_unverified(tmp_path: Path) -> None:
    assert check(tmp_path / "nope").status is PermissionStatus.UNVERIFIED
