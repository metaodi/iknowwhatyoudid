"""The one door to the network (FR-018, FR-019).

Nothing here reaches a real host. The transport is substituted, and what is asserted is
the policy around it: which hosts are reachable at all, how a rate limit is obeyed, when
retrying stops, and what is allowed to appear in a log.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from iknowwhatyoudid.errors import MailReadError
from iknowwhatyoudid.net import http


class FakeResponse:
    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self._body = body
        self.status = status
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def allowing(*hosts: str) -> http.Client:
    return http.Client(allowed_hosts=frozenset(hosts))


# --- the allow-list --------------------------------------------------------------------


def test_a_host_not_on_the_allow_list_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-019 — the whole egress surface is one frozen set.

    Refused *before* any connection is attempted, so a typo in a URL cannot become a
    request to somewhere unintended.
    """
    called = False

    def must_not_run(*_: object, **__: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(urllib.request, "urlopen", must_not_run)
    client = allowing("graph.microsoft.com")

    with pytest.raises(http.HostNotAllowedError) as raised:
        client.get("https://evil.example/steal")

    assert "evil.example" in str(raised.value)
    assert not called, "the request must be refused before it is attempted"


def test_an_allowed_host_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: FakeResponse(b'{"ok":true}')
    )
    client = allowing("graph.microsoft.com")
    assert client.get("https://graph.microsoft.com/v1.0/me") == {"ok": True}


def test_plain_http_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token must never cross an unencrypted connection."""
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    client = allowing("graph.microsoft.com")
    with pytest.raises(http.HostNotAllowedError):
        client.get("http://graph.microsoft.com/v1.0/me")


def test_a_subdomain_is_not_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """`graph.microsoft.com.evil.example` must not pass as `graph.microsoft.com`."""
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    client = allowing("graph.microsoft.com")
    with pytest.raises(http.HostNotAllowedError):
        client.get("https://graph.microsoft.com.evil.example/v1.0/me")


# --- rate limits ------------------------------------------------------------------------


def _rate_limited(retry_after: str | None, then: FakeResponse) -> Any:
    attempts: list[int] = []

    def urlopen(request: Any, *_: object, **__: object) -> FakeResponse:
        attempts.append(1)
        if len(attempts) == 1:
            headers = {"Retry-After": retry_after} if retry_after else {}
            raise urllib.error.HTTPError(
                request.full_url, 429, "Too Many Requests", headers, None  # type: ignore[arg-type]
            )
        return then

    urlopen.attempts = attempts  # type: ignore[attr-defined]
    return urlopen


def test_retry_after_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-018 — a tight retry loop is how a corporate account gets throttled.

    The user would experience that as their employer's mail breaking, so the header the
    provider sends is obeyed rather than guessed at.
    """
    urlopen = _rate_limited("7", FakeResponse(b'{"ok":true}'))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    client = allowing("graph.microsoft.com")
    assert client.get("https://graph.microsoft.com/v1.0/me") == {"ok": True}
    assert slept == [7.0], "the provider's own figure, not ours"


def test_without_retry_after_it_backs_off(monkeypatch: pytest.MonkeyPatch) -> None:
    urlopen = _rate_limited(None, FakeResponse(b'{"ok":true}'))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    client = allowing("graph.microsoft.com")
    client.get("https://graph.microsoft.com/v1.0/me")
    assert slept == [1.0], "the first backoff is one second"


def test_retrying_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Five attempts, then the account fails — it never retries indefinitely."""
    attempts: list[int] = []

    def always_429(request: Any, *_: object, **__: object) -> FakeResponse:
        attempts.append(1)
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", always_429)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    client = allowing("graph.microsoft.com")
    with pytest.raises(MailReadError):
        client.get("https://graph.microsoft.com/v1.0/me")
    assert len(attempts) == http.MAX_ATTEMPTS


def test_a_client_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 401 will not become a 200 by asking again; retrying it just burns the limit."""
    attempts: list[int] = []

    def unauthorised(request: Any, *_: object, **__: object) -> FakeResponse:
        attempts.append(1)
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", unauthorised)
    client = allowing("graph.microsoft.com")

    with pytest.raises(http.HttpStatusError) as raised:
        client.get("https://graph.microsoft.com/v1.0/me")
    assert raised.value.status == 401
    assert len(attempts) == 1


# --- what may be logged -----------------------------------------------------------------


def test_the_log_carries_a_host_and_a_status_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-008 — a token in a query string is still a token in a log file."""
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: FakeResponse(b'{"secret":"s3cr3t"}')
    )
    lines: list[str] = []
    monkeypatch.setattr(http, "_log", lambda message, **fields: lines.append(f"{message} {fields}"))

    client = allowing("graph.microsoft.com")
    client.get(
        "https://graph.microsoft.com/v1.0/me?access_token=s3cr3t",
        headers={"Authorization": "Bearer s3cr3t"},
    )

    joined = " ".join(lines)
    assert "graph.microsoft.com" in joined
    assert "s3cr3t" not in joined, "a credential reached the log"
    assert "Authorization" not in joined
    assert "access_token" not in joined


def test_only_get_and_post_exist() -> None:
    """There is no `delete` or `patch` to call, so no connector can reach for one."""
    surface = {name for name in dir(http.Client) if not name.startswith("_")}
    assert surface == {"get", "post"}, surface
