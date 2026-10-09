"""Regression tests for GHSA-mrrj-6m2q-jch9.

The ISO 20022 business rules must judge the amount and currency that an
XML parser reads from the document, never a second, text-based view of
it. A namespace prefix outside a regex character class plus a decoy
inside a processing instruction previously let an over-limit,
disallowed-currency pacs.008 pass the rules and approve.
"""

import pytest

from qwed_finance.cross_guard import CrossGuard
from qwed_finance.integrations.ucp import PaymentStatus, UCPIntegration

_NS = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"
_RULES = {"max_amount": 1000, "allowed_currencies": ["USD"]}


def _pacs(amount_xml: str, namespaces: str = "") -> str:
    return (
        f"<Document{namespaces}>"
        "<GrpHdr><MsgId>A</MsgId><CreDtTm>2026-01-01T00:00:00</CreDtTm>"
        "<NbOfTxs>1</NbOfTxs></GrpHdr>"
        "<CdtTrfTxInf>"
        f"{amount_xml}"
        "<Dbtr><Nm>ACME CORP</Nm></Dbtr>"
        "<DbtrAgt>BANKA</DbtrAgt><CdtrAgt>BANKB</CdtrAgt>"
        "</CdtTrfTxInf></Document>"
    )


def _amount(text: str, ccy: str = "USD") -> str:
    return f'<IntrBkSttlmAmt Ccy="{ccy}">{text}</IntrBkSttlmAmt>'


def _rules(xml: str):
    return CrossGuard().verify_iso20022_with_rules(xml, _RULES)


def _ucp(xml: str):
    ucp = UCPIntegration(max_transaction_amount=1000, allowed_currencies=["USD"])
    return ucp.verify_iso20022_payment(xml, ["SOMEONE ELSE"], kyc_verified=True)


# ===== Advisory reproduction =====

_PREFIXED_WITH_PI_DECOY = _pacs(
    '<?note <IntrBkSttlmAmt Ccy="USD">100.00</IntrBkSttlmAmt>?>'
    '<p·x:IntrBkSttlmAmt Ccy="RUB">9999999.00</p·x:IntrBkSttlmAmt>',
    namespaces=f' xmlns:p·x="{_NS}"',
)


def test_prefixed_amount_behind_pi_decoy_is_judged_on_parsed_value():
    result = _rules(_PREFIXED_WITH_PI_DECOY)
    assert result.passed is False
    assert result.guard_results.get("BusinessRule.max_amount") is False
    assert result.guard_results.get("BusinessRule.currency") is False
    assert result.policy_breach is True


def test_prefixed_amount_behind_pi_decoy_never_approves_payment():
    result = _ucp(_PREFIXED_WITH_PI_DECOY)
    assert result.status == PaymentStatus.BLOCKED
    assert result.can_proceed is False


def test_pi_decoy_alone_does_not_mask_real_amount():
    xml = _pacs(
        '<?note <IntrBkSttlmAmt Ccy="USD">100</IntrBkSttlmAmt>?>'
        + _amount("9999999", ccy="RUB")
    )
    result = _rules(xml)
    assert result.passed is False
    assert result.policy_breach is True


def test_honest_prefixed_amount_still_evaluates():
    xml = _pacs(
        '<p·x:IntrBkSttlmAmt Ccy="USD">500.00</p·x:IntrBkSttlmAmt>',
        namespaces=f' xmlns:p·x="{_NS}"',
    )
    result = _rules(xml)
    assert result.guard_results.get("BusinessRule.amount") is True
    assert result.guard_results.get("BusinessRule.max_amount") is True
    assert result.guard_results.get("BusinessRule.currency") is True


# ===== Mixed content inside the amount element =====


@pytest.mark.parametrize(
    "content",
    [
        "9999999<!-- -->e-5",  # parsers disagree on the text around a comment
        "100<?x?>0",  # processing instruction splits the digits
        "100<Sub>0</Sub>",  # child element
    ],
)
def test_amount_with_child_nodes_fails_closed(content):
    result = _rules(_pacs(_amount(content)))
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False
    assert result.policy_breach is False


# ===== Lexical form =====


@pytest.mark.parametrize(
    "text", ["1e3", "1E3", "1,000", "1_000", "0x10", "1 000", ".5e1", "Infinity"]
)
def test_non_decimal_spellings_are_unparseable(text):
    result = _rules(_pacs(_amount(text)))
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


@pytest.mark.parametrize("text", ["100", "100.50", " 100 ", "0.5", ".5", "1."])
def test_plain_decimal_amounts_still_pass(text):
    result = _rules(_pacs(_amount(text)))
    assert result.guard_results.get("BusinessRule.amount") is True
    assert result.guard_results.get("BusinessRule.max_amount") is True


def test_character_references_are_decoded_exactly_once():
    # The parser reads "1&#48;00" (an escaped reference) as literal text;
    # decoding it a second time would turn it into 1000.
    result = _rules(_pacs(_amount("1&amp;#48;00")))
    assert result.guard_results.get("BusinessRule.amount") is False


# ===== Document-level failures =====


def test_foreign_namespace_decoy_makes_amounts_disagree():
    xml = _pacs(
        _amount("100")
        + '<d:IntrBkSttlmAmt xmlns:d="urn:decoy" Ccy="USD">9999999</d:IntrBkSttlmAmt>'
    )
    result = _rules(xml)
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


@pytest.mark.parametrize(
    "xml",
    [
        _pacs(_amount("100")).replace("</Document>", ""),  # truncated
        _pacs('<u:IntrBkSttlmAmt Ccy="USD">100</u:IntrBkSttlmAmt>'),  # unbound prefix
        '<!DOCTYPE d [<!ENTITY a "100">]>' + _pacs(_amount("&a;")),  # entity
    ],
)
def test_unparseable_documents_fail_closed(xml):
    result = _rules(xml)
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False
