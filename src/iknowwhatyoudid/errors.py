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


class GitUnavailableError(IkwydError):
    """The git binary is missing, or older than this feature needs.

    A tool requirement, not a Python dependency: reported at validation time as a
    not-ready source naming what to install, never as a traceback at ingestion.
    """


class GitReadError(IkwydError):
    """A repository could not be read.

    Never fatal for a run: the repository is named by path and the rest are still
    ingested. A repository the user believes is being read but is not produces a gap
    in a timesheet that nobody checks.
    """


class GitCommandNotAllowedError(IkwydError):
    """An attempt was made to run a git command that is not on the read-only list.

    Principle II is an allow-list, not a convention — this is what makes it impossible
    to reach `fetch` or `gc` without editing the one module a reviewer checks.
    """


class MailReadError(IkwydError):
    """One mail account could not be read.

    Never fatal for a run: the account is named with a reason and the rest are still
    ingested. An account the user believes is being read but is not produces a gap in a
    timesheet that nobody checks — the same reasoning as `GitReadError`.
    """


class AuthorisationError(IkwydError):
    """Authorisation could not be obtained or refreshed.

    The base for the two cases below. Kept distinct from them because "something went
    wrong signing in" and "your employer must approve this" need different actions from
    the user, and conflating them tells them neither.
    """


class ConsentRequiredError(AuthorisationError):
    """The tenant requires an administrator to approve this application.

    Distinct from a missing or expired credential: nothing the user can do alone will
    fix it, and telling them to re-authorise would send them round a loop that cannot
    terminate.
    """


class TokenExpiredError(AuthorisationError):
    """A stored refresh token was rejected.

    Expected rather than exceptional for Google, which expires tokens from apps in
    testing status after seven days (research R4). Reported with the command that fixes
    it, and never fatal for the other accounts in the run.
    """


class MappingError(ConfigError):
    """The project mapping file could not be used as given."""
