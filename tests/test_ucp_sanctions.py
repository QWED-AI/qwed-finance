"""Regression tests for UCP sanctions screening (#77) and the shared
normalized matcher (#76, #78): parsed-document extraction, bidirectional
name matching, loud empty-list failure, mixed-script review.
"""

from qwed_finance.compliance_guard import (
    has_mixed_scripts,
    normalize_for_screening,
    sanctions_match,
)
from qwed_finance.integrations.ucp import PaymentStatus, UCPIntegration


def test_normalize_folds_perturbations():
    assert normalize_for_screening("BANK-OF  LONDON.") == "bank of london"
    assert normalize_for_screening("ＢＡＮＫ") == "bank"
    assert normalize_for_screening("BA\u200bNK") == "bank"
    assert normalize_for_screening(42) == ""


def test_mixed_script_detected():
    assert has_mixed_scripts("BАNK") is True  # Cyrillic A
    assert has_mixed_scripts("BANK") is False
    assert has_mixed_scripts("") is False


def test_token_set_covers_reversed_names():
    assert sanctions_match("KOREA, NORTH", "NORTH KOREA") is True
    assert sanctions_match("BANK OF LONDON", "BANK OF LONDON PLC") is True
    assert sanctions_match("LONDON", "BANK OF LONDON PLC", allow_reverse=False) is False
    assert sanctions_match("", "BANK") is False


def _doc(body: str) -> str:
    return f"<Document>{body}</Document>"


def test_namespaced_elements_screened():
    xml = _doc(
        '<p:Dbtr xmlns:p="urn:x"><p:Nm>BANNED ENTITY LTD</p:Nm></p:Dbtr>'
    )
    result = UCPIntegration().verify_iso20022_payment(xml, ["BANNED ENTITY LTD"])
    assert result.can_proceed is False
    assert any("SANCTIONS HIT" in v for v in result.violations)


def test_char_ref_entity_screened():
    xml = _doc("<Dbtr><Nm>&#66;ANNED ENTITY LTD</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, ["BANNED ENTITY LTD"])
    assert result.can_proceed is False


def test_reversed_name_screened():
    xml = _doc("<Dbtr><Nm>KOREA, NORTH</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, ["NORTH KOREA"])
    assert result.can_proceed is False


def test_empty_sanctions_list_fails_loud():
    xml = _doc("<Dbtr><Nm>BOB</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, [])
    assert result.can_proceed is False
    assert any("UNSCREENED" in v for v in result.violations)


def test_mixed_script_goes_to_review():
    xml = _doc("<Dbtr><Nm>BАNK</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, ["SOMEONE ELSE"])
    assert result.can_proceed is False
    assert any("REVIEW" in v for v in result.violations)


def test_mixed_script_returns_pending_review_not_blocked():
    xml = _doc("<Dbtr><Nm>BАNK</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, ["SOMEONE ELSE"])
    assert result.status == PaymentStatus.PENDING_REVIEW


def test_mixed_script_has_rejected_receipt():
    xml = _doc("<Dbtr><Nm>BАNK</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, ["SOMEONE ELSE"])
    assert any(
        receipt.verified is False
        and any("REVIEW" in (v or "") for v in (receipt.violations or []))
        for receipt in result.receipts
    )


def test_unscreened_has_rejected_receipt():
    xml = _doc("<Dbtr><Nm>BOB</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, [])
    assert any(
        receipt.verified is False
        and any("UNSCREENED" in (v or "") for v in (receipt.violations or []))
        for receipt in result.receipts
    )


def test_doctype_refused_for_screening():
    xml = (
        '<!DOCTYPE foo [<!ENTITY x "BANNED ENTITY LTD">]>'
        "<Document><Dbtr><Nm>&x;</Nm></Dbtr></Document>"
    )
    result = UCPIntegration().verify_iso20022_payment(xml, ["BANNED ENTITY LTD"])
    assert result.can_proceed is False
    assert any("UNSCREENED" in v for v in result.violations)


def test_oversize_document_refused_for_screening():
    xml = "<Document><Dbtr><Nm>" + "A" * 1_000_001 + "</Nm></Dbtr></Document>"
    result = UCPIntegration().verify_iso20022_payment(xml, [" NOBODY "])
    assert result.can_proceed is False
    assert any("UNSCREENED" in v for v in result.violations)


def test_malformed_xml_unscreened_not_approved():
    result = UCPIntegration().verify_iso20022_payment(
        "<Document><Dbtr><Nm>BOB</Nm></Dbtr>", ["SOMEONE ELSE"]
    )
    assert result.can_proceed is False
    assert any("UNSCREENED" in v for v in result.violations)


def test_adeline_exact_match_blocks():
    xml = _doc(
        "<Dbtr><Nm>BOB</Nm><PstlAdr><AdrLine>BANNED BANK PLC</AdrLine></PstlAdr></Dbtr>"
    )
    result = UCPIntegration().verify_iso20022_payment(xml, ["BANNED BANK PLC"])
    assert result.can_proceed is False
    assert any("SANCTIONS HIT" in v for v in result.violations)


def test_adeline_fragment_no_reverse_match():
    xml = _doc(
        "<Dbtr><Nm>BOB</Nm><PstlAdr><AdrLine>LONDON</AdrLine></PstlAdr></Dbtr>"
    )
    result = UCPIntegration().verify_iso20022_payment(xml, ["BANK OF LONDON PLC"])
    london_reviews = [v for v in result.violations if "LONDON" in v and "REVIEW" in v]
    hit_reviews = [v for v in result.violations if "SANCTIONS HIT" in v]
    assert hit_reviews == []
    assert london_reviews == []
    assert result.status in (PaymentStatus.APPROVED, PaymentStatus.PENDING_REVIEW)


def test_unicode_identical_match_blocks():
    xml = _doc("<Dbtr><Nm>БАНК</Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, ["БАНК"])
    assert result.can_proceed is False
    assert any("SANCTIONS HIT" in v for v in result.violations)


def test_nested_child_name_screened_whole():
    xml = _doc("<Dbtr><Nm>BANNED<Sub> ENTITY LTD</Sub></Nm></Dbtr>")
    result = UCPIntegration().verify_iso20022_payment(xml, ["BANNED ENTITY LTD"])
    assert result.can_proceed is False
    assert any("SANCTIONS HIT" in v for v in result.violations)
