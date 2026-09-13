"""What the user is told when a provider refuses — and the debt this file settles.

`0004` specified this classification and shipped it **unreachable**. `net/http.py` read the
response body and threw it away, raising `HttpStatusError(status, host)` with no detail, so
every marker in `_CONSENT_MARKERS` and `_EXPIRED_MARKERS` was matched against the string
`"host answered 400"` and none could ever fire. The tests that existed passed because they
constructed the error *with* a detail themselves, bypassing the module that was supposed to
supply one.

The cost was a day: `ikwyd sources authorise` failed for Gmail with "authorisation was
refused" and nothing else, twice, before anyone thought to look at the log and find a bare
`status=400`.

So this file tests two things that were changed without tests during that diagnosis
(`0006` FR-017): that `net/http.py` **carries** the body, and that `_classify` **uses** it.
Neither is interesting on its own; together they are the difference between a tool that can
be debugged and one that cannot.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from iknowwhatyoudid.auth import flow
from iknowwhatyoudid.errors import (
    AuthorisationError,
    ConsentRequiredError,
    TokenExpiredError,
)
from iknowwhatyoudid.net import http
from iknowwhatyoudid.net.http import HttpStatusError

#: The response that produced feature `0006`, verbatim.
GOOGLE_SAID = (
    '{\n  "error": "invalid_request",\n'
    '  "error_description": "client_secret is missing."\n}'
)


def classify(detail: str, status: int = 400) -> AuthorisationError:
    """Run one refusal through the classifier the way `flow` does."""
    return flow._classify(HttpStatusError(status, "oauth2.googleapis.com", detail))


# --- FR-015: the refusals the tool understands ------------------------------------------------


def test_a_consent_marker_says_an_administrator_must_act() -> None:
    """The worst outcome this guards against is a loop the user cannot escape.

    Telling someone to re-authorise when their employer's administrator is the one who has
    to act sends them round a circle that cannot terminate.
    """
    error = classify('{"error": "invalid_grant", "suberror": "AADSTS65001"}')

    assert isinstance(error, ConsentRequiredError)
    assert "administrator" in error.message.lower()
    assert error.remedy is not None
    assert "will not help" in error.remedy


def test_an_expiry_marker_says_to_sign_in_again() -> None:
    error = classify('{"error": "invalid_grant", "error_description": "token_expired"}')

    assert isinstance(error, TokenExpiredError)
    assert error.remedy is not None
    assert "authorise" in error.remedy


def test_consent_is_checked_before_expiry() -> None:
    """A body carrying both must not be reported as the one the user can fix alone.

    Microsoft's `AADSTS65001` arrives inside an `invalid_grant`, so a classifier that
    checked expiry first would tell every consent-blocked user to sign in again — forever.
    """
    error = classify('{"error": "invalid_grant", "suberror": "AADSTS65001"}')
    assert isinstance(error, ConsentRequiredError)


# --- FR-014: the refusal the tool does not understand -----------------------------------------


def test_an_unrecognised_refusal_shows_the_providers_own_words() -> None:
    """FR-014 — using the actual response that made this feature necessary.

    This is the branch reached when the tool has nothing to add, which makes it the one
    where swallowing the provider's message leaves the user with nothing at all. If this
    test ever goes red, the next Gmail failure takes a day again.
    """
    error = classify(GOOGLE_SAID)

    assert type(error) is AuthorisationError
    assert "client_secret is missing." in error.message


def test_an_empty_body_still_names_the_host_and_status() -> None:
    """Spec Edge Cases — less than a message, but more than nothing."""
    error = classify("")

    assert "oauth2.googleapis.com" in error.message
    assert "400" in error.message


def test_every_refusal_carries_either_an_interpretation_or_the_providers_words() -> None:
    """SC-005, stated as the property rather than case by case.

    Three shapes, one rule: the user never gets a message that says only that something
    went wrong.
    """
    for detail in ('{"suberror": "AADSTS65001"}', '{"error": "invalid_grant"}', GOOGLE_SAID, ""):
        error = classify(detail)
        interpreted = isinstance(error, ConsentRequiredError | TokenExpiredError)
        quoted = detail and detail in error.message
        assert interpreted or quoted or "400" in error.message, detail


# --- FR-013: bounds ----------------------------------------------------------------------------


class FakeHTTPError(urllib.error.HTTPError):
    """An `HTTPError` whose body is whatever a test wants it to be."""

    def __init__(self, body: bytes, status: int = 400) -> None:
        super().__init__(
            url="https://oauth2.googleapis.com/token",
            code=status,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(body),
        )


def test_a_long_body_is_truncated_to_the_declared_maximum() -> None:
    """FR-013 — asserted against the named constant, not a literal.

    An OAuth error body is a short JSON object. Anything appreciably longer is a provider's
    HTML error page, and a page of markup in a terminal helps nobody.
    """
    refusal = http._refusal(FakeHTTPError(b"<html>" + b"x" * 900 + b"</html>"))

    assert len(refusal) == http.MAX_REFUSAL_CHARACTERS


def test_a_short_body_is_untouched() -> None:
    refusal = http._refusal(FakeHTTPError(GOOGLE_SAID.encode("utf-8")))
    assert refusal == GOOGLE_SAID


def test_a_body_that_is_not_utf8_does_not_raise() -> None:
    """Spec Edge Cases — a provider answering in something else must not become a crash."""
    refusal = http._refusal(FakeHTTPError(b"\xff\xfe not valid utf-8 \x80"))
    assert isinstance(refusal, str)
    assert "not valid utf-8" in refusal


# --- FR-012: the body actually reaches the caller ----------------------------------------------


def test_a_refusal_carries_the_body_into_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-012 — the half that was missing, and which made the classification dead code.

    Tested through `Client` rather than through `_refusal` alone, because the defect was
    not in reading the body: it was that the reading and the raising were not connected.
    """

    def refuse(request: object, timeout: object = None) -> object:
        raise FakeHTTPError(GOOGLE_SAID.encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    client = http.Client(allowed_hosts=frozenset({"oauth2.googleapis.com"}))

    with pytest.raises(HttpStatusError) as caught:
        client.post("https://oauth2.googleapis.com/token", form={"client_id": "an-app"})

    assert "client_secret is missing." in str(caught.value), (
        "the response body was read and discarded — the state that made this bug take a day"
    )


# --- FR-010: and does not reach the log ---------------------------------------------------------


def test_the_log_records_only_host_method_and_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """FR-010 — the body reaches the user; it must not reach a file that persists.

    A log is re-read later, attached to issues, and shared. What is acceptable on a
    terminal for one second is not acceptable there.
    """
    logged: list[dict[str, object]] = []

    def capture(message: str, **fields: object) -> None:
        logged.append(dict(fields))

    monkeypatch.setattr(http, "_log", capture)

    def refuse(request: object, timeout: object = None) -> object:
        raise FakeHTTPError(GOOGLE_SAID.encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    client = http.Client(allowed_hosts=frozenset({"oauth2.googleapis.com"}))
    with pytest.raises(HttpStatusError):
        client.post("https://oauth2.googleapis.com/token", form={"client_id": "an-app"})

    assert logged, "nothing was logged at all"
    for entry in logged:
        assert set(entry) <= {"host", "method", "status"}, f"the log gained a field: {entry}"
        assert "client_secret" not in str(entry)
        assert "invalid_request" not in str(entry)
