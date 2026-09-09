"""Whether a file is readable by anyone but its owner (FR-005, FR-031).

Two entirely different mechanisms, because the naive one is broken on Windows:
``os.stat().st_mode`` returns synthesised permission bits there (0o666 for every file,
regardless of its real ACL) and ``os.geteuid`` does not exist. ``icacls`` was the
obvious fallback and is unusable for parsing — it returns *localised* principal names.

So Windows reads the DACL as SDDL through two Win32 calls, which yields SID
abbreviations that are the same in every locale:

    O:S-1-5-21-...D:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;S-1-5-21-...)

See specs/0001-local-store-foundation/research.md R10.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PermissionStatus(StrEnum):
    OWNER_ONLY = "OWNER_ONLY"
    OTHERS_CAN_READ = "OTHERS_CAN_READ"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True, slots=True)
class PermissionReport:
    status: PermissionStatus
    detail: str


#: Trustees that may hold access without the file counting as exposed. None of them
#: represents another ordinary user:
#:   SY  Local System
#:   BA  Builtin Administrators
#:   OW  Owner Rights — the object's own owner, written as an abbreviation rather than
#:       as a literal SID. Files created under a user profile or %TEMP% routinely carry
#:       one, so omitting it reports a perfectly private file as world-readable.
#:   CO  Creator Owner — likewise resolves to the owner, not to a third party.
_ACCEPTED_WINDOWS_TRUSTEES = frozenset({"SY", "BA", "OW", "CO"})

#: One ACE of an SDDL DACL: (type;flags;rights;object;inherit;trustee)
_ACE = re.compile(r"\(([^)]*)\)")

#: An SDDL section marker. Only ever appears at the top level: ACE bodies are
#: semicolon-separated and contain no colon, and SIDs use hyphens.
_SECTION = re.compile(r"([OGDS]):")

#: Mnemonic rights strings that include read access.
_READ_RIGHT_TOKENS = ("FA", "FR", "FX", "GA", "GR", "KA", "KR")

#: Rights are just as often written as a numeric mask (a real inherited ACE looks like
#: ``(A;OICIID;0x1200a9;;;BU)``), so a token-only check silently misses a file readable
#: by every local user. Bits: FILE_READ_DATA, GENERIC_ALL, GENERIC_READ.
_READ_RIGHT_BITS = 0x00000001 | 0x10000000 | 0x80000000


def _grants_read(rights: str) -> bool:
    rights = rights.strip()
    if not rights:
        return False
    try:
        mask = int(rights, 16) if rights.lower().startswith("0x") else int(rights)
    except ValueError:
        return any(token in rights for token in _READ_RIGHT_TOKENS)
    return bool(mask & _READ_RIGHT_BITS)


def _sections(sddl: str) -> dict[str, str]:
    """Split an SDDL string into its O:/G:/D:/S: sections."""
    found: dict[str, str] = {}
    matches = list(_SECTION.finditer(sddl))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(sddl)
        found[match.group(1)] = sddl[match.end() : end].strip()
    return found


def check(path: Path) -> PermissionReport:
    """Report whether anyone but the owner can read *path*.

    Never returns OWNER_ONLY when the check could not actually be made; a failed check
    is UNVERIFIED, because reporting an unchecked file as safe is the one outcome the
    spec forbids.
    """
    try:
        if os.name == "posix":
            return _check_posix(path)
        if os.name == "nt":
            return _check_windows(path)
    except OSError as exc:
        return PermissionReport(PermissionStatus.UNVERIFIED, f"could not read permissions: {exc}")
    return PermissionReport(
        PermissionStatus.UNVERIFIED, f"no permission check implemented for os.name={os.name!r}"
    )


def _check_posix(path: Path) -> PermissionReport:
    mode = stat.S_IMODE(path.stat().st_mode)
    exposed = mode & (stat.S_IRGRP | stat.S_IROTH)
    if exposed:
        return PermissionReport(
            PermissionStatus.OTHERS_CAN_READ,
            f"mode {mode:04o} — group or other can read",
        )
    return PermissionReport(PermissionStatus.OWNER_ONLY, f"mode {mode:04o} — owner only")


def _check_windows(path: Path) -> PermissionReport:
    sddl = read_sddl(path)
    return interpret_sddl(sddl)


def interpret_sddl(sddl: str) -> PermissionReport:
    """Decide OWNER_ONLY vs OTHERS_CAN_READ from an SDDL string.

    Split out from the Win32 call so it is directly unit-testable on any platform with
    captured SDDL strings.
    """
    sections = _sections(sddl)
    owner = sections.get("O")
    if not owner:
        return PermissionReport(PermissionStatus.UNVERIFIED, "SDDL carried no owner")
    dacl = sections.get("D")
    if dacl is None:
        return PermissionReport(PermissionStatus.UNVERIFIED, "SDDL carried no DACL")

    accepted = _ACCEPTED_WINDOWS_TRUSTEES | {owner}
    others: list[str] = []
    for ace_body in _ACE.findall(dacl):
        parts = ace_body.split(";")
        if len(parts) < 6:
            continue
        ace_type, rights, trustee = parts[0], parts[2], parts[5]
        if ace_type.startswith("D"):  # a deny ACE never grants access
            continue
        if trustee in accepted:
            continue
        if _grants_read(rights):
            others.append(trustee)

    if others:
        return PermissionReport(
            PermissionStatus.OTHERS_CAN_READ,
            "readable by " + ", ".join(sorted(set(others))),
        )
    return PermissionReport(
        PermissionStatus.OWNER_ONLY, "only the owner, SYSTEM and Administrators can read"
    )


def read_sddl(path: Path) -> str:
    """Read a file's owner and DACL as an SDDL string, via ctypes into advapi32."""
    import ctypes
    import ctypes.wintypes as wt

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    se_file_object = 1
    owner_information = 0x00000001
    dacl_information = 0x00000004
    sddl_revision_1 = 1

    advapi32.GetNamedSecurityInfoW.restype = wt.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wt.LPCWSTR,
        ctypes.c_int,
        wt.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wt.BOOL
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p,
        wt.DWORD,
        wt.DWORD,
        ctypes.POINTER(wt.LPWSTR),
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    descriptor = ctypes.c_void_p()
    wanted = owner_information | dacl_information
    rc = advapi32.GetNamedSecurityInfoW(
        str(path), se_file_object, wanted, None, None, None, None, ctypes.byref(descriptor)
    )
    if rc != 0:
        raise OSError(rc, f"GetNamedSecurityInfoW failed with {rc}")

    out = wt.LPWSTR()
    size = ctypes.c_ulong()
    try:
        ok = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, sddl_revision_1, wanted, ctypes.byref(out), ctypes.byref(size)
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "ConvertSecurityDescriptor... failed")
        value = out.value or ""
    finally:
        if out:
            kernel32.LocalFree(ctypes.cast(out, ctypes.c_void_p))
        kernel32.LocalFree(descriptor)
    return value


def restrict_to_owner(path: Path) -> None:
    """Best-effort: make *path* readable only by its owner (FR-005, FR-039).

    On POSIX this is exact. On Windows a file created under the user's profile already
    inherits an owner-only ACL, and rewriting the ACL from a normal process is more
    likely to break inheritance than to improve matters — so this is a no-op there and
    `check()` reports what actually held.
    """
    if os.name == "posix":
        try:
            path.chmod(0o600)
        except OSError:
            pass
