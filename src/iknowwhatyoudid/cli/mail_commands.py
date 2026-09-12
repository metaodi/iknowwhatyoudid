"""`ikwyd sources authorise` and `ikwyd mail …`.

`authorise` is the **only interactive command in the tool**. `ingest` never opens a
browser: a scheduled or scripted run must never block waiting for one, and a person who
set up a nightly job should not discover it has been sitting on a consent screen since
Tuesday.

It also names the scope in plain words *before* opening the browser. The user is about to
grant access to their mail; they should hear what is being asked for from the tool that
asks, not only from the consent screen that receives it.
"""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..auth import flow, pkce
from ..auth import tokens as token_store
from ..errors import (
    AuthorisationError,
    ConsentRequiredError,
    IkwydError,
    TokenExpiredError,
    UsageError,
)
from ..mail import correspondents as correspondents_repo
from ..mail import gmail, graph
from ..net.http import Client
from ..projects import attribution
from ..records import repository as records_repo
from ..records import timestamps
from .commands import Result
from .render import table, when

#: Exit codes, from contracts/cli-commands.md.
EXIT_DECLINED = 3
EXIT_CONSENT_REQUIRED = 4

#: What the user is told before the browser opens, in their words rather than Microsoft's.
_PLAIN_WORDS = {
    "mail.outlook": (
        "Mail.ReadBasic — read your mail, without message bodies or attachments.",
        "This grant cannot send, delete, move, or mark anything as read.",
    ),
    "mail.gmail": (
        "gmail.metadata — read message headers and labels, never a body or an attachment.",
        "This grant cannot send, delete, or modify anything.",
    ),
}


@dataclass(frozen=True, slots=True)
class Endpoints:
    authorise: str
    token: str


def endpoints_for(kind: str, tenant: str) -> Endpoints:
    if kind == "mail.outlook":
        base = f"https://{graph.LOGIN_HOST}/{tenant or 'organizations'}/oauth2/v2.0"
        return Endpoints(f"{base}/authorize", f"{base}/token")
    if kind == "mail.gmail":
        return Endpoints(
            f"https://{gmail.ACCOUNTS_HOST}/o/oauth2/v2/auth",
            f"https://{gmail.OAUTH_HOST}/token",
        )
    raise UsageError(
        f"{kind} does not use `sources authorise`",
        remedy="Only Microsoft 365 and Gmail accounts need authorising.",
    )


def scopes_for(kind: str) -> tuple[str, ...]:
    return gmail.SCOPES if kind == "mail.gmail" else graph.SCOPES


def hosts_for(kind: str) -> frozenset[str]:
    if kind == "mail.gmail":
        return frozenset({gmail.ACCOUNTS_HOST, gmail.OAUTH_HOST, gmail.GMAIL_HOST})
    return frozenset({graph.LOGIN_HOST, graph.GRAPH_HOST})


def authorise(
    session: Any,
    *,
    name: str,
    open_browser: bool = True,
) -> Result:
    """Obtain the authorisation one account needs, once."""
    status = session.report.status_for(name)
    if status is None:
        raise UsageError(
            f"no source named {name!r} is configured",
            remedy="Run `ikwyd sources list` to see the names.",
        )

    kind = status.source.kind
    if kind in {"mail.mbox", "mail.hey"}:
        return Result(
            "sources.authorise",
            True,
            session.path,
            {"account": name, "authorised": False, "reason": "no authorisation needed"},
            f"{name} reads an exported file. There is nothing to authorise —\n"
            f"point `paths` at the export and run `ikwyd ingest`.",
        )

    client_id, tenant = _application_for(status.source)
    places = endpoints_for(kind, tenant)
    challenge = pkce.new_challenge()
    loopback = pkce.listen()

    lines = [f"Signing in to {kind.split('.')[1].title()} for {name}."]
    for sentence in _PLAIN_WORDS.get(kind, ()):
        lines.append(f"  Requesting: {sentence}")
    url = pkce.authorisation_url(
        endpoint=places.authorise,
        client_id=client_id,
        scopes=scopes_for(kind),
        redirect_uri=loopback.redirect_uri,
        challenge=challenge,
    )

    if open_browser:
        lines.append(f"Waiting for the redirect on {loopback.redirect_uri} …")
        webbrowser.open(url)
    else:
        lines.append("Open this in a browser, then return here:")
        lines.append(f"  {url}")

    received = loopback.wait()
    code = flow.classify_redirect(received, challenge)

    client = Client(allowed_hosts=hosts_for(kind))
    issued = flow.exchange_code(
        client,
        token_endpoint=places.token,
        client_id=client_id,
        code=code,
        redirect_uri=loopback.redirect_uri,
        challenge=challenge,
    )
    if not issued.refresh_token:
        raise AuthorisationError(
            "the provider returned no refresh token",
            remedy=(
                "Without one, every run would need a browser. Check that the application "
                "registration requests `offline_access`."
            ),
        )

    path = token_store.path_for(session.path)
    token_store.save(
        path,
        token_store.StoredToken(
            account=name,
            refresh_token=issued.refresh_token,
            client_id=client_id,
            tenant=tenant,
        ),
    )

    lines.append("")
    lines.append(f"Authorised. Token stored in {path} (readable by you alone).")
    lines.append("Run `ikwyd ingest` to read.")
    return Result(
        "sources.authorise",
        True,
        session.path,
        {"account": name, "authorised": True, "token_path": str(path)},
        "\n".join(lines),
    )


def _application_for(source: Any) -> tuple[str, str]:
    """The client_id and tenant for an account, from its settings.

    Deliberately **not** from `credentials.toml`. A client_id is public — it appears in
    every authorisation URL — and that file registers everything it holds with the
    redaction filter, which would mask the client_id out of the URL this command prints.
    """
    client_id = source.settings.get("client_id")
    if not client_id:
        raise UsageError(
            f"{source.name} has no `client_id`",
            remedy=(
                "Register an application in your provider's console and add "
                "`client_id = \"…\"` to this source. It is not a secret."
            ),
        )
    return str(client_id), str(source.settings.get("tenant", ""))


# --- mail list ---------------------------------------------------------------------------


def mail_list(
    session: Any,
    *,
    since: str | None = None,
    until: str | None = None,
    account: str | None = None,
    project: str | None = None,
) -> Result:
    """Mail activity, filtered. Always says that received mail is not read."""
    from .commands import _parse_date

    found = records_repo.query(
        session.connection,
        since=_parse_date(since),
        until=_parse_date(until, end_of_day=True),
        source=account,
    )
    mail = [r for r in found if r.payload.get("kind") == "mail_sent"]

    from ..derived import repository as derived_repo

    attributed = derived_repo.projects_for_records(
        session.connection, [record.id for record in mail]
    )

    rows = []
    payload = []
    for record in mail:
        name, rule = attributed.get(record.id, (None, None))
        if project and name != project:
            continue
        recipients = record.payload.get("recipients") or []
        to = ", ".join(
            str(entry[0]) for entry in recipients if isinstance(entry, list | tuple)
        )
        marked = (
            f"{name} (ad hoc)"
            if rule and attribution.Rule(rule) in attribution.AD_HOC_RULES
            else (name or "—")
        )
        rows.append(
            [
                when(record.occurred_utc),
                str(record.payload.get("account", record.source)),
                marked,
                to[:40],
                str(record.payload.get("subject", ""))[:44],
            ]
        )
        payload.append(
            {
                "when": record.occurred_utc,
                "account": record.payload.get("account"),
                "project": name,
                "project_rule": rule,
                "to": [str(e[0]) for e in recipients if isinstance(e, list | tuple)],
                "subject": record.payload.get("subject"),
            }
        )

    body = table(["WHEN", "ACCOUNT", "PROJECT", "TO", "SUBJECT"], rows) or "No mail."
    # FR-049. A day that looks empty must be distinguishable from a day that was empty.
    tail = f"{len(rows):,} messages · sent mail only — received mail is not read"

    return Result(
        "mail.list",
        True,
        session.path,
        {"messages": payload, "sent_mail_only": True},
        f"{body}\n\n{tail}",
    )


def mail_correspondents(session: Any, *, project: str | None = None) -> Result:
    """Who contributes most to a project (FR-054).

    The unmapped count is the point of the command: a correspondent sitting in an ad-hoc
    project is a mapping nobody has written yet, and ranking them is how that becomes
    discoverable rather than something to guess at.
    """
    found = correspondents_repo.contributions(session.connection, project=project)

    rows = []
    for entry in found:
        label = entry.project or "—"
        if entry.project and entry.project_is_ad_hoc:
            label = f"{entry.project} (ad hoc)"
        rows.append(
            [
                entry.address[:34],
                label[:30],
                f"{entry.messages:,}",
                when(entry.last_seen_utc)[:10],
            ]
        )

    unmapped = sum(1 for e in found if e.project_is_ad_hoc or not e.project)
    body = table(["ADDRESS", "PROJECT", "MESSAGES", "LAST"], rows) or "No correspondents."
    tail = f"{len(found):,} correspondents · {unmapped:,} not yet mapped to a project"

    return Result(
        "mail.correspondents",
        True,
        session.path,
        {
            "correspondents": [
                {
                    "address": e.address,
                    "domain": e.domain,
                    "project": e.project,
                    "project_is_ad_hoc": e.project_is_ad_hoc,
                    "messages": e.messages,
                    "last_seen_utc": e.last_seen_utc,
                }
                for e in found
            ],
            "unmapped": unmapped,
        },
        f"{body}\n\n{tail}",
    )


def exit_code_for(error: IkwydError) -> int:
    """The contract's codes: declined and consent-required are not ordinary failures."""
    if isinstance(error, ConsentRequiredError):
        return EXIT_CONSENT_REQUIRED
    if isinstance(error, TokenExpiredError):
        return error.exit_code
    if isinstance(error, AuthorisationError) and "declined" in error.message:
        return EXIT_DECLINED
    return error.exit_code
