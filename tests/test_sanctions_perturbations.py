"""Regression tests for GHSA-mv2c-jwm9-pfrq.

Single-character perturbations inside a sanctioned name — punctuation or
spacing inside a word, diacritics, stray combining marks, and Latin
look-alike letters — must not clear sanctions screening.
"""

import pytest

from qwed_finance.compliance_guard import normalize_for_screening, sanctions_match
from qwed_finance.cross_guard import CrossGuard
from qwed_finance.integrations.ucp import UCPIntegration

_SANCTIONED = ["EVIL CORP"]

PERTURBED_NAMES = [
    "EV-IL CORP",  # hyphen inside a word
    "E.V.I.L. CORP",  # dotted letters
    "EV IL CORP",  # space inside a word
    "E V I L CORP",  # spaced letters
    "EV/IL CORP",
    "\u00c9VIL CORP",  # precomposed diacritic
    "E\u0301VIL CORP",  # combining acute accent
    "EV\u0331IL CORP",  # stray combining mark inside the word
    "EV\u2800IL CORP",  # braille blank
    "EV\u0131L CORP",  # dotless i
    "\u1d07\u1d20\u026a\u029f \u1d04\u1d0f\u0280\u1d18",  # small capitals
]


def _mt(beneficiary: str) -> str:
    return (
        "{1:F01BANKBEBBAXXX0000000000}{2:I103BANKDEFFXXXXN}{4:\n"
        ":20:REF1\n:23B:CRED\n:32A:260115USD1000,00\n"
        ":50K:/111\nALICE\n"
        f":59:/222\n{beneficiary}\n"
        ":71A:SHA\n-}"
    )


def _pacs(debtor_name: str) -> str:
    return (
        "<Document><CdtTrfTxInf>"
        '<IntrBkSttlmAmt Ccy="USD">100</IntrBkSttlmAmt>'
        f"<Dbtr><Nm>{debtor_name}</Nm></Dbtr>"
        "</CdtTrfTxInf></Document>"
    )


@pytest.mark.parametrize("name", PERTURBED_NAMES)
def test_perturbed_name_is_not_cleared_in_mt103(name):
    result = CrossGuard().verify_swift_with_sanctions(_mt(name), _SANCTIONED)
    assert result.passed is False


@pytest.mark.parametrize("name", PERTURBED_NAMES)
def test_perturbed_name_is_not_approved_in_iso20022(name):
    result = UCPIntegration().verify_iso20022_payment(
        _pacs(name), _SANCTIONED, kyc_verified=True
    )
    assert result.can_proceed is False


@pytest.mark.parametrize(
    "name",
    [
        "EV-IL CORP",
        "E.V.I.L. CORP",
        "\u00c9VIL CORP",
        "EV\u0131L CORP",
        "\u1d07\u1d20\u026a\u029f \u1d04\u1d0f\u0280\u1d18",
    ],
)
def test_matcher_hits_perturbed_names_forward_only(name):
    # Forward-only (address-fragment mode) must catch them too: the
    # perturbation is inside the sanctioned name, not a fragment of it.
    assert sanctions_match(name, "EVIL CORP", allow_reverse=False) is True


def test_pure_greek_lookalike_spelling_matches_latin_entry():
    assert sanctions_match("\u0392\u0391\u039d\u039a", "BANK") is True


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Jos\u00e9", "jose"),
        ("M\u00dcLLER GmbH", "muller gmbh"),
        ("\u1d07\u1d20\u026a\u029f", "evil"),
        ("EV\u0131L", "evil"),
        ("BANK-OF  LONDON.", "bank of london"),
    ],
)
def test_normalization_folds_diacritics_and_lookalikes(value, expected):
    assert normalize_for_screening(value) == expected


@pytest.mark.parametrize(
    "entity, sanctioned, allow_reverse",
    [
        ("LONDON", "BANK OF LONDON PLC", False),  # address fragment
        ("MIRANDA SMITH", "BANK OF LONDON PLC", True),
        ("JOSE GARCIA LTD", "EVIL CORP", True),
        ("BOB", "BENTLEY MOTORS", True),
        ("ALICE TRADING", "ACE TRADE", True),
        ("EVE ILCO", "EVIL CORP", False),
    ],
)
def test_unrelated_names_still_clear(entity, sanctioned, allow_reverse):
    assert sanctions_match(entity, sanctioned, allow_reverse=allow_reverse) is False


def test_identical_non_latin_names_still_match():
    assert (
        sanctions_match("\u0411\u0410\u041d\u041a", "\u0411\u0410\u041d\u041a") is True
    )
