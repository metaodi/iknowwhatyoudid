"""Mail lands on the right project (US2, FR-032 to FR-047).

Every case runs end to end: a real archive, a real mapping file, a real store. The
precedence table in `contracts/mapping-file.md` is asserted row by row, because the whole
value of stating an order is that it can be checked.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fixtures.mail import messages as fx
from iknowwhatyoudid.cli.main import main
from iknowwhatyoudid.projects import attribution
from iknowwhatyoudid.store import connection as conn
from iknowwhatyoudid.store import migrate


def workspace(tmp_path: Path, box: fx.Mailbox, mapping: str = "") -> Path:
    archive = box.write_mbox(tmp_path / "export.mbox")
    (tmp_path / "config.toml").write_text(
        f'[[source]]\nname = "mail"\nkind = "mail.mbox"\n'
        f'addresses = ["{fx.ME}"]\npaths = ["{archive.as_posix()}"]\n',
        encoding="utf-8",
    )
    (tmp_path / "projects.toml").write_text(mapping, encoding="utf-8")
    return tmp_path


def run(space: Path, *argv: str) -> int:
    return main(
        [
            *argv,
            "--config",
            str(space / "config.toml"),
            "--projects",
            str(space / "projects.toml"),
            "--store",
            str(space / "store.db"),
        ]
    )


def ingest(space: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(space, "ingest")
    capsys.readouterr()


def attributions(space: Path) -> dict[str, tuple[str, str, bool]]:
    """subject → (project, rule, is_ad_hoc)."""
    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    rows = connection.execute(
        "SELECT json_extract(r.payload, '$.subject') AS subject, "
        "       p.name AS project, d.rule AS rule, p.ad_hoc AS ad_hoc "
        "FROM derived_attribution d "
        "JOIN raw_record r ON r.id = d.record_id "
        "JOIN user_project p ON p.id = d.project_id"
    ).fetchall()
    connection.close()
    return {
        str(row["subject"]): (str(row["project"]), str(row["rule"]), bool(row["ad_hoc"]))
        for row in rows
    }


ACME = """
[[project]]
name           = "acme-migration"
correspondents = ["anna@acme.example", "acme.example"]
subjects       = ["[ACME]"]
"""


# --- the precedence table, row by row --------------------------------------------------


def test_an_address_rule_matches_a_recipient(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    box = fx.Mailbox()
    box.add(fx.message("Status update", to=(fx.ANNA,)))
    space = workspace(tmp_path, box, ACME)

    ingest(space, capsys)

    project, rule, ad_hoc = attributions(space)["Status update"]
    assert project == "acme-migration"
    assert rule == attribution.Rule.CORRESPONDENT
    assert ad_hoc is False


def test_a_domain_rule_matches_a_subdomain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`acme.example` matches `ops@mail.acme.example` — suffix on labels, not characters."""
    box = fx.Mailbox()
    box.add(fx.message("Ops question", to=(fx.OPS,)))
    space = workspace(tmp_path, box, ACME)

    ingest(space, capsys)

    project, rule, _ = attributions(space)["Ops question"]
    assert project == "acme-migration"
    assert rule == attribution.Rule.CORRESPONDENT_DOMAIN


def test_a_domain_rule_does_not_match_a_lookalike(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`notacme.example` ends with `acme.example` as characters, and must not match."""
    box = fx.Mailbox()
    box.add(fx.message("Wrong company", to=("eve@notacme.example",)))
    space = workspace(tmp_path, box, ACME)

    ingest(space, capsys)

    project, rule, ad_hoc = attributions(space)["Wrong company"]
    assert project == "notacme.example"
    assert rule == attribution.Rule.AD_HOC_DOMAIN
    assert ad_hoc is True


def test_a_subject_rule_beats_a_correspondent_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-036 — a subject is about *this message*; a person works on several things."""
    mapping = """
[[project]]
name           = "by-person"
correspondents = ["bob@northwind.example"]

[[project]]
name     = "by-subject"
subjects = ["[ACME]"]
"""
    box = fx.Mailbox()
    box.add(fx.message("[ACME] to Bob", to=(fx.BOB,)))
    space = workspace(tmp_path, box, mapping)

    ingest(space, capsys)

    project, rule, _ = attributions(space)["[ACME] to Bob"]
    assert project == "by-subject"
    assert rule == attribution.Rule.SUBJECT


def test_an_address_rule_beats_a_domain_rule_declared_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whatever the order.

    Otherwise a broad domain rule declared early would make every precise rule below it
    unreachable — silent shadowing, and very hard to notice in a billing record.
    """
    mapping = """
[[project]]
name           = "everything-acme"
correspondents = ["acme.example"]

[[project]]
name           = "annas-work"
correspondents = ["anna@acme.example"]
"""
    box = fx.Mailbox()
    box.add(fx.message("To Anna", to=(fx.ANNA,)))
    space = workspace(tmp_path, box, mapping)

    ingest(space, capsys)

    project, rule, _ = attributions(space)["To Anna"]
    assert project == "annas-work"
    assert rule == attribution.Rule.CORRESPONDENT


# --- nothing matches -------------------------------------------------------------------


def test_an_unmatched_message_gets_an_ad_hoc_domain_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-038 — nothing is left unattributed, and the guess is marked as one."""
    box = fx.Mailbox()
    box.add(fx.message("Unrelated", to=(fx.BOB,)))
    space = workspace(tmp_path, box, ACME)

    ingest(space, capsys)

    project, rule, ad_hoc = attributions(space)["Unrelated"]
    assert project == "northwind.example"
    assert rule == attribution.Rule.AD_HOC_DOMAIN
    assert ad_hoc is True, "a guess must never read as a decision"


def test_every_message_carries_a_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-002 — 100%, with no exceptions."""
    space = workspace(tmp_path, fx.attribution_cases(), ACME)
    ingest(space, capsys)

    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    unattributed = connection.execute(
        "SELECT count(*) FROM raw_record r "
        "LEFT JOIN derived_attribution d ON d.record_id = r.id "
        "WHERE d.record_id IS NULL"
    ).fetchone()[0]
    connection.close()
    assert unattributed == 0


# --- the ad-hoc domain, precisely ------------------------------------------------------


@pytest.mark.parametrize(
    ("recipients", "own", "expected"),
    [
        # One external domain.
        (["anna@acme.example"], ["example.com"], "acme.example"),
        # Two, one more frequent.
        (["a@acme.example", "b@acme.example", "c@other.example"], ["example.com"], "acme.example"),
        # A genuine tie, broken alphabetically so the answer is stable.
        (["a@zebra.example", "b@alpha.example"], ["example.com"], "alpha.example"),
        # Own domains discarded first.
        (["me@example.com", "anna@acme.example"], ["example.com"], "acme.example"),
        # Only colleagues — falls back to the account's own domain.
        (["colleague@example.com"], ["example.com"], "example.com"),
        # Nothing at all.
        ([], ["example.com"], "example.com"),
    ],
)
def test_the_ad_hoc_domain_is_deterministic(
    recipients: list[str], own: list[str], expected: str
) -> None:
    """FR-039 — 'named after its recipients' domain' has no single answer otherwise."""
    assert attribution.ad_hoc_domain(recipients, own) == expected


def test_the_same_mailbox_read_twice_attributes_identically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-010b — the result depends on the message, never on the order it was read."""
    forwards = tmp_path / "forwards"
    forwards.mkdir()
    ingest(workspace(forwards, fx.attribution_cases(), ACME), capsys)

    # A second, independent store — the same messages, read in the opposite order.
    backwards = tmp_path / "backwards"
    backwards.mkdir()
    reversed_box = fx.Mailbox(messages=list(reversed(fx.attribution_cases().messages)))
    ingest(workspace(backwards, reversed_box, ACME), capsys)

    assert attributions(forwards) == attributions(backwards)


# --- the evidence ------------------------------------------------------------------------


def test_the_evidence_records_what_matched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-035, FR-037 — a message filed somewhere surprising must be explicable."""
    box = fx.Mailbox()
    box.add(fx.message("[ACME] plan", to=(fx.ANNA,)))
    space = workspace(tmp_path, box, ACME)
    ingest(space, capsys)

    path = space / "store.db"
    connection = conn.connect(path)
    migrate.migrate(connection, path)
    evidence = connection.execute(
        "SELECT evidence FROM derived_attribution LIMIT 1"
    ).fetchone()[0]
    connection.close()

    assert "[ACME]" in evidence, "the winning rule is named"
    assert "mapping:subject" in evidence


# --- mapping faults ----------------------------------------------------------------------


def faults(tmp_path: Path, mapping: str) -> list[str]:
    from iknowwhatyoudid.projects import mapping as mapping_module

    path = tmp_path / "projects.toml"
    path.write_text(mapping, encoding="utf-8")
    _, problems = mapping_module.load(path)
    return [p.code for p in problems]


def test_a_malformed_correspondent_blocks(tmp_path: Path) -> None:
    from iknowwhatyoudid.projects import mapping as m

    codes = faults(
        tmp_path, '[[project]]\nname = "p"\ncorrespondents = ["not@an@address"]\n'
    )
    assert m.MALFORMED_CORRESPONDENT in codes


def test_an_empty_subject_rule_blocks(tmp_path: Path) -> None:
    """It would match every message ever sent."""
    from iknowwhatyoudid.projects import mapping as m

    codes = faults(tmp_path, '[[project]]\nname = "p"\nsubjects = [""]\n')
    assert m.EMPTY_SUBJECT_RULE in codes


def test_a_correspondent_claimed_by_two_projects_blocks(tmp_path: Path) -> None:
    """Genuinely ambiguous. Guessing would put billable work on the wrong line."""
    from iknowwhatyoudid.projects import mapping as m

    codes = faults(
        tmp_path,
        '[[project]]\nname = "a"\ncorrespondents = ["anna@acme.example"]\n'
        '[[project]]\nname = "b"\ncorrespondents = ["anna@acme.example"]\n',
    )
    assert m.DUPLICATE_CORRESPONDENT in codes


def test_a_subject_claimed_by_two_projects_blocks(tmp_path: Path) -> None:
    from iknowwhatyoudid.projects import mapping as m

    codes = faults(
        tmp_path,
        '[[project]]\nname = "a"\nsubjects = ["[ACME]"]\n'
        '[[project]]\nname = "b"\nsubjects = ["[acme]"]\n',
    )
    assert m.DUPLICATE_SUBJECT in codes


def test_every_fault_is_reported_in_one_pass(tmp_path: Path) -> None:
    from iknowwhatyoudid.projects import mapping as m

    codes = faults(
        tmp_path,
        '[[project]]\nname = "p"\ncorrespondents = ["bad@@address"]\nsubjects = [""]\n',
    )
    assert m.MALFORMED_CORRESPONDENT in codes
    assert m.EMPTY_SUBJECT_RULE in codes


def test_an_ad_hoc_mail_project_is_marked_in_records_query(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SC-009 — in *every* view, and `0004` added a rule name the old check missed.

    The marker was decided by whether the rule string ended in "ad-hoc", which
    `mapping:ad-hoc-domain` does not. An unmarked guess reads exactly like a decision the
    user made, which is the one thing Principle V forbids.
    """
    box = fx.Mailbox()
    box.add(fx.message("To Anna", to=(fx.ANNA,)))
    box.add(fx.message("To Bob", to=(fx.BOB,), offset_seconds=60))
    space = workspace(tmp_path, box, ACME)
    ingest(space, capsys)

    main(["records", "query", "--store", str(space / "store.db")])
    out = capsys.readouterr().out

    declared = [line for line in out.splitlines() if "acme-migration" in line]
    guessed = [line for line in out.splitlines() if "northwind.example" in line]
    assert declared and guessed
    assert all("(ad hoc)" in line for line in guessed)
    assert not any("(ad hoc)" in line for line in declared)
