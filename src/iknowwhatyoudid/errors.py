"""Exception hierarchy and its mapping onto process exit codes.

Exit codes are part of the CLI contract (contracts/cli-commands.md):

    0  success
    1  the operation failed
    2  usage error, or the store was written by a newer version
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


class IkwydError(Exception):
    """Base for every error this tool raises deliberately."""

    exit_code = EXIT_FAILED

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy


class UsageError(IkwydError):
    """The command was invoked wrongly."""

    exit_code = EXIT_USAGE


class StoreError(IkwydError):
    """Something is wrong with the store itself."""


class StoreLockedError(StoreError):
    """Another command holds the store (FR-025)."""


class StoreCorruptError(StoreError):
    """The store failed an integrity check, or is not a store at all (FR-026).

    Raising this never deletes or overwrites anything: a corrupt store may still be
    the only copy of a year of withdrawn records and corrections.
    """


class StoreTooNewError(StoreError):
    """The store was written by a newer version of the tool (FR-022).

    Exit code 2 rather than 1: this is not a failed operation, it is a refusal to
    touch the store at all.
    """

    exit_code = EXIT_USAGE


class UnsupportedSQLiteError(StoreError):
    """The available SQLite is older than this schema needs."""


class MigrationError(StoreError):
    """A migration could not complete (FR-021).

    The store is left at its previous version; the transaction has already rolled back
    by the time this is raised.
    """


class BatchError(IkwydError):
    """A batch handed to the store violates the record contract."""


class ConfigError(IkwydError):
    """The configuration could not be used as given."""


class ConfigParseError(ConfigError):
    """The configuration file is not valid TOML (FR-004).

    Exit code 2 rather than 1: a broken file and a valid file describing a broken
    source are different problems, and a script driving this tool must tell them apart.
    """

    exit_code = EXIT_USAGE

    def __init__(
        self,
        message: str,
        *,
        remedy: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message, remedy=remedy)
        self.line = line
        self.column = column


class ConfigNotFoundError(ConfigError):
    """No configuration file exists at the resolved path (FR-002)."""


class UnknownKindError(ConfigError):
    """A source names a kind this build does not carry (FR-029)."""


class CredentialUnreadableError(ConfigError):
    """A credential store exists but could not be read (FR-021)."""
