"""Best-effort full-disk-encryption detection (FR-031).

Three-valued, and it never collapses "unknown" into "safe".

On Windows this is usually UNVERIFIED, and that is not a shortcoming of this code:
BitLocker status cannot be read without administrator rights. All three available
probes — `manage-bde -status`, `Get-BitLockerVolume`, and the Win32_EncryptableVolume
CIM class — return access-denied for a normal user (verified; research.md R10). So the
report names the elevated command the user can run themselves, which turns a dead end
into an action.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# PowerShell cold start alone can exceed five seconds on Windows; a probe that times
# out reports UNVERIFIED, which is the right answer but for the wrong reason.
_TIMEOUT_SECONDS = 25


class EncryptionStatus(StrEnum):
    ON = "ON"
    OFF = "OFF"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True, slots=True)
class EncryptionReport:
    status: EncryptionStatus
    detail: str
    how_to_check: str | None = None


def check(path: Path, platform: str | None = None) -> EncryptionReport:
    system = sys.platform if platform is None else platform
    try:
        if system == "win32":
            return _check_windows(path)
        if system == "darwin":
            return _check_macos()
        if system.startswith("linux"):
            return _check_linux(path)
    except (OSError, subprocess.SubprocessError) as exc:
        return EncryptionReport(EncryptionStatus.UNVERIFIED, f"probe failed: {exc}")
    return EncryptionReport(
        EncryptionStatus.UNVERIFIED, f"no probe implemented for platform {system!r}"
    )


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _check_windows(path: Path) -> EncryptionReport:
    drive = path.resolve().drive or "C:"
    how = f"In an elevated PowerShell:  Get-BitLockerVolume -MountPoint {drive}"
    try:
        result = _run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-BitLockerVolume -MountPoint '{drive}').ProtectionStatus",
            ]
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return EncryptionReport(EncryptionStatus.UNVERIFIED, f"probe failed: {exc}", how)

    value = result.stdout.strip()
    if result.returncode == 0 and value:
        if value in {"1", "On"}:
            return EncryptionReport(EncryptionStatus.ON, "BitLocker protection is on", how)
        if value in {"0", "Off"}:
            return EncryptionReport(EncryptionStatus.OFF, "BitLocker protection is off", how)

    return EncryptionReport(
        EncryptionStatus.UNVERIFIED,
        "reading BitLocker status requires administrator rights",
        how,
    )


def _check_macos() -> EncryptionReport:
    how = "Run:  fdesetup status"
    result = _run(["fdesetup", "status"])
    text = result.stdout.strip()
    if result.returncode == 0 and text:
        if "FileVault is On" in text:
            return EncryptionReport(EncryptionStatus.ON, "FileVault is on", how)
        if "FileVault is Off" in text:
            return EncryptionReport(EncryptionStatus.OFF, "FileVault is off", how)
    return EncryptionReport(EncryptionStatus.UNVERIFIED, "could not read FileVault status", how)


def _check_linux(path: Path) -> EncryptionReport:
    """Look for a dm-crypt mapping behind the filesystem holding *path*."""
    how = "Run:  lsblk -o NAME,TYPE,MOUNTPOINT"
    try:
        device_id = path.resolve().stat().st_dev
    except OSError as exc:
        return EncryptionReport(EncryptionStatus.UNVERIFIED, f"probe failed: {exc}", how)

    major, minor = (device_id >> 8) & 0xFF, device_id & 0xFF
    dm_uuid = Path(f"/sys/dev/block/{major}:{minor}/dm/uuid")
    try:
        uuid = dm_uuid.read_text(encoding="utf-8").strip()
    except OSError:
        return EncryptionReport(
            EncryptionStatus.UNVERIFIED,
            "the volume is not a device-mapper target; encryption could not be determined",
            how,
        )
    if uuid.startswith("CRYPT-"):
        return EncryptionReport(EncryptionStatus.ON, f"dm-crypt volume ({uuid})", how)
    return EncryptionReport(
        EncryptionStatus.OFF, "device-mapper volume with no dm-crypt layer", how
    )
