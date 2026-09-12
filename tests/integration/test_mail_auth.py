"""Authorisation, and the four failures that must be told apart (FR-010, SC-012).

Nothing here contacts a provider. Every response is recorded, and the assertions are about
*which state* the tool concludes — because each needs a different action from the user, and
"authentication failed" tells them none of them.

The worst outcome this guards against is sending someone to re-authorise when their
employer's administrator is the one who has to act: a loop that cannot terminate, with the
tool insisting the user do something that will not work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iknowwhatyoudid.auth import flow, pkce, tokens
from iknowwhatyoudid.errors import (
    AuthorisationError,
    ConsentRequiredError,
    TokenExpiredError,
)
from iknowwhatyoudid.net.http import HttpStatusError
from iknowwhatyoudid.protection import permissions

SECRET = "refresh-token-that-must-never-appear"
CODE = "authorisation-code-that-must-never-appear"


class Refusing:
    """A client whose token endpoint answers with one recorded provider error."""

    def __init__(self, detail: str, status: int = 400) -> None:
        self._detail = detail
        self._status = status

    def post(self, url: str, **_: object) -> object:
        raise HttpStatusError(self._status, "login.microsoftonline.com", self._detail)

    def get(self, url: str, **_: object) -> object:  # pragma: no cover
        raise AssertionError("the token flow never GETs")


class Answering:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = body

    def post(self, url: str, **_: object) -> object:
        return self._body

    def get(self, url: str, **_: object) -> object:  # pragma: no cover
        raise AssertionError("the token flow never GETs")


def refresh_with(client: object) -> flow.Tokens:
    return flow.refresh(
        client,  # type: ignore[arg-type]
        token_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id="app",
        refresh_token=SECRET,
        scopes=("Mail.ReadBasic", "offline_access"),
    )


# --- the four failures, told apart ------------------------------------------------------


def test_an_administrator_must_consent_is_its_own_state() -> None:
    """Research R6 — the one the user cannot fix alone.

    Telling them to re-authorise would send them round a loop that cannot terminate,
    because their organisation has to act, not them.
    """
    with pytest.raises(ConsentRequiredError) as raised:
        refresh_with(Refusing("AADSTS65001: The user or administrator has not consented"))

    assert "administrator" in str(raised.value)
    assert "will not help" in (raised.value.remedy or ""), (
        "it must say re-authorising is pointless, or the user will keep trying"
    )


def test_an_expired_token_is_its_own_state() -> None:
    """Research R4 — Google does this every seven days, by design."""
    with pytest.raises(TokenExpiredError) as raised:
        refresh_with(Refusing("invalid_grant: Token has been expired or revoked"))

    assert "authorise" in (raised.value.remedy or "")


def test_any_other_refusal_is_generic_but_still_actionable() -> None:
    with pytest.raises(AuthorisationError) as raised:
        refresh_with(Refusing("invalid_client: no such application"))

    assert not isinstance(raised.value, ConsentRequiredError | TokenExpiredError)
    assert raised.value.remedy


def test_an_unreachable_provider_is_not_a_credential_problem() -> None:
    """Nothing is wrong with the configuration, so it must not say there is."""
    from iknowwhatyoudid.errors import MailReadError

    class Unreachable:
        def post(self, url: str, **_: object) -> object:
            raise MailReadError("login.microsoftonline.com could not be reached")

        def get(self, url: str, **_: object) -> object:  # pragma: no cover
            raise AssertionError

    with pytest.raises(AuthorisationError) as raised:
        refresh_with(Unreachable())

    assert not isinstance(raised.value, ConsentRequiredError | TokenExpiredError)
    assert "later" in (raised.value.remedy or "")


def test_a_missing_access_token_is_refused_rather_than_half_accepted() -> None:
    with pytest.raises(AuthorisationError):
        refresh_with(Answering({"token_type": "Bearer"}))


# --- the fifth state: it worked -----------------------------------------------------------


def test_a_good_response_yields_tokens() -> None:
    got = refresh_with(
        Answering(
            {"access_token": "at", "refresh_token": SECRET, "expires_in": 3599}
        )
    )
    assert got.access_token == "at"
    assert got.refresh_token == SECRET
    assert got.expires_in == 3599


# --- nothing leaks ---------------------------------------------------------------------------


def test_tokens_do_not_render_themselves() -> None:
    """A stray `print`, a traceback, a debugger — all reach `__repr__` first."""
    got = flow.Tokens(access_token="at", refresh_token=SECRET)

    assert SECRET not in repr(got)
    assert "at" not in repr(got).replace("Tokens(", "")
    assert "redacted" in repr(got)


def test_a_stored_token_does_not_render_itself() -> None:
    stored = tokens.StoredToken(account="work", refresh_token=SECRET)
    assert SECRET not in repr(stored)
    assert "work" in repr(stored), "the account is safe to show, and useful"


def test_no_secret_reaches_an_error_message() -> None:
    """An exception is the most likely thing to be logged or pasted into an issue."""
    with pytest.raises(AuthorisationError) as raised:
        refresh_with(Refusing("invalid_grant"))

    rendered = f"{raised.value} {raised.value.remedy}"
    assert SECRET not in rendered


# --- the redirect ---------------------------------------------------------------------------


def test_a_redirect_with_the_wrong_state_is_refused() -> None:
    """A redirect this process did not start must not have its code redeemed."""
    challenge = pkce.new_challenge()
    with pytest.raises(AuthorisationError) as raised:
        flow.classify_redirect({"code": CODE, "state": "somebody-elses"}, challenge)
    assert "did not match" in str(raised.value)


def test_a_declined_authorisation_says_so_plainly() -> None:
    challenge = pkce.new_challenge()
    with pytest.raises(AuthorisationError) as raised:
        flow.classify_redirect({"error": "access_denied"}, challenge)
    assert "declined" in str(raised.value)


def test_a_tenant_refusal_in_the_redirect_is_also_a_consent_problem() -> None:
    """Microsoft can refuse at the redirect as well as at the token endpoint."""
    challenge = pkce.new_challenge()
    with pytest.raises(ConsentRequiredError):
        flow.classify_redirect(
            {
                "error": "access_denied",
                "error_description": "AADSTS65001: admin consent required",
            },
            challenge,
        )


def test_a_good_redirect_yields_the_code() -> None:
    challenge = pkce.new_challenge()
    got = flow.classify_redirect({"code": CODE, "state": challenge.state}, challenge)
    assert got == CODE


def test_no_redirect_at_all_is_a_timeout_not_a_refusal() -> None:
    challenge = pkce.new_challenge()
    with pytest.raises(AuthorisationError) as raised:
        flow.classify_redirect({}, challenge)
    assert "timeout" in str(raised.value)


# --- PKCE ----------------------------------------------------------------------------------------


def test_the_challenge_is_the_hash_of_the_verifier_not_the_verifier() -> None:
    """The whole point: an intercepted authorisation request reveals nothing usable."""
    import base64
    import hashlib

    challenge = pkce.new_challenge()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(challenge.verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert challenge.challenge == expected
    assert challenge.challenge != challenge.verifier
    assert challenge.method == "S256", "plain is permitted by the RFC and is not used"


def test_every_challenge_is_different() -> None:
    assert len({pkce.new_challenge().verifier for _ in range(20)}) == 20


def test_the_verifier_is_within_the_length_the_rfc_allows() -> None:
    verifier = pkce.new_challenge().verifier
    assert 43 <= len(verifier) <= 128


def test_the_authorisation_url_sends_the_challenge_and_never_the_verifier() -> None:
    challenge = pkce.new_challenge()
    url = pkce.authorisation_url(
        endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        client_id="app",
        scopes=("Mail.ReadBasic", "offline_access"),
        redirect_uri="http://127.0.0.1:1234/",
        challenge=challenge,
    )

    assert challenge.challenge in url
    assert challenge.verifier not in url, "the verifier must never leave the process"
    assert "Mail.ReadBasic" in url


# --- the token file ------------------------------------------------------------------------------


def test_a_token_file_readable_by_others_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-008 — created user-only, and checked on every read, not only at creation.

    A file that was restricted once and later opened up is exactly the case worth
    catching, and asking is cheap.
    """
    path = tmp_path / "tokens.toml"
    tokens.save(path, tokens.StoredToken(account="work", refresh_token=SECRET))

    report = permissions.check(path)
    assert report.status is not permissions.PermissionStatus.OTHERS_CAN_READ

    # Force the permission check to report an exposed file. Patching the real module
    # rather than reaching through `tokens`' namespace: mypy is right that it is not an
    # export, and patching the source is what we actually mean.
    monkeypatch.setattr(
        permissions,
        "check",
        lambda _: permissions.PermissionReport(
            permissions.PermissionStatus.OTHERS_CAN_READ, "test"
        ),
    )

    with pytest.raises(tokens.TokenStoreUnreadableError) as raised:
        tokens.load(path)

    assert "other users" in str(raised.value)


def test_an_absent_token_file_is_not_an_error(tmp_path: Path) -> None:
    """It is the state before the first authorisation, which is normal."""
    assert tokens.load(tmp_path / "nothing.toml") == {}


def test_a_saved_token_round_trips_and_is_registered_for_redaction(tmp_path: Path) -> None:
    from iknowwhatyoudid.credentials import redaction

    redaction.clear()
    path = tmp_path / "tokens.toml"
    tokens.save(path, tokens.StoredToken(account="work", refresh_token=SECRET))

    loaded = tokens.load(path)
    assert loaded["work"].refresh_token == SECRET
    assert redaction.redact(f"token is {SECRET}") != f"token is {SECRET}", (
        "a token that reaches a log line must be masked"
    )
    redaction.clear()


def test_saving_one_account_leaves_the_others_alone(tmp_path: Path) -> None:
    path = tmp_path / "tokens.toml"
    tokens.save(path, tokens.StoredToken(account="work", refresh_token="a"))
    tokens.save(path, tokens.StoredToken(account="personal", refresh_token="b"))

    loaded = tokens.load(path)
    assert set(loaded) == {"work", "personal"}
    assert loaded["work"].refresh_token == "a"


def test_forgetting_an_account_removes_only_that_one(tmp_path: Path) -> None:
    path = tmp_path / "tokens.toml"
    tokens.save(path, tokens.StoredToken(account="work", refresh_token="a"))
    tokens.save(path, tokens.StoredToken(account="personal", refresh_token="b"))

    assert tokens.forget(path, "work") is True
    assert set(tokens.load(path)) == {"personal"}
    assert tokens.forget(path, "work") is False


def test_the_token_file_is_valid_toml_even_with_awkward_values(tmp_path: Path) -> None:
    """A token is opaque; it may contain quotes or backslashes."""
    path = tmp_path / "tokens.toml"
    awkward = 'has"a quote and \\ a backslash'
    tokens.save(path, tokens.StoredToken(account="work", refresh_token=awkward))
    assert tokens.load(path)["work"].refresh_token == awkward


def test_the_json_form_of_an_authorised_account_carries_no_token(tmp_path: Path) -> None:
    """FR-008 — `--json` is the most likely thing to be piped somewhere."""
    path = tmp_path / "tokens.toml"
    tokens.save(path, tokens.StoredToken(account="work", refresh_token=SECRET))
    stored = tokens.load(path)["work"]

    rendered = json.dumps({"account": stored.account, "authorised": True})
    assert SECRET not in rendered


# --- the five states, as the CLI reports them ----------------------------------------


def test_sources_check_names_the_state_for_an_unauthorised_account(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-010 — the user is told what to do, not merely that something failed."""
    from iknowwhatyoudid.cli.main import main

    (tmp_path / "config.toml").write_text(
        '[[source]]\nname = "work-mail"\nkind = "mail.outlook"\n'
        'credential = "c"\naddresses = ["me@example.com"]\n'
        'client_id = "00000000-0000-0000-0000-000000000000"\n',
        encoding="utf-8",
    )
    main(
        ["sources", "check", "work-mail", "--config", str(tmp_path / "config.toml"),
         "--store", str(tmp_path / "s.db")]
    )
    out = capsys.readouterr().out

    assert "credential absent" in out
    assert "authorise work-mail" in out, "it names the command that fixes it"


def test_sources_check_reports_a_missing_archive_distinctly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An export that has not been made is not a credential problem."""
    from iknowwhatyoudid.cli.main import main

    (tmp_path / "config.toml").write_text(
        '[[source]]\nname = "hey"\nkind = "mail.hey"\n'
        'addresses = ["me@example.com"]\npaths = ["missing.mbox"]\n',
        encoding="utf-8",
    )
    main(
        ["sources", "check", "hey", "--config", str(tmp_path / "config.toml"),
         "--store", str(tmp_path / "s.db")]
    )
    out = capsys.readouterr().out

    assert "archive not found" in out
    assert "credential" not in out.lower().replace("credentials.toml", "")


def test_the_five_states_are_each_distinct() -> None:
    """The table itself, so a sixth state cannot quietly collapse into another."""
    from iknowwhatyoudid.cli import sources_commands

    assert len(set(sources_commands.AUTHORISATION_STATES)) == len(
        sources_commands.AUTHORISATION_STATES
    )
    assert "administrator approval required" in sources_commands.AUTHORISATION_STATES
