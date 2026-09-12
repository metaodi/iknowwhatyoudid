"""Exchanging and refreshing authorisation (FR-009 to FR-012).

The whole value of this module is in how it *fails*. FR-010 requires four states to be
distinguishable, because each needs a different action from the user:

| State | What it means | What they do |
|---|---|---|
| absent | nothing stored | authorise |
| expired | the refresh token was rejected | authorise again |
| consent required | the tenant will not permit this app | ask their administrator |
| unreachable | a network or provider fault | try later |

"Authentication failed" tells them none of those, and sending someone to re-authorise in a
loop that cannot terminate — because their employer has to act, not them — is the specific
failure this table exists to prevent (research R6).

No token, code or verifier is ever logged, printed, or put in an exception message.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import AuthorisationError, ConsentRequiredError, MailReadError, TokenExpiredError
from ..net.http import Client, HttpStatusError
from .pkce import Challenge

#: Microsoft says so with a code; Google says so with a string. Both mean "your
#: organisation, not you, has to act".
_CONSENT_MARKERS = (
    "AADSTS65001",  # the user or administrator has not consented
    "AADSTS90094",  # the grant requires administrator permission
    "admin_consent_required",
    "consent_required",
    "interaction_required",
)

#: A refresh token that will never work again, however many times it is retried.
_EXPIRED_MARKERS = (
    "invalid_grant",
    "AADSTS70008",  # the refresh token has expired
    "AADSTS50173",  # credentials changed since the token was issued
    "token_expired",
)


@dataclass(frozen=True, slots=True)
class Tokens:
    """What a provider returns. Never rendered, never logged."""

    access_token: str
    refresh_token: str | None
    expires_in: int = 3600
    scope: str = ""

    def __repr__(self) -> str:
        """Redacted, so an accidental `print` or traceback cannot leak it."""
        held = "refresh+access" if self.refresh_token else "access"
        return f"Tokens({held}, redacted)"


def exchange_code(
    client: Client,
    *,
    token_endpoint: str,
    client_id: str,
    code: str,
    redirect_uri: str,
    challenge: Challenge,
) -> Tokens:
    """Redeem an authorisation code, proving possession with the PKCE verifier."""
    return _token_request(
        client,
        token_endpoint,
        {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": challenge.verifier,
        },
    )


def refresh(
    client: Client,
    *,
    token_endpoint: str,
    client_id: str,
    refresh_token: str,
    scopes: tuple[str, ...],
) -> Tokens:
    """Trade a refresh token for a new access token.

    For Google this is the call that fails every seven days while the OAuth app is in
    testing status (research R4). It is an expected event, not an exceptional one: the
    caller reports the account as `credential expired` and the run continues.
    """
    return _token_request(
        client,
        token_endpoint,
        {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(scopes),
        },
    )


def _token_request(client: Client, endpoint: str, form: dict[str, str]) -> Tokens:
    try:
        body = client.post(endpoint, form=form)
    except HttpStatusError as exc:
        raise _classify(exc) from exc
    except MailReadError as exc:
        # `net/http` already exhausted its retries; the provider is simply not answering.
        raise AuthorisationError(
            "the identity provider could not be reached",
            remedy="Try again later. Nothing already stored is affected.",
        ) from exc

    if not isinstance(body, dict) or "access_token" not in body:
        raise AuthorisationError(
            "the identity provider returned no access token",
            remedy="Run the authorisation again.",
        )

    return Tokens(
        access_token=str(body["access_token"]),
        refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
        expires_in=int(body.get("expires_in", 3600)),
        scope=str(body.get("scope", "")),
    )


def _classify(exc: HttpStatusError) -> AuthorisationError:
    """Turn a refusal into the state that tells the user what to do.

    The provider's own message is matched rather than the status code, because a 400 from
    a token endpoint means five different things and only the body distinguishes them.
    """
    detail = str(exc)

    if any(marker in detail for marker in _CONSENT_MARKERS):
        return ConsentRequiredError(
            "your organisation requires an administrator to approve this application",
            remedy=(
                "Re-authorising will not help — an administrator has to grant consent for "
                "the tenant. Until then this account cannot be read; every other source "
                "still ingests."
            ),
        )

    if any(marker in detail for marker in _EXPIRED_MARKERS):
        return TokenExpiredError(
            "the stored authorisation was rejected",
            remedy="Run `ikwyd sources authorise NAME` to sign in again.",
        )

    return AuthorisationError(
        "authorisation was refused",
        remedy="Run `ikwyd sources authorise NAME` to sign in again.",
    )


def classify_redirect(received: dict[str, str], challenge: Challenge) -> str:
    """The authorisation code from a redirect, or a refusal saying why.

    Checks `state` first. A redirect without the value this process generated did not come
    from the request this process made, and redeeming its code would be redeeming
    somebody else's.
    """
    if not received:
        raise AuthorisationError(
            "no redirect arrived before the timeout",
            remedy="Run the command again, and complete the sign-in in the browser.",
        )

    error = received.get("error", "")
    description = received.get("error_description", "")
    if error:
        combined = f"{error} {description}"
        if any(marker in combined for marker in _CONSENT_MARKERS):
            raise ConsentRequiredError(
                "your organisation requires an administrator to approve this application",
                remedy=(
                    "An administrator has to grant consent for the tenant. Re-authorising "
                    "will not help."
                ),
            )
        if error in {"access_denied", "consent_required"}:
            raise AuthorisationError(
                "authorisation was declined",
                remedy="Nothing was changed. Run the command again to try once more.",
            )
        raise AuthorisationError(
            f"the provider refused: {error}",
            remedy="Run the command again.",
        )

    if received.get("state") != challenge.state:
        raise AuthorisationError(
            "the redirect did not match the request this command made",
            remedy=(
                "Nothing was stored. Run the command again, and complete the sign-in in "
                "the browser window it opens."
            ),
        )

    code = received.get("code")
    if not code:
        raise AuthorisationError(
            "the redirect carried no authorisation code",
            remedy="Run the command again.",
        )
    return code
