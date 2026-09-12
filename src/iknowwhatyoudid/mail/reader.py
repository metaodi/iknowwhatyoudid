"""One reader, every mail provider (FR-026, FR-028, FR-029).

`MailReader` implements `SourceReader` once and dispatches on kind. Everything above it —
the store, attribution, corrections, querying — sees records, not providers.

That is what FR-029 asks for, and it is testable rather than aspirational: adding a fifth
provider means writing a module that yields header dicts and adding one line to
`_READERS`. Nothing else in the codebase learns about it.

A message that cannot become a record is **skipped and named**, never silently dropped.
An account that fails entirely is skipped and named too, and the other accounts still
ingest — a source the user believes is being read but is not produces a gap in a
timesheet that nobody checks.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import findings as f
from ..config.model import ConfiguredSource
from ..auth import flow, tokens as token_store
from ..errors import AuthorisationError, MailReadError
from ..kinds.spec import CredentialHandle, LiveCheckResult
from ..net.http import Client
from ..records.model import NormalizedRecord, RunMode
from .. import addresses as addr
from . import gmail, graph, mbox, message as msg
from .message import MessageRejected, Provider

MISSING_ADDRESSES = "mail-addresses-missing"
MALFORMED_ADDRESS = "mail-address-malformed"
MISSING_PATHS = "mail-paths-missing"
ARCHIVE_UNREADABLE = "mail-archive-unreadable"

#: Which provider module answers for which configured kind.
_PROVIDER_FOR_KIND = {
    "mail.outlook": Provider.GRAPH,
    "mail.gmail": Provider.GMAIL,
    # Hey is an export, not a live source: its CLI cannot supply recipients or a
    # Message-ID (research R1). The provider is recorded as HEY so a record says where the
    # mail came from, but the reading is an archive read.
    "mail.hey": Provider.HEY,
    "mail.mbox": Provider.MBOX,
}


def own_addresses(source: ConfiguredSource) -> list[str]:
    raw = source.settings.get("addresses", [])
    return [str(item) for item in raw] if isinstance(raw, list) else []


def archive_paths(source: ConfiguredSource) -> list[str]:
    raw = source.settings.get("paths", [])
    return [str(item) for item in raw] if isinstance(raw, list) else []


def expand(patterns: Sequence[str]) -> list[Path]:
    """`~` and globs, as `git.local` already does for repository locations."""
    import os
    from glob import glob

    found: list[Path] = []
    for pattern in patterns:
        expanded = os.path.expanduser(pattern)
        if any(ch in expanded for ch in "*?["):
            found.extend(Path(p) for p in sorted(glob(expanded)))
        else:
            found.append(Path(expanded))
    return found


class MailReader:
    """Reads mail accounts. Never writes to one."""

    def __init__(self) -> None:
        self._skipped: list[str] = []
        #: Account name → the point to resume from. Seeded before a read and drained
        #: after, so the reader never touches the store itself.
        self._resumption: dict[str, str | None] = {}
        #: Where `config.toml` is, so `tokens.toml` can be found beside it.
        self._config_path: Path | None = None

    def use_config_path(self, path: Path) -> None:
        self._config_path = path

    def drain_skips(self) -> Sequence[str]:
        """Everything skipped since the last call (FR-017, FR-020, SC-011)."""
        skipped = tuple(self._skipped)
        self._skipped.clear()
        return skipped

    # --- validation, offline ------------------------------------------------------------

    def validate(self, source: ConfiguredSource) -> Sequence[f.Finding]:
        """Contacts nothing. `sources validate` is run constantly and must stay fast."""
        problems: list[f.Finding] = []
        declared = own_addresses(source)

        if not declared:
            problems.append(
                f.blocking(
                    MISSING_ADDRESSES,
                    "no addresses declared",
                    source_name=source.name,
                    key_path="addresses",
                    remedy=(
                        "Add at least one address that is yours. Without it the "
                        "connector cannot tell your mail from anyone else's, so it "
                        "would record nothing."
                    ),
                )
            )
        for index, address in enumerate(declared):
            if not addr.is_valid(address):
                problems.append(
                    f.blocking(
                        MALFORMED_ADDRESS,
                        f"{address!r} is not a mail address",
                        source_name=source.name,
                        key_path=f"addresses[{index}]",
                        remedy="It can never match, so it is a typo rather than an intention.",
                    )
                )

        if source.kind in ("mail.mbox", "mail.hey") and not archive_paths(source):
            problems.append(
                f.blocking(
                    MISSING_PATHS,
                    "no archive paths given",
                    source_name=source.name,
                    key_path="paths",
                    remedy="Point `paths` at one or more exported `.mbox` files.",
                )
            )
        return problems

    def check_live(
        self, source: ConfiguredSource, credential: CredentialHandle | None
    ) -> LiveCheckResult:
        """Confirm the source is reachable. Read-only, and never ingests."""
        if source.kind in ("mail.mbox", "mail.hey"):
            missing = [p for p in expand(archive_paths(source)) if not p.is_file()]
            if missing:
                return LiveCheckResult(
                    False, f"{len(missing)} archive(s) not found: {missing[0]}"
                )
            return LiveCheckResult(True, "archive readable")
        return LiveCheckResult(False, "reading not yet implemented for this kind")

    # --- reading ---------------------------------------------------------------------------

    def read(
        self,
        source: ConfiguredSource,
        credential: CredentialHandle | None,
        since: datetime | None,
        mode: RunMode,
    ) -> Iterator[NormalizedRecord]:
        provider = _PROVIDER_FOR_KIND.get(source.kind)
        if provider is None:  # pragma: no cover — the registry refuses first
            raise MailReadError(f"{source.kind} is not a mail kind")

        declared = own_addresses(source)
        if provider in (Provider.MBOX, Provider.HEY):
            yield from self._read_archives(source, declared, since, provider)
            return
        if provider in (Provider.GRAPH, Provider.GMAIL):
            yield from self._read_api(source, declared, since, provider)
            return

        raise MailReadError(
            f"reading {source.kind} is not implemented yet",
            remedy="Configure a `mail.mbox` source, or wait for this connector.",
        )

    # --- the two API providers ------------------------------------------------------------

    def _read_api(
        self,
        source: ConfiguredSource,
        declared: list[str],
        since: datetime | None,
        provider: Provider,
    ) -> Iterator[NormalizedRecord]:
        """Read one Microsoft 365 or Gmail account, resuming from its stored cursor.

        One path for both. They differ only in the module that knows the endpoints and
        the scopes, which is what FR-029 asks for: adding a provider should not add a
        branch here.

        A rejected cursor is not a failure. Both providers expire them, and the answer is
        to read the window again — wider, but correct, and the store deduplicates by
        `source_id` so nothing is doubled.
        """
        api = graph if provider is Provider.GRAPH else gmail
        hosts = (
            {graph.GRAPH_HOST, graph.LOGIN_HOST}
            if provider is Provider.GRAPH
            else {gmail.GMAIL_HOST, gmail.OAUTH_HOST}
        )
        stored = self._token_for(source)
        client = Client(allowed_hosts=frozenset(hosts))

        try:
            issued = flow.refresh(
                client,
                token_endpoint=self._token_endpoint(stored, provider),
                client_id=stored.client_id,
                refresh_token=stored.refresh_token,
                scopes=api.SCOPES,
            )
        except AuthorisationError as exc:
            raise MailReadError(exc.message, remedy=exc.remedy) from exc

        resumption = self._resumption_for(source)
        try:
            yield from self._drain(
                api, client, issued.access_token, source, declared, since, resumption,
                provider,
            )
        except MailReadError:
            if resumption is None:
                raise
            self._skipped.append(
                f"{source.name}: the stored resumption point was refused, so the window "
                f"was read again from the start"
            )
            self._resumption[source.name] = None
            yield from self._drain(
                api, client, issued.access_token, source, declared, since, None, provider
            )

    def _drain(
        self,
        api: Any,
        client: Client,
        token: str,
        source: ConfiguredSource,
        declared: list[str],
        since: datetime | None,
        resumption: str | None,
        provider: Provider,
    ) -> Iterator[NormalizedRecord]:
        for headers, has_attachment, new_point in api.read(
            client, token=token, since=since, resumption_point=resumption
        ):
            if new_point:
                self._resumption[source.name] = new_point
            if not headers:
                continue
            try:
                message = msg.build(
                    headers=headers,
                    account=source.name,
                    provider=provider,
                    own_addresses=declared,
                    has_attachments=has_attachment,
                )
            except MessageRejected as rejected:
                if "not one of this account" not in rejected.reason:
                    self._skipped.append(f"{source.name}: {rejected}")
                continue
            yield msg.to_record(message)

    def _token_for(self, source: ConfiguredSource) -> token_store.StoredToken:
        path = token_store.path_for(self._config_path or Path("config.toml"))
        stored = token_store.load(path).get(source.name)
        if stored is None:
            raise MailReadError(
                f"{source.name} has no stored authorisation",
                remedy=f"Run `ikwyd sources authorise {source.name}`.",
            )
        return stored

    @staticmethod
    def _token_endpoint(stored: token_store.StoredToken, provider: Provider) -> str:
        if provider is Provider.GMAIL:
            return f"https://{gmail.OAUTH_HOST}/token"
        tenant = stored.tenant or "organizations"
        return f"https://{graph.LOGIN_HOST}/{tenant}/oauth2/v2.0/token"

    def _resumption_for(self, source: ConfiguredSource) -> str | None:
        return self._resumption.get(source.name)

    def drain_resumption_points(self) -> dict[str, str | None]:
        """What each account should resume from next time, then forget it.

        Returned rather than written here because a reader must not touch the store —
        `sources/run.py` owns that, and keeping it there is what lets `0002`'s state
        handling stay source-agnostic.
        """
        points = dict(self._resumption)
        self._resumption.clear()
        return points

    def remember_resumption(self, account: str, point: str | None) -> None:
        """Seed a resumption point from the store before a read."""
        self._resumption[account] = point

    def _read_archives(
        self,
        source: ConfiguredSource,
        declared: list[str],
        since: datetime | None,
        provider: Provider,
    ) -> Iterator[NormalizedRecord]:
        for path in expand(archive_paths(source)):
            try:
                yield from self._read_one_archive(path, source, declared, since, provider)
            except MailReadError as exc:
                # Named in the run's report, never swallowed.
                self._skipped.append(f"{path}: {exc.message}")
                continue

    def _read_one_archive(
        self,
        path: Path,
        source: ConfiguredSource,
        declared: list[str],
        since: datetime | None,
        provider: Provider = Provider.MBOX,
    ) -> Iterator[NormalizedRecord]:
        for headers, has_attachment in mbox.read(path):
            try:
                message = msg.build(
                    headers=headers,
                    account=source.name,
                    provider=provider,
                    own_addresses=declared,
                    has_attachments=has_attachment,
                    # An archive is one snapshot; its silence proves nothing about the
                    # mailbox, so nothing from it may ever be withdrawn (research R13).
                    withdrawable=False,
                )
            except MessageRejected as rejected:
                # A message from someone else is the ordinary case in an archive that
                # holds both directions — expected, and not worth reporting. Anything
                # else is a fault the user should hear about.
                if "not one of this account" not in rejected.reason:
                    self._skipped.append(f"{path.name}: {rejected}")
                continue

            if since is not None and message.sent_at < since:
                continue
            yield msg.to_record(message)


def messages_from_records(
    records: Sequence[NormalizedRecord],
) -> list[NormalizedRecord]:
    """Just the mail ones, for callers that hold a mixed batch."""
    return [r for r in records if r.payload.get("kind") == "mail_sent"]
