"""Normalising mail addresses (FR-031, research R12).

Deliberately **not** inside `mail/`. Both `mail/` and `projects/` need it — one to record
an address, the other to match a mapping rule against one — and `projects/` is forbidden
from importing `mail/` so that re-derivation is provably unable to contact an account.

Making an exception for "the harmless part of mail/" would turn that boundary from a rule
a test can check into a judgement a future author has to re-make. This module has no I/O
of any kind, so it belongs above both rather than inside either.

The rule stops at case, and that is a decision rather than an omission.

Lowercasing is the only transformation that is universally safe: RFC 5321 permits a
case-sensitive local part, but no provider in practice treats one that way, and a user
who wrote `Anna@Acme.example` in their mapping means the same person as `anna@acme.example`.

What is deliberately **not** done is provider-specific canonicalisation — stripping
Gmail's dots, or removing a `+tag`. Both would merge addresses the user never declared
equivalent, and the specification's own assumption is that recognising one human behind
several addresses is out of scope here. A `+client` tag is also frequently the exact
signal a correspondent rule wants to key on; erasing it would destroy information to
make a guess.
"""

from __future__ import annotations

import re
from email.utils import getaddresses, parseaddr

#: Deliberately permissive. This is not RFC 5322 validation — that is famously not a
#: regular language — it is a check that an entry could ever match a real address, so a
#: typo in a mapping file becomes a blocking finding instead of a rule that silently
#: never fires.
_PLAUSIBLE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise(raw: str) -> str:
    """One address, in the form everything downstream compares.

    Accepts any of the shapes a header or a configuration file produces: a bare address,
    one in angle brackets, or one behind a display name.
    """
    _, address = parseaddr(raw.strip())
    return address.strip().lower()


def display_name_of(raw: str) -> str | None:
    """The display name, if there is one.

    Kept for showing to a person and **never** used for matching: a display name is set
    by whoever sent the message and can say anything at all.
    """
    name, _ = parseaddr(raw.strip())
    return name.strip() or None


def domain_of(address: str) -> str:
    """The part after the `@`, lowercased.

    Stored as its own column and returned separately because both domain rules and the
    ad-hoc project fallback key on it, and neither should re-split a string per row.
    """
    normalised = normalise(address)
    _, _, domain = normalised.partition("@")
    return domain


def is_valid(raw: str) -> bool:
    """Whether this could ever be a real address."""
    return bool(_PLAUSIBLE.match(normalise(raw)))


def parse_list(header: str) -> list[str]:
    """Every address in a `To` or `Cc` header, normalised, in the order given.

    Order is preserved because a recipient list is evidence: the first name on it is
    usually who the message was actually for.
    """
    return [
        normalise(address)
        for _, address in getaddresses([header])
        if address.strip()
    ]


def domains_of(addresses: list[str]) -> list[str]:
    return [domain_of(address) for address in addresses]
