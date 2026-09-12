"""Subject rules match by case-insensitive substring — no globs, no regex (research R11).

This is the one place the mapping contract refuses a feature people will ask for, and
the reason is the first test below.
"""

from __future__ import annotations

import pytest

from iknowwhatyoudid.projects.model import Mapping, MappingEntry


def mapping(*entries: MappingEntry) -> Mapping:
    return Mapping(path=__import__("pathlib").Path("projects.toml"), entries=entries)


def project(name: str, *, subjects: tuple[str, ...] = (), index: int = 0) -> MappingEntry:
    return MappingEntry(project_name=name, subjects=subjects, index=index)


# --- the trap this design exists to avoid ---------------------------------------------


def test_a_bracketed_tag_matches_literally() -> None:
    """The reason there is no glob support.

    `[ACME]` is the single most likely rule anyone writes — bracketed tags are the
    convention this feature exists to serve. Under glob matching it would be a
    **character class** meaning "any one of A, C, M, E", and would match nearly every
    subject ever sent, silently mis-attributing a year of mail.
    """
    rules = mapping(project("acme", subjects=("[ACME]",)))

    hit = rules.match_message(subject="Re: [ACME] rollout plan", addresses=[])
    assert hit is not None and hit.project_name == "acme"

    # Every one of these contains an A, a C, an M or an E. Under glob semantics they
    # would all match; under substring semantics none of them do.
    for innocent in ["A message", "Meeting notes", "Escalation", "Case update"]:
        assert rules.match_message(subject=innocent, addresses=[]) is None, innocent


def test_regex_metacharacters_are_literal_too() -> None:
    """A rule is read back six months later and must mean what it looks like."""
    rules = mapping(project("p", subjects=(".*",)))
    assert rules.match_message(subject="anything at all", addresses=[]) is None
    assert rules.match_message(subject="a .* literal", addresses=[]) is not None


# --- ordinary matching ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "subject", "matches"),
    [
        ("invoice", "Invoice 2231 attached", True),
        ("INVOICE", "invoice 2231 attached", True),
        ("invoice", "Re: Fwd: your invoice", True),
        ("invoice", "Payment received", False),
        ("acme rollout", "Re: Acme Rollout plan", True),
    ],
)
def test_substring_case_insensitive(rule: str, subject: str, matches: bool) -> None:
    rules = mapping(project("p", subjects=(rule,)))
    assert (rules.match_message(subject=subject, addresses=[]) is not None) is matches


def test_the_evidence_names_what_matched() -> None:
    """FR-035 — an attribution that cannot be explained cannot be corrected."""
    rules = mapping(project("acme", subjects=("[ACME]",)))
    hit = rules.match_message(subject="Re: [ACME] plan", addresses=[])
    assert hit is not None
    assert hit.evidence == "[ACME]"


def test_the_first_declared_rule_wins() -> None:
    """FR-036 — order is a property of the file's text, so the result is stable."""
    rules = mapping(
        project("first", subjects=("report",), index=0),
        project("second", subjects=("report",), index=1),
    )
    hit = rules.match_message(subject="Monthly report", addresses=[])
    assert hit is not None and hit.project_name == "first"


def test_an_empty_subject_matches_no_rule() -> None:
    rules = mapping(project("p", subjects=("anything",)))
    assert rules.match_message(subject="", addresses=[]) is None
