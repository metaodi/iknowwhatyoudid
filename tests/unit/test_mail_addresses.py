"""Address normalisation (FR-031, research R12).

The rule is deliberately small: case, whitespace, display name, angle brackets. Anything
beyond that merges addresses the user never said were the same, and the spec's own
assumption is that recognising one human behind several addresses is out of scope.
"""

from __future__ import annotations

import pytest

from iknowwhatyoudid import addresses


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Anna@ACME.example", "anna@acme.example"),
        ("  anna@acme.example  ", "anna@acme.example"),
        ('"Anna B" <Anna@Acme.Example>', "anna@acme.example"),
        ("<anna@acme.example>", "anna@acme.example"),
        ("Anna B <anna@acme.example>", "anna@acme.example"),
    ],
)
def test_normalisation(given: str, expected: str) -> None:
    assert addresses.normalise(given) == expected


@pytest.mark.parametrize(
    "given",
    ["a.n.n.a@gmail.com", "anna+client@gmail.com", "anna+client@acme.example"],
)
def test_provider_specific_canonicalisation_is_not_attempted(given: str) -> None:
    """Gmail treats dots and `+tags` as noise. This tool does not, deliberately.

    Stripping them would merge addresses the user never declared equivalent, and a
    `+client` tag is often exactly the signal a correspondent rule wants to key on.
    """
    assert addresses.normalise(given) == given.lower()


def test_the_domain_is_available_separately() -> None:
    """The ad-hoc project fallback counts domains per message; it should not re-split."""
    assert addresses.domain_of("anna@acme.example") == "acme.example"
    assert addresses.domain_of("Anna@ACME.Example") == "acme.example"


def test_something_that_is_not_an_address_is_rejected() -> None:
    """A malformed entry in the mapping can never match, so it is a typo, not a wish."""
    for junk in ["", "   ", "no-at-sign", "@nolocal.example", "trailing@", "a@b@c"]:
        assert not addresses.is_valid(junk), junk


def test_a_plausible_address_is_accepted() -> None:
    for good in ["anna@acme.example", "a@b.co", "first.last+tag@sub.domain.example"]:
        assert addresses.is_valid(good), good


def test_a_header_yields_every_address_in_order() -> None:
    """A broadcast is evidence of something different from a two-person exchange."""
    found = addresses.parse_list('"Anna B" <anna@acme.example>, bob@northwind.example')
    assert found == ["anna@acme.example", "bob@northwind.example"]


def test_a_display_name_is_kept_separately_but_never_matched_on() -> None:
    """A display name is attacker-controlled and changes freely; it is shown, not used."""
    assert addresses.display_name_of('"Anna B" <anna@acme.example>') == "Anna B"
    assert addresses.display_name_of("anna@acme.example") is None
