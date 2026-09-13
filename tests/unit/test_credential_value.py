"""The one doorway through which a credential value can be obtained.

Until `0006` nothing could extract a value from the credentials file at all, and that —
rather than any careful coding — was what guaranteed a secret could not reach output. This
feature cuts an opening, so these tests are about the size and shape of the opening rather
than about Gmail.

Two of them assert an **order** rather than an end state. Registering a value before
returning it and registering it afterwards leave the process in exactly the same condition;
what differs is whether a caller can briefly hold a value the redaction filter does not yet
know about. A window is only visible to a test that looks for the sequence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iknowwhatyoudid.credentials import redaction
from iknowwhatyoudid.credentials.store import CredentialPresence, CredentialStore
from iknowwhatyoudid.errors import IkwydError
from iknowwhatyoudid.protection import permissions

SECRET = "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ee-in-output"
OTHER = "a-different-value-under-a-key-this-feature-never-reads"


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """The redaction registry is process-global; these tests assert on its contents."""
    redaction.clear()


def written(tmp_path: Path, body: str) -> CredentialStore:
    path = tmp_path / "credentials.toml"
    path.write_text(body, encoding="utf-8")
    permissions.restrict_to_owner(path)
    return CredentialStore(path)


def furnished(tmp_path: Path) -> CredentialStore:
    return written(
        tmp_path,
        "[credential.gmail]\n"
        f'client_secret = "{SECRET}"\n'
        f'some_other_key = "{OTHER}"\n'
        "\n"
        "[credential.outlook]\n",
    )


# --- FR-001: a value comes back ------------------------------------------------------------


def test_a_value_is_returned_by_name_and_key(tmp_path: Path) -> None:
    store = furnished(tmp_path)
    assert store.value("gmail", "client_secret") == SECRET


def test_a_second_key_under_the_same_name_is_returned_too(tmp_path: Path) -> None:
    """The accessor is general by decision (clarification Q1), so this must work."""
    store = furnished(tmp_path)
    assert store.value("gmail", "some_other_key") == OTHER


# --- FR-005: one shape of absence -----------------------------------------------------------


def test_every_shape_of_absence_is_the_same_outcome(tmp_path: Path) -> None:
    """FR-005 — asserted as equality of results, not as four separate assertions.

    Four almost-identical assertions would pass even if the four cases returned four
    different falsy things, and a caller distinguishing them would then be writing code
    against an accident.
    """
    store = written(
        tmp_path,
        "[credential.gmail]\n"
        'empty = ""\n'
        'blank = "   "\n'
        "\n"
        "[credential.outlook]\n",
    )

    outcomes = [
        store.value("no-such-credential", "client_secret"),
        store.value("outlook", "client_secret"),
        store.value("gmail", "empty"),
        store.value("gmail", "blank"),
    ]

    assert outcomes == [None, None, None, None]
    assert len(set(map(type, outcomes))) == 1


def test_an_absent_file_is_absence_not_an_error(tmp_path: Path) -> None:
    """Before `ikwyd init` there is no file. That is a normal state, not a fault."""
    store = CredentialStore(tmp_path / "does-not-exist.toml")
    assert store.value("gmail", "client_secret") is None


# --- FR-004: registered before it is returned ------------------------------------------------


def test_the_value_is_registered_before_it_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-004 — the window is the whole point, and the end state cannot show it.

    Register-then-return and return-then-register finish identically. What differs is
    whether there is an instant in which a caller holds a value the redaction filter has
    never heard of, and could print it. So the *order* is what gets asserted.
    """
    store = furnished(tmp_path)
    order: list[str] = []

    real_register = redaction.register

    def spy(value: str) -> None:
        order.append("register")
        real_register(value)

    monkeypatch.setattr(redaction, "register", spy)

    value = store.value("gmail", "client_secret")
    order.append("returned")

    assert value == SECRET
    assert order.index("register") < order.index("returned"), (
        "the value was returned before it could be masked"
    )


def test_a_value_under_any_key_is_registered(tmp_path: Path) -> None:
    """FR-004a — containment belongs to the accessor, not to the one caller it has today.

    A general accessor cannot rely on its narrowness to keep values contained, so it has to
    do the containing itself — for every key, including ones nothing reads yet.
    """
    store = furnished(tmp_path)
    store.value("gmail", "some_other_key")

    assert redaction.redact(f"leaked: {OTHER}") == f"leaked: {redaction.MASK}"


def test_a_value_too_short_to_mask_is_documented_not_registered(tmp_path: Path) -> None:
    """Research R5 — a documented limit of the filter, stated rather than papered over.

    Lowering the threshold would mask common short strings across all output, which is a
    real cost against an imaginary benefit: no OAuth secret is five characters long. The
    contract says registration is *attempted*, not that it is guaranteed.
    """
    store = written(tmp_path, '[credential.gmail]\nclient_secret = "abc"\n')

    assert store.value("gmail", "client_secret") == "abc"
    assert redaction.known_count() == 0


# --- FR-003: permissions -----------------------------------------------------------------


def exposed(tmp_path: Path) -> CredentialStore:
    """A credentials file the operating system says others can read."""
    path = tmp_path / "credentials.toml"
    path.write_text(f'[credential.gmail]\nclient_secret = "{SECRET}"\n', encoding="utf-8")
    return CredentialStore(path)


def test_reading_a_value_refuses_when_others_can_read_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-003 — handing a secret out of a file just shown to be world-readable."""
    store = exposed(tmp_path)
    monkeypatch.setattr(
        permissions,
        "check",
        lambda path: permissions.PermissionReport(
            permissions.PermissionStatus.OTHERS_CAN_READ, "everyone can read it"
        ),
    )

    with pytest.raises(IkwydError) as caught:
        store.value("gmail", "client_secret")

    message = f"{caught.value.message} {caught.value.remedy or ''}"
    assert str(store.path) in message, "the refusal must name the file"
    assert "restrict" in message.lower(), "the refusal must say what to do"


def test_the_presence_check_still_only_warns_when_others_can_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-003a — a regression test for a **deliberate** inconsistency.

    `tokens.toml` refuses on every read because it holds nothing but secrets. This file
    also answers "is this name known?", whose answer discloses nothing — so refusing that
    would break `sources list` and `sources validate` for anyone whose file is loose, while
    protecting nothing at all.

    Without this test, someone tidying the two paths into agreement would break every
    loose-file user and look entirely right doing it.
    """
    store = exposed(tmp_path)
    monkeypatch.setattr(
        permissions,
        "check",
        lambda path: permissions.PermissionReport(
            permissions.PermissionStatus.OTHERS_CAN_READ, "everyone can read it"
        ),
    )

    status = store.status("gmail")

    assert status.presence is CredentialPresence.PRESENT
    assert "gmail" in store.known_names()


def test_an_unverifiable_permission_does_not_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`UNVERIFIED` is the normal answer on some systems; it is not evidence of exposure.

    Treating "could not check" as "others can read" would make the tool unusable wherever
    the check is unavailable, which is a refusal based on ignorance rather than on a fact.
    """
    store = furnished(tmp_path)
    monkeypatch.setattr(
        permissions,
        "check",
        lambda path: permissions.PermissionReport(
            permissions.PermissionStatus.UNVERIFIED, "cannot tell"
        ),
    )

    assert store.value("gmail", "client_secret") == SECRET


# --- FR-001a: nothing else returns a value -------------------------------------------------


def test_no_other_member_returns_a_credential_value(tmp_path: Path) -> None:
    """FR-001a — the accessor is the only doorway, checked over the public surface.

    Every public member is called with plausible arguments and its result searched for the
    known secret. A method that leaked one — a `__repr__`, a diagnostic helper, a future
    `as_dict` — fails here rather than in somebody's terminal.
    """
    store = furnished(tmp_path)
    store.value("gmail", "client_secret")  # ensure it is loaded

    leaks: list[str] = []
    for name in dir(store):
        if name.startswith("_") or name == "value":
            continue
        member = getattr(store, name)
        try:
            result = member("gmail") if callable(member) else member
        except TypeError:
            try:
                result = member()
            except TypeError:
                continue
        except IkwydError:
            continue
        if SECRET in repr(result):
            leaks.append(name)

    assert leaks == [], f"these members expose a credential value: {leaks}"


def test_the_repr_of_the_store_hides_everything(tmp_path: Path) -> None:
    store = furnished(tmp_path)
    store.value("gmail", "client_secret")
    assert SECRET not in repr(store)
