"""Regression tests for operative-value receipt coverage (#65) and
business-limit wiring in verify_iso20022_payment (#67).

A well-formed over-limit / disallowed-currency / KYC-less pacs.008 must
never approve, and every verdict must be evidenced by a receipt whose
hash covers the operative amount and currency — not a document prefix.
"""

from qwed_finance.cross_guard import CrossGuard
from qwed_finance.integrations.ucp import PaymentStatus, UCPIntegration
from qwed_finance.models.receipt import ReceiptGenerator

_ALLOWED = ["USD", "EUR", "GBP"]


def _pacs(amount: str = "1000", ccy: str = "USD", filler: str = "") -> str:
    return (
        "<Document>"
        "<GrpHdr><MsgId>A</MsgId><CreDtTm>2026-01-01T00:00:00</CreDtTm>"
        "<NbOfTxs>1</NbOfTxs></GrpHdr>"
        "<CdtTrfTxInf>"
        f"{filler}"
        f"<IntrBkSttlmAmt Ccy=\"{ccy}\">{amount}</IntrBkSttlmAmt>"
        "<Dbtr><Nm>ACME CORP</Nm></Dbtr>"
        "<DbtrAgt>BANKA</DbtrAgt><CdtrAgt>BANKB</CdtrAgt>"
        "</CdtTrfTxInf></Document>"
    )


def _rules(xml: str):
    return CrossGuard().verify_iso20022_with_rules(
        xml, {"allowed_currencies": _ALLOWED, "max_amount": 1000000}
    )


# ===== #65: receipt evidence =====


def test_structure_receipt_hash_covers_full_document():
    # Same first 200 characters, different operative currency: the hash
    # must still separate the documents (#65).
    pad = "<!--" + "P" * 300 + "-->"
    usd = _rules(_pacs(filler=pad))
    eur = _rules(_pacs(ccy="EUR", filler=pad))
    xml = _pacs(filler=pad)
    assert usd.receipts[0].input_hash == ReceiptGenerator.hash_input(xml)
    assert usd.receipts[0].input_hash != eur.receipts[0].input_hash


def test_structure_receipt_preview_stays_bounded():
    pad = "<!--" + "P" * 300 + "-->"
    receipt = _rules(_pacs(filler=pad)).receipts[0]
    assert len(receipt.input_preview) <= 103
    assert receipt.llm_value is None


def test_business_receipt_records_operative_currency_and_amount():
    result = _rules(_pacs(amount="42000", ccy="EUR"))
    business = [
        r for r in result.receipts
        if r.guard_name == "CrossGuard.business_rules"
    ]
    assert len(business) == 1
    receipt = business[0]
    assert receipt.verified is True
    assert "42000" in receipt.input_preview
    assert "EUR" in receipt.input_preview
    assert receipt.metadata["currencies"] == ["EUR"]


def test_business_receipt_evidences_failing_currency_verdict():
    result = _rules(_pacs(amount="1000", ccy="RUB"))
    receipt = next(
        r for r in result.receipts
        if r.guard_name == "CrossGuard.business_rules"
    )
    assert receipt.verified is False
    assert "RUB" in receipt.input_preview
    assert any("not in allowed list" in v for v in receipt.violations)


def test_comment_decoy_currency_does_not_poison_honest_message():
    xml = _pacs(filler='<!-- <IntrBkSttlmAmt Ccy="RUB">1</IntrBkSttlmAmt> -->')
    result = _rules(xml)
    assert result.guard_results.get("BusinessRule.currency") is True
    assert result.passed is True


def test_receipt_breach_classification_is_policy_only():
    # Out-of-bounds agreed amount: policy breach.
    over = CrossGuard().verify_iso20022_with_rules(
        _pacs(amount="2000000"),
        {"allowed_currencies": _ALLOWED, "max_amount": 1000000},
    )
    assert over.policy_breach is True
    # Unparseable amount: structural failure, not a policy verdict.
    broken = CrossGuard().verify_iso20022_with_rules(
        _pacs(amount="nan"),
        {"allowed_currencies": _ALLOWED, "max_amount": 1000000},
    )
    assert broken.policy_breach is False


def test_under_min_amount_is_policy_breach():
    under = CrossGuard().verify_iso20022_with_rules(
        _pacs(amount="0"),
        {"allowed_currencies": _ALLOWED, "min_amount": 1},
    )
    assert under.guard_results.get("BusinessRule.min_amount") is False
    assert under.policy_breach is True


def test_self_closing_amount_fails_closed():
    xml = '<Document><IntrBkSttlmAmt Ccy="USD"/></Document>'
    result = CrossGuard().verify_iso20022_with_rules(
        xml, {"allowed_currencies": _ALLOWED}
    )
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


# ===== #67: business limits wired into the payment path =====


def test_over_limit_payment_blocks():
    result = UCPIntegration().verify_iso20022_payment(
        _pacs(amount="2000000"), ["SOMEONE ELSE"]
    )
    assert result.status == PaymentStatus.BLOCKED
    assert result.can_proceed is False
    assert any("exceeds max" in v for v in result.violations)


def test_disallowed_currency_blocks():
    result = UCPIntegration().verify_iso20022_payment(
        _pacs(amount="10", ccy="RUB"), ["SOMEONE ELSE"]
    )
    assert result.status == PaymentStatus.BLOCKED
    assert result.can_proceed is False
    assert any("not in allowed list" in v for v in result.violations)


def test_kyc_context_missing_never_auto_approves():
    # require_kyc defaults True; a pacs.008 carries no KYC evidence.
    result = UCPIntegration().verify_iso20022_payment(
        _pacs(), ["SOMEONE ELSE"]
    )
    assert result.status == PaymentStatus.PENDING_REVIEW
    assert result.can_proceed is False
    assert any("KYC verification required" in v for v in result.violations)


def test_explicit_kyc_context_approves_clean_payment():
    result = UCPIntegration().verify_iso20022_payment(
        _pacs(), ["SOMEONE ELSE"], kyc_verified=True
    )
    assert result.status == PaymentStatus.APPROVED
    assert result.can_proceed is True
    assert result.violations == []


def test_kyc_disabled_config_approves_without_context():
    result = UCPIntegration(require_kyc=False).verify_iso20022_payment(
        _pacs(), ["SOMEONE ELSE"]
    )
    assert result.status == PaymentStatus.APPROVED
    assert result.can_proceed is True


def test_business_receipts_are_audited():
    ucp = UCPIntegration()
    ucp.verify_iso20022_payment(_pacs(), ["SOMEONE ELSE"])
    assert any(
        r.guard_name == "CrossGuard.business_rules"
        for r in ucp.audit_log.receipts
    )


def test_sanctions_hit_still_blocks_clean_limits():
    # Sanctions outrank everything: a hit stays BLOCKED even when the
    # business rules and KYC would otherwise be satisfiable.
    result = UCPIntegration().verify_iso20022_payment(
        _pacs(), ["ACME CORP"], kyc_verified=True
    )
    assert result.status == PaymentStatus.BLOCKED
    assert any("SANCTIONS HIT" in v for v in result.violations)
