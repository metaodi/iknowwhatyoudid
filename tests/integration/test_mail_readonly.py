"""The guarantee the feature rests on (FR-013, FR-014, SC-002, SC-003).

Written before the Graph connector, and the ordering is the point: read-only is cheapest
to keep true from the first commit.

Three levels of assurance, weakest to strongest:

1. **behavioural** — nothing mutating is sent;
2. **structural** — no mutating method exists to send;
3. **by construction** — the scope requested does not grant mutation at all.

Only the third is really load-bearing. The other two catch a mistake; the third makes the
mistake impossible, because Microsoft will not honour a write from a `Mail.ReadBasic`
token however the client is written.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "iknowwhatyoudid"


def source_of(module: str) -> str:
    return (SRC / module).read_text(encoding="utf-8")


# --- by construction: the scope cannot write ------------------------------------------


def test_the_graph_scope_is_read_only_and_excludes_bodies() -> None:
    """`Mail.ReadBasic` returns messages **without body or attachments**.

    This is what turns FR-023 and FR-024 from rules the code must remember into facts
    about what the server will hand over. `Mail.Read` would work and is broader;
    `Mail.ReadWrite` is never requested under any circumstance (research R5).
    """
    from iknowwhatyoudid.mail import graph

    assert graph.SCOPES == ("Mail.ReadBasic", "offline_access")
    joined = " ".join(graph.SCOPES)
    assert "ReadWrite" not in joined
    assert "Send" not in joined
    assert "Mail.Read " not in joined + " ", "the broader Mail.Read is not requested"


def code_literals(path: Path) -> set[str]:
    """Every string literal a module could actually *send*, excluding docstrings.

    A docstring is an `ast.Constant` too, so "we never request `Mail.ReadWrite`" would
    otherwise read as a request for it. `0003` hit this exact trap twice with grep; the
    fix is to look at what the code says rather than at what the file contains.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def test_no_mutating_scope_appears_anywhere_in_the_codebase() -> None:
    """A scope string is easy to widen in a hurry and hard to notice in review."""
    forbidden = ("Mail.ReadWrite", "Mail.Send", "mail.google.com", "gmail.modify")
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for literal in code_literals(path):
            for scope in forbidden:
                if scope in literal:
                    offenders.append(f"{path.name}: {literal!r}")
    assert not offenders, offenders


def test_the_literal_check_would_catch_a_real_widening(tmp_path: Path) -> None:
    """The test above is only worth having if it fails on the thing it guards.

    A docstring mentioning a scope must pass; an actual scope constant must not.
    """
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        '"""We never request Mail.ReadWrite."""\nX = "Mail.ReadBasic"\n',
        encoding="utf-8",
    )
    guilty = tmp_path / "guilty.py"
    guilty.write_text(
        '"""Reads mail."""\nSCOPES = ("Mail.ReadWrite",)\n',
        encoding="utf-8",
    )

    assert not any("ReadWrite" in s for s in code_literals(innocent))
    assert any("ReadWrite" in s for s in code_literals(guilty))


# --- structural: no mutating request can be made ---------------------------------------


def test_the_http_client_offers_no_mutating_method() -> None:
    """There is no `delete`, `put` or `patch` to reach for.

    Principle II at the level of what is callable rather than what is called.
    """
    from iknowwhatyoudid.net import http

    assert {n for n in dir(http.Client) if not n.startswith("_")} == {"get", "post"}


def test_graph_issues_only_get_requests() -> None:
    """`post` exists for token exchange; the mail reader must never use it.

    Checked through the AST rather than by searching text, because `0003` learned that a
    docstring mentioning a command matches a grep for it.
    """
    tree = ast.parse(source_of("mail/graph.py"))
    methods = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "post" not in methods, "the Graph reader must only ever GET"
    assert "get" in methods


def test_every_graph_url_is_under_the_read_only_message_endpoints() -> None:
    """No `/send`, no `/move`, no `/copy`, no `/markAsRead`."""
    tree = ast.parse(source_of("mail/graph.py"))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    paths = [value for value in literals if value.startswith("/")]
    assert paths, "the endpoints are literals, so they can be reviewed here"
    for path in paths:
        for mutating in ("send", "move", "copy", "reply", "forward", "markasread"):
            assert mutating not in path.lower(), f"{path} looks like it mutates"


# --- the fields asked for ----------------------------------------------------------------


def test_the_select_names_only_the_agreed_fields() -> None:
    """FR-023, FR-024 — a `$select` is how a future author would widen this by accident.

    Naming the seven fields explicitly means adding `body` to the response requires
    editing a list a reviewer reads, rather than deleting a filter they might not notice.
    """
    from iknowwhatyoudid.mail import graph

    assert set(graph.SELECT) == {
        "internetMessageId",
        "sentDateTime",
        "from",
        "toRecipients",
        "ccRecipients",
        "subject",
        "hasAttachments",
    }
    for forbidden in ("body", "bodyPreview", "uniqueBody", "attachments", "bccRecipients"):
        assert forbidden not in graph.SELECT, forbidden


def test_the_sent_items_folder_is_what_is_read() -> None:
    """FR-048 — received mail is never fetched, rather than fetched and discarded.

    Less data crosses the network, and the requirement holds even if the filtering code
    is wrong.
    """
    from iknowwhatyoudid.mail import graph

    assert "sentitems" in graph.SENT_FOLDER_URL.lower()
    assert "delta" in graph.SENT_FOLDER_URL


# --- behavioural: a whole read, with the transport watched -------------------------------


def test_a_full_read_sends_nothing_but_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    """The end-to-end version of the above, against recorded responses."""
    from fixtures.responses import graph as recorded
    from iknowwhatyoudid.mail import graph

    seen: list[tuple[str, str]] = []

    class Spy:
        def get(self, url: str, *, headers: dict[str, str] | None = None) -> object:
            seen.append(("GET", url))
            return recorded.next_page()

        def post(self, url: str, **_: object) -> object:  # pragma: no cover
            seen.append(("POST", url))
            raise AssertionError("the mail reader must never POST")

    recorded.reset()
    list(graph.read(Spy(), token="t", since=None, resumption_point=None))

    assert seen, "it did read"
    assert {method for method, _ in seen} == {"GET"}
    assert all("graph.microsoft.com" in url for _, url in seen)
