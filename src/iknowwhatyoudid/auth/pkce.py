"""Proof Key for Code Exchange, and the loopback that receives the code (research R7).

PKCE exists because a native application cannot keep a secret: anything compiled into the
binary is readable by whoever has the binary. Instead the client invents a random verifier,
sends only its hash when starting the flow, and proves possession by sending the verifier
when redeeming the code. An intercepted authorisation code is then useless on its own.

The redirect goes to `127.0.0.1` on a port the operating system picks, which keeps the
code out of the terminal and out of shell history. The server accepts **one** request and
stops.

Standard library only — `secrets`, `hashlib`, `base64`, `http.server`. Verified present.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

#: RFC 7636 allows 43–128 characters. 64 bytes of entropy encodes to 86, comfortably
#: inside the range and well beyond what a guess could reach.
VERIFIER_BYTES = 64

#: A browser redirect that never arrives should not hang a terminal for ever.
DEFAULT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class Challenge:
    """The pair that binds an authorisation request to the client that made it."""

    verifier: str
    challenge: str
    method: str = "S256"
    state: str = ""


def new_challenge() -> Challenge:
    """A fresh verifier, its SHA-256 challenge, and a state value.

    `state` is unrelated to PKCE and guards a different attack: it is echoed back by the
    provider, so a redirect that arrives without it — or with someone else's — is not the
    one this process started.
    """
    verifier = _b64(secrets.token_bytes(VERIFIER_BYTES))
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return Challenge(
        verifier=verifier,
        challenge=_b64(digest),
        method="S256",
        state=_b64(secrets.token_bytes(16)),
    )


def _b64(raw: bytes) -> str:
    """base64url without padding, as RFC 7636 requires."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class _Handler(BaseHTTPRequestHandler):
    """Answers exactly one redirect, then lets the server stop."""

    received: dict[str, str] = {}  # noqa: RUF012 — shared with the server instance

    def do_GET(self) -> None:  # noqa: N802 — the name is BaseHTTPRequestHandler's
        query = urllib.parse.urlparse(self.path).query
        parsed = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        type(self).received = parsed

        ok = "code" in parsed
        body = _PAGE_OK if ok else _PAGE_DENIED
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        """Silence. The default handler prints the request line, which holds the code."""


_PAGE_OK = (
    b"<!doctype html><meta charset=utf-8><title>Authorised</title>"
    b"<p>Authorised. You can close this tab and return to the terminal."
)
_PAGE_DENIED = (
    b"<!doctype html><meta charset=utf-8><title>Not authorised</title>"
    b"<p>No authorisation was granted. You can close this tab."
)


@dataclass(slots=True)
class Loopback:
    """A one-shot local receiver for the redirect."""

    server: HTTPServer
    port: int

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def wait(self, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, str]:
        """Serve until the redirect arrives, or give up.

        Returns whatever the provider sent — `code` and `state` on success, `error` and
        `error_description` when the user declined or the tenant refused. Interpreting
        those is `flow.py`'s job; this only delivers them.
        """
        self.server.timeout = timeout
        _Handler.received = {}

        thread = threading.Thread(target=self.server.handle_request, daemon=True)
        thread.start()
        thread.join(timeout + 1)

        try:
            self.server.server_close()
        except OSError:  # pragma: no cover — already closed
            pass
        return dict(_Handler.received)


def listen() -> Loopback:
    """Bind a loopback port the operating system chooses.

    Port 0 asks for any free port, which avoids both a collision with something already
    running and a fixed port an attacker could sit on first.
    """
    try:
        server = HTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover — no loopback is a broken machine
        raise OSError(f"could not listen on 127.0.0.1: {exc}") from exc
    return Loopback(server=server, port=server.server_address[1])


def authorisation_url(
    *,
    endpoint: str,
    client_id: str,
    scopes: tuple[str, ...],
    redirect_uri: str,
    challenge: Challenge,
) -> str:
    """Where to send the browser."""
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": challenge.state,
            "code_challenge": challenge.challenge,
            "code_challenge_method": challenge.method,
            # Without this a tenant that has already consented returns no refresh token,
            # and every run would need a browser.
            "prompt": "consent",
        }
    )
    return f"{endpoint}?{query}"
