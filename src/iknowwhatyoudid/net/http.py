"""The only place this tool makes an HTTP request (FR-018, FR-019).

Every outbound call goes through `Client`, which holds a **host allow-list** built from
the accounts the user configured. A host not on it is refused before a connection is
attempted. This mirrors `git/binary.py` from `0003`, where an allow-list of subcommands
made "read-only" something a reviewer could check rather than something the code
promised: here it makes "no destination other than a configured account" answerable by
reading one file.

There is deliberately no `delete`, `put` or `patch`. A connector cannot reach for a
method that does not exist, so Principle II holds at the level of what is callable
rather than at the level of what is called.

Nothing here logs a URL's query, a request header, or a response body. A token in a
query string is still a token in a log file.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..errors import IkwydError, MailReadError
from ..obs import logging as obs

#: Attempts in total, not retries after the first. Beyond this an account fails and the
#: run continues with the others — a tight retry loop against a corporate tenant is how
#: an account gets throttled, and the user experiences that as their mail breaking.
MAX_ATTEMPTS = 5

#: The first backoff, doubling each time, used only when the provider sends no
#: `Retry-After`. Their figure is always better than ours.
INITIAL_BACKOFF_SECONDS = 1.0

#: Longer than this and the account is better failed than waited on; the run should end
#: in a reasonable time even when a provider is unhappy.
MAX_BACKOFF_SECONDS = 60.0

DEFAULT_TIMEOUT_SECONDS = 30

#: Statuses worth trying again. Everything else is a fact about the request, and asking
#: a second time only burns the rate limit that made 429 appear in the first place.
_RETRYABLE = frozenset({429, 500, 502, 503, 504})


class HostNotAllowedError(IkwydError):
    """A request was made to a host outside the allow-list.

    Not a network error — nothing was contacted. It means the code tried to reach
    somewhere the user never configured, which is a bug worth failing loudly for.
    """


class HttpStatusError(IkwydError):
    """A request completed and the provider refused it.

    Carries the status so a caller can tell "expired credential" from "forbidden by your
    administrator" — FR-010 requires those to be distinguishable, and they differ only by
    what the provider said.
    """

    def __init__(self, status: int, host: str, detail: str = "") -> None:
        super().__init__(
            f"{host} answered {status}" + (f": {detail}" if detail else ""),
            remedy="Nothing was changed at the source. The account was skipped.",
        )
        self.status = status
        self.host = host


def _log(_message: str, **fields: object) -> None:
    """Indirection so a test can capture what would be logged, and assert on it."""
    obs.http_request(
        host=str(fields.get("host", "")),
        method=str(fields.get("method", "")),
        status=fields.get("status", ""),
    )


def _host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


class Client:
    """An HTTP client that can only reach hosts it was told about."""

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._allowed = frozenset(host.lower() for host in allowed_hosts)
        self._timeout = timeout

    def get(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> Any:
        return self._send("GET", url, headers=headers, body=None)

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> Any:
        """POST is here for token exchange only — never to change anything at a source."""
        encoded = urllib.parse.urlencode(form or {}).encode("ascii")
        merged = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
        return self._send("POST", url, headers=merged, body=encoded)

    # --- the machinery ------------------------------------------------------------------

    def _check(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https":
            raise HostNotAllowedError(
                f"refusing a non-HTTPS request to {host or url!r}",
                remedy="Credentials must never cross an unencrypted connection.",
            )
        if host not in self._allowed:
            raise HostNotAllowedError(
                f"{host!r} is not a destination any configured account uses",
                remedy=(
                    "Every host this tool may reach comes from your configuration. "
                    "Run `ikwyd sources destinations` to see the whole list."
                ),
            )
        return host

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None,
        body: bytes | None,
    ) -> Any:
        host = self._check(url)
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, MAX_ATTEMPTS + 1):
            request = urllib.request.Request(url, data=body, method=method)
            for name, value in (headers or {}).items():
                request.add_header(name, value)

            try:
                with urllib.request.urlopen(  # noqa: S310 — scheme and host are checked above
                    request, timeout=self._timeout
                ) as response:
                    payload = response.read()
                # Host and status only. Never the query, never a header, never the body.
                _log("http", host=host, method=method, status=200)
                return json.loads(payload) if payload else None
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                _log("http", host=host, method=method, status=status)
                if status not in _RETRYABLE or attempt == MAX_ATTEMPTS:
                    if status in _RETRYABLE:
                        raise MailReadError(
                            f"{host} was still answering {status} after "
                            f"{MAX_ATTEMPTS} attempts",
                            remedy=(
                                "The provider is rate-limiting or unavailable. Nothing "
                                "was changed at the source; try again later."
                            ),
                        ) from exc
                    raise HttpStatusError(status, host) from exc
                time.sleep(self._wait_for(exc, backoff))
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            except urllib.error.URLError as exc:
                _log("http", host=host, method=method, status="unreachable")
                if attempt == MAX_ATTEMPTS:
                    raise MailReadError(
                        f"{host} could not be reached: {exc.reason}",
                        remedy="Check the connection. Nothing already stored is affected.",
                    ) from exc
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _wait_for(exc: urllib.error.HTTPError, backoff: float) -> float:
        """The provider's `Retry-After` if it sent one, else our own backoff."""
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if raw:
            try:
                return min(float(raw), MAX_BACKOFF_SECONDS)
            except ValueError:
                # It may also be an HTTP date; we do not parse one, we just back off.
                pass
        return backoff
