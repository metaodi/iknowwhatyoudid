"""The six paths a credential value must never reach, and the chokepoint that stops it.

`0006` cut the first opening through which a credential value can be obtained. Until then
the guarantee rested on there being no way to get one at all; it now rests on `value()`
registering everything it returns with the redaction filter, and on every user-facing
stream passing through `cli/render.py`.

The second half of that is what this file checks. `render.py`'s own docstring says a
chokepoint holds "for every command written from now on, including ones nobody has thought
of yet" — which is only true while nothing bypasses it. Two modules did when this feature
began, and the AST test at the bottom is what stops a third.
"""

from __future__ import annotations

import ast
import json
import webbrowser
from pathlib import Path

import pytest

from iknowwhatyoudid.cli import mail_commands
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.credentials import redaction
from iknowwhatyoudid.protection import permissions

SRC = Path(__file__).resolve().parents[2] / "src" / "iknowwhatyoudid"

#: Long enough to be registered, distinctive enough that a substring match means something.
SECRET = "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ever-be-printed-anywhere"


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    redaction.clear()


def configured(tmp_path: Path) -> Path:
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
        'addresses = ["someone@example.com"]\n',
        encoding="utf-8",
    )
    (space / "credentials.toml").write_text(
        f'[credential.gmail-credential]\nclient_secret = "{SECRET}"\n', encoding="utf-8"
    )
    permissions.restrict_to_owner(space / "credentials.toml")
    return space / "config.toml"


#: Commands that read the configuration, and therefore could reach a credential.
CONFIGURED_COMMANDS = (
    ["sources", "list"],
    ["sources", "validate"],
    ["sources", "destinations"],
    ["sources", "kinds"],
    ["sources", "check", "personal-mail"],
    ["ingest"],
)

#: Commands that do not take `--config`. Included because "this command cannot reach a
#: credential" is an assumption worth testing rather than asserting — a registered value is
#: registered process-wide, so anything printing afterwards could still carry it.
STORE_COMMANDS = (
    ["store", "info"],
    ["mail", "correspondents"],
    ["records", "query", "--from", "2026-01-01", "--to", "2026-12-31"],
)


def run_everything(config: Path, store: str, capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Every command, in both output forms, returning what each one printed."""
    seen: list[str] = []
    for argv in CONFIGURED_COMMANDS:
        for extra in ([], ["--json"]):
            main([*argv, *extra, "--config", str(config), "--store", store])
            captured = capsys.readouterr()
            seen.append(captured.out + captured.err)
    for argv in STORE_COMMANDS:
        for extra in ([], ["--json"]):
            main([*argv, *extra, "--store", store])
            captured = capsys.readouterr()
            seen.append(captured.out + captured.err)
    return seen


# --- FR-009: the six paths -------------------------------------------------------------------


def test_no_command_prints_a_credential_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-009, SC-003 — stdout, stderr and `--json`, over the whole surface."""
    config = configured(tmp_path)
    store = str(tmp_path / "store.db")

    seen = run_everything(config, store, capsys)

    offenders = [text for text in seen if SECRET in text]
    assert offenders == [], f"{len(offenders)} command(s) printed the credential value"


def test_the_log_never_carries_a_credential_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-009, FR-010 — the log persists and gets shared; it is the worst of the six."""
    config = configured(tmp_path)
    store = tmp_path / "store.db"

    run_everything(config, str(store), capsys)

    log = store.parent / "iknowwhatyoudid.log"
    if log.exists():
        assert SECRET not in log.read_text(encoding="utf-8", errors="replace")


def test_a_failing_command_does_not_print_it_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-009 — the success path is the easy half.

    An error message built from a provider's own response is exactly where a value would
    surface, so the interesting case is a command that fails **after** the secret has been
    loaded and sent.
    """
    from iknowwhatyoudid.auth import pkce
    from iknowwhatyoudid.net.http import HttpStatusError

    config = configured(tmp_path)

    challenge = pkce.Challenge(
        verifier="v", challenge="c", method="S256", state="fixed-state"
    )
    monkeypatch.setattr(pkce, "new_challenge", lambda: challenge)

    class Loopback:
        port = 51000

        @property
        def redirect_uri(self) -> str:
            return f"http://127.0.0.1:{self.port}/"

        def wait(self, timeout: int = 300) -> dict[str, str]:
            return {"code": "a-code", "state": "fixed-state"}

    monkeypatch.setattr(pkce, "listen", lambda: Loopback())
    monkeypatch.setattr(webbrowser, "open", lambda url: None)

    class EchoingBack:
        """A provider that quotes the request back — some really do, in validation errors."""

        def post(self, url: str, *, form: dict[str, str] | None = None, **_: object) -> object:
            body = json.dumps(
                {"error": "invalid_request", "error_description": f"bad value {SECRET}"}
            )
            raise HttpStatusError(400, "oauth2.googleapis.com", body)

        def get(self, url: str, **_: object) -> object:  # pragma: no cover
            raise AssertionError

    monkeypatch.setattr(mail_commands, "Client", lambda **_: EchoingBack())

    code = main(
        [
            "sources",
            "authorise",
            "personal-mail",
            "--config",
            str(config),
            "--store",
            str(tmp_path / "s.db"),
        ]
    )
    captured = capsys.readouterr()
    text = captured.out + captured.err

    assert code != 0
    assert SECRET not in text, "a provider's echo of the secret reached the user"
    assert redaction.MASK in text, "the value was neither masked nor absent — check the path"


def test_a_value_under_any_key_is_masked_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-004a — containment belongs to the accessor, not to its one caller.

    Asserted with a key this feature never reads, because a general accessor that only
    protected the key it happens to be used for would be protecting the caller rather than
    the file.
    """
    from iknowwhatyoudid.credentials.store import CredentialStore

    path = tmp_path / "credentials.toml"
    path.write_text(
        f'[credential.a]\nsomething_else = "{SECRET}"\n', encoding="utf-8"
    )
    permissions.restrict_to_owner(path)

    store = CredentialStore(path)
    assert store.value("a", "something_else") == SECRET

    from iknowwhatyoudid.cli.render import human

    assert SECRET not in human(f"the value is {SECRET}")


# --- the chokepoint has no bypasses ----------------------------------------------------------


def user_facing_prints(path: Path) -> list[int]:
    """Line numbers of `print(...)` calls in *path*, from the AST.

    Text matching is not enough and this project has been caught by it three times: a grep
    for a name has matched a docstring saying the opposite of the code.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            found.append(node.lineno)
    return found


#: The functions that *are* the chokepoint, by their real names.
CHOKEPOINT = frozenset({"human", "envelope", "redact"})


def redacting_names(tree: ast.Module) -> set[str]:
    """Every local name in this module that refers to a chokepoint function.

    Resolved from the module's own imports rather than hardcoded, because
    `from .render import human as render_human` is an established convention here, and a
    checker that did not follow aliases would report a guarded call as a bypass — the kind
    of false alarm that gets a test deleted rather than a bug fixed.
    """
    bound = set(CHOKEPOINT)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in CHOKEPOINT:
                    bound.add(alias.asname or alias.name)
    return bound


def goes_through_redaction(path: Path, lineno: int) -> bool:
    """Whether the `print` at *lineno* has a redacting call somewhere in its arguments."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed = redacting_names(tree)

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and node.lineno == lineno
        ):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                name = (
                    inner.func.id
                    if isinstance(inner.func, ast.Name)
                    else getattr(inner.func, "attr", "")
                )
                if name in allowed:
                    return True
    return False


def test_no_command_module_prints_without_passing_through_the_chokepoint() -> None:
    """Research R4 — the finding that made this a task rather than a footnote.

    `cli/render.py` applies `redact()` to both output forms, and `commands.emit` is the only
    thing that should reach a stream. Two modules acquired a direct `print(..., file=sys.stderr)`
    in the two days before this feature — neither printing a secret, but the guarantee is
    that the chokepoint has no bypasses, not that each bypass happens to be harmless today.

    `emit` itself is the chokepoint's own exit and is exempt by name.
    """
    exempt = {"commands.py", "render.py"}
    offenders: dict[str, list[int]] = {}

    for path in sorted((SRC / "cli").glob("*.py")):
        if path.name in exempt:
            continue
        unguarded = [
            lineno
            for lineno in user_facing_prints(path)
            if not goes_through_redaction(path, lineno)
        ]
        if unguarded:
            offenders[path.name] = unguarded

    assert offenders == {}, (
        f"these print without redaction: {offenders}. "
        "Route them through cli/render.py, or the chokepoint is decoration."
    )


def test_the_bypass_check_would_actually_catch_one(tmp_path: Path) -> None:
    """The previous test passes trivially if the walker finds nothing. It does not."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import sys\n"
        "from .render import human as render_human\n"
        "def a() -> None:\n"
        "    print('bare', file=sys.stderr)\n"
        "def b() -> None:\n"
        "    print(render_human('guarded'), file=sys.stderr)\n",
        encoding="utf-8",
    )

    lines = user_facing_prints(sample)
    assert len(lines) == 2, lines
    assert not goes_through_redaction(sample, lines[0]), "a bare print was not caught"
    assert goes_through_redaction(sample, lines[1]), (
        "an aliased chokepoint call was miscounted as a bypass"
    )
