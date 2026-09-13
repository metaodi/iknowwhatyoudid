"""What each provider's token exchange actually carries.

Gmail could not be authorised at all before `0006`: Google's token endpoint refuses the
exchange for an `installed` client without a `client_secret`, and this tool sent none
([research R1](../../specs/0006-gmail-client-secret/research.md)).

Every assertion here is about **the request that was made**, not about the outcome. That is
deliberate and is why the token endpoint is substituted rather than mocked at a higher
level: "Microsoft carries no secret" is a statement about absence, and absence cannot be
proved by watching a request succeed.

Nothing here contacts a provider, opens a browser, or signs in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import webbrowser

from iknowwhatyoudid.auth import flow, pkce
from iknowwhatyoudid.cli import mail_commands
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.credentials import redaction

GMAIL_SECRET = "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-this-account"
CODE = "an-authorisation-code"
FIXED_STATE = "a-fixed-state-value"


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    redaction.clear()


class Recorder:
    """A token endpoint that answers plausibly and remembers what it was sent."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, str]]] = []

    def post(self, url: str, *, form: dict[str, str] | None = None, **_: object) -> object:
        self.posts.append((url, dict(form or {})))
        return {
            "access_token": "an-access-token",
            "refresh_token": "a-refresh-token",
            "expires_in": 3600,
            "scope": "",
        }

    def get(self, url: str, **_: object) -> object:  # pragma: no cover
        raise AssertionError("the token flow never GETs")

    @property
    def last_form(self) -> dict[str, str]:
        assert self.posts, "no request was made"
        return self.posts[-1][1]


# --- the configuration the tests run against -------------------------------------------------


def written(tmp_path: Path, *, gmail_secret: str | None, outlook_secret: str | None) -> Path:
    """A configuration directory holding one Gmail and one Microsoft account."""
    space = tmp_path / "config-dir"
    space.mkdir(exist_ok=True)

    (space / "config.toml").write_text(
        "version = 1\n"
        "\n"
        "[[source]]\n"
        'name = "personal-mail"\n'
        'kind = "mail.gmail"\n'
        'credential = "gmail-credential"\n'
        'client_id = "an-app.apps.googleusercontent.com"\n'
        'addresses = ["someone@example.com"]\n'
        "\n"
        "[[source]]\n"
        'name = "work-mail"\n'
        'kind = "mail.outlook"\n'
        'credential = "outlook-credential"\n'
        'client_id = "00000000-0000-0000-0000-000000000000"\n'
        'addresses = ["someone@example.org"]\n',
        encoding="utf-8",
    )

    lines = ["[credential.gmail-credential]"]
    if gmail_secret is not None:
        lines.append(f'client_secret = "{gmail_secret}"')
    lines += ["", "[credential.outlook-credential]"]
    if outlook_secret is not None:
        lines.append(f'client_secret = "{outlook_secret}"')
    (space / "credentials.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    from iknowwhatyoudid.protection import permissions

    permissions.restrict_to_owner(space / "credentials.toml")
    return space / "config.toml"


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    """Substitute everything interactive, and record the token request."""
    recorder = Recorder()

    challenge = pkce.Challenge(
        verifier="a-verifier", challenge="a-challenge", method="S256", state=FIXED_STATE
    )
    monkeypatch.setattr(pkce, "new_challenge", lambda: challenge)

    class FakeLoopback:
        port = 51000

        @property
        def redirect_uri(self) -> str:
            return f"http://127.0.0.1:{self.port}/"

        def wait(self, timeout: int = 300) -> dict[str, str]:
            return {"code": CODE, "state": FIXED_STATE}

    monkeypatch.setattr(pkce, "listen", lambda: FakeLoopback())
    monkeypatch.setattr(mail_commands, "Client", lambda **_: recorder)

    opened: list[str] = []
    # Patched on the module itself, which `mail_commands` holds a reference to.
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    recorder.browser_opened = opened  # type: ignore[attr-defined]
    return recorder


def authorise(config: Path, account: str, tmp_path: Path) -> int:
    return main(
        ["sources", "authorise", account, "--config", str(config), "--store", str(tmp_path / "s.db")]
    )


# --- FR-006: what each provider's exchange carries -------------------------------------------


def test_gmail_carries_the_client_secret(
    tmp_path: Path, signed_in: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-006 — the whole reason this feature exists."""
    config = written(tmp_path, gmail_secret=GMAIL_SECRET, outlook_secret=None)

    code = authorise(config, "personal-mail", tmp_path)
    capsys.readouterr()

    assert code == 0
    assert signed_in.last_form.get("client_secret") == GMAIL_SECRET


def test_microsoft_carries_no_client_secret(
    tmp_path: Path, signed_in: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-006, SC-002 — PKCE exists so a public client holds no secret."""
    config = written(tmp_path, gmail_secret=None, outlook_secret=None)

    code = authorise(config, "work-mail", tmp_path)
    capsys.readouterr()

    assert code == 0
    assert "client_secret" not in signed_in.last_form


def test_a_secret_in_a_microsoft_entry_is_still_not_sent(
    tmp_path: Path, signed_in: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec Edge Cases — a secret that does not belong in a flow must not enter it.

    Someone who pastes a secret into the wrong entry has made a filing mistake. It must not
    become a protocol change.
    """
    config = written(tmp_path, gmail_secret=None, outlook_secret="GOCSPX-pasted-in-the-wrong-place")

    code = authorise(config, "work-mail", tmp_path)
    capsys.readouterr()

    assert code == 0
    assert "client_secret" not in signed_in.last_form
    assert "GOCSPX-pasted-in-the-wrong-place" not in str(signed_in.posts)


def test_no_request_other_than_the_token_exchange_carries_it(
    tmp_path: Path, signed_in: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-008 — the secret belongs to the token endpoint and nowhere else."""
    config = written(tmp_path, gmail_secret=GMAIL_SECRET, outlook_secret=None)

    authorise(config, "personal-mail", tmp_path)
    capsys.readouterr()

    for url, form in signed_in.posts:
        if "client_secret" in form:
            assert url.endswith("/token"), f"a secret was sent to {url}"


def test_the_refresh_request_carries_it_too(tmp_path: Path) -> None:
    """FR-006 — an access token lasts an hour; the refresh is the common path.

    Exercised directly against `flow.refresh`, because reaching it through `ingest` needs a
    stored token, a store and a live-looking mailbox — none of which changes what is being
    asserted: the form carries the secret.
    """
    recorder = Recorder()

    flow.refresh(
        recorder,  # type: ignore[arg-type]
        token_endpoint="https://oauth2.googleapis.com/token",
        client_id="an-app.apps.googleusercontent.com",
        refresh_token="a-stored-refresh-token",
        scopes=("https://www.googleapis.com/auth/gmail.metadata",),
        client_secret=GMAIL_SECRET,
    )

    assert recorder.last_form.get("client_secret") == GMAIL_SECRET


def test_a_refresh_without_one_sends_none(tmp_path: Path) -> None:
    """The Microsoft path, at the same level. Absence is structural, not conditional."""
    recorder = Recorder()

    flow.refresh(
        recorder,  # type: ignore[arg-type]
        token_endpoint="https://login.microsoftonline.com/organizations/oauth2/v2.0/token",
        client_id="an-app",
        refresh_token="a-stored-refresh-token",
        scopes=("Mail.ReadBasic", "offline_access"),
    )

    assert "client_secret" not in recorder.last_form


# --- FR-007: a Gmail account with no secret --------------------------------------------------


def test_a_missing_secret_fails_before_a_browser_opens(
    tmp_path: Path, signed_in: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-007, SC-004.

    Asserted on the browser never being invoked, not merely on a non-zero exit. A message
    that arrives after a window has already opened has saved nobody anything — the user has
    already signed in, and only then learns it was pointless.
    """
    config = written(tmp_path, gmail_secret=None, outlook_secret=None)

    code = authorise(config, "personal-mail", tmp_path)
    captured = capsys.readouterr()
    text = captured.out + captured.err

    assert code != 0
    assert signed_in.browser_opened == [], "a browser was opened before the check"  # type: ignore[attr-defined]
    assert signed_in.posts == [], "a request was made before the check"

    assert "credentials.toml" in text, "the message must name the file"
    assert "gmail-credential" in text, "the message must name the entry"
    assert "client_secret" in text, "the message must name the key"


def test_an_empty_secret_is_treated_as_missing(
    tmp_path: Path, signed_in: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-005 — so the user gets the message above rather than a 400 from Google."""
    config = written(tmp_path, gmail_secret="   ", outlook_secret=None)

    code = authorise(config, "personal-mail", tmp_path)
    capsys.readouterr()

    assert code != 0
    assert signed_in.browser_opened == []  # type: ignore[attr-defined]


# --- FR-006a: a secret that will never be used ------------------------------------------------


def test_a_secret_on_a_kind_that_never_sends_one_is_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-006a, SC-010 — both halves are the assertion.

    A warning, because the source is not broken: it signs in exactly as it should. What is
    broken is the user's picture of what they just did.
    """
    config = written(tmp_path, gmail_secret=None, outlook_secret="GOCSPX-never-used-here")

    code = main(
        ["sources", "validate", "--config", str(config), "--store", str(tmp_path / "s.db")]
    )
    out = capsys.readouterr().out

    assert code == 0, out
    assert "0 errors" in out, out
    assert "outlook-credential" in out, "the warning must name the entry"
    assert "client_secret" in out or "secret" in out.lower()
    assert "GOCSPX-never-used-here" not in out, "the warning must not print the value"


def test_the_source_with_an_unused_secret_still_validates_as_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second half of SC-010: a warning must not cost readiness."""
    config = written(tmp_path, gmail_secret=None, outlook_secret="GOCSPX-never-used-here")

    main(["sources", "list", "--config", str(config), "--store", str(tmp_path / "s.db")])
    out = capsys.readouterr().out

    assert "work-mail" in out
    assert "not ready" not in out.lower()


def test_a_secret_where_it_belongs_is_not_warned_about(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The negative. A warning that fires on the correct configuration is noise."""
    config = written(tmp_path, gmail_secret=GMAIL_SECRET, outlook_secret=None)

    main(["sources", "validate", "--config", str(config), "--store", str(tmp_path / "s.db")])
    out = capsys.readouterr().out

    assert "gmail-credential" not in out or "never sends" not in out


# --- FR-016: narration arrives before the wait ------------------------------------------------


def test_the_narration_is_printed_before_the_wait_and_survives_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-016, SC-006 — asserted by **ordering**, not by presence.

    Presence alone passes against the old behaviour, which gathered every line into the
    result and printed it at the end — arriving after the wait it described, and vanishing
    entirely when the exchange raised. Both halves are checked here: the narration is on
    stderr before the blocking call is entered, and it is still there after a failure.
    """
    config = written(tmp_path, gmail_secret=GMAIL_SECRET, outlook_secret=None)

    challenge = pkce.Challenge(
        verifier="a-verifier", challenge="a-challenge", method="S256", state=FIXED_STATE
    )
    monkeypatch.setattr(pkce, "new_challenge", lambda: challenge)

    seen_when_waiting: dict[str, str] = {}

    class WatchingLoopback:
        port = 51000

        @property
        def redirect_uri(self) -> str:
            return f"http://127.0.0.1:{self.port}/"

        def wait(self, timeout: int = 300) -> dict[str, str]:
            # What the user could already see at the moment the command began to block.
            seen_when_waiting["err"] = capsys.readouterr().err
            return {"code": CODE, "state": FIXED_STATE}

    monkeypatch.setattr(pkce, "listen", lambda: WatchingLoopback())
    monkeypatch.setattr(webbrowser, "open", lambda url: None)

    class Failing:
        def post(self, url: str, **_: object) -> object:
            from iknowwhatyoudid.net.http import HttpStatusError

            raise HttpStatusError(400, "oauth2.googleapis.com", '{"error": "invalid_grant"}')

        def get(self, url: str, **_: object) -> object:  # pragma: no cover
            raise AssertionError

    monkeypatch.setattr(mail_commands, "Client", lambda **_: Failing())

    code = authorise(config, "personal-mail", tmp_path)
    after = capsys.readouterr()

    before = seen_when_waiting.get("err", "")
    assert "Signing in to Gmail" in before, "the narration arrived after the wait began"
    assert "127.0.0.1:51000" in before, "the user was not told where the redirect would land"

    assert code != 0
    assert (after.out + after.err).strip(), "the failure discarded everything and said nothing"
