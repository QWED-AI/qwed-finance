"""Regression tests for operative-value receipt coverage (#65) and
business-limit wiring in verify_iso20022_payment (#67).

A well-formed over-limit / disallowed-currency / KYC-less pacs.008 must
never approve, and every verdict must be evidenced by a receipt whose
hash covers the operative amount and currency — not a document prefix.
"""

import hashlib
import json

from qwed_finance.cross_guard import CrossGuard
from qwed_finance.integrations.ucp import PaymentStatus, UCPIntegration
from qwed_finance.message_guard import MessageGuard
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


# ===== #88 review fixes =====


def test_surrogate_input_fails_closed_without_crash():
    # Unpaired surrogates appear in malformed input exactly when
    # validation is about to reject it: hashing, size checks, and
    # screening must all fail closed, never raise (#88).
    bad = "<Document>\ud800</Document>"
    result = CrossGuard().verify_iso20022_with_rules(
        bad, {"allowed_currencies": _ALLOWED}
    )
    assert result.passed is False
    ucp = UCPIntegration().verify_iso20022_payment(bad, ["SOMEONE ELSE"])
    assert ucp.can_proceed is False
    assert ucp.status == PaymentStatus.BLOCKED


def test_namespaced_amount_and_currency_extracted():
    xml = (
        '<Document xmlns:p="urn:x">'
        '<p:IntrBkSttlmAmt Ccy="USD">100</p:IntrBkSttlmAmt></Document>'
    )
    rules = CrossGuard().check_business_rules(
        xml, {"allowed_currencies": _ALLOWED}
    )
    assert rules.guard_results.get("BusinessRule.amount") is True
    assert rules.guard_results.get("BusinessRule.currency") is True


def test_character_references_decode_before_judging():
    # A real parser reads `1&#48;00` as 1000 and `US&#68;` as USD; the
    # rules engine must judge the same value instead of false-rejecting.
    xml = (
        "<Document>"
        '<IntrBkSttlmAmt Ccy="US&#68;">1&#48;00</IntrBkSttlmAmt></Document>'
    )
    rules = CrossGuard().check_business_rules(
        xml, {"allowed_currencies": _ALLOWED}
    )
    assert rules.guard_results.get("BusinessRule.amount") is True
    assert rules.guard_results.get("BusinessRule.currency") is True
    assert rules.receipts[0].metadata["currencies"] == ["USD"]


def test_missing_currency_sibling_is_structural_not_policy():
    # One disallowed present currency plus a Ccy-less sibling is a
    # structural failure — it must never classify as a policy breach,
    # which would route the document to BLOCKED instead of review (#88).
    mixed = (
        '<Document><IntrBkSttlmAmt Ccy="RUB">100</IntrBkSttlmAmt>'
        "<IntrBkSttlmAmt>100</IntrBkSttlmAmt></Document>"
    )
    rules = CrossGuard().check_business_rules(
        mixed, {"allowed_currencies": ["USD"]}
    )
    assert rules.guard_results.get("BusinessRule.currency") is False
    assert rules.policy_breach is False


def test_structure_invalid_over_limit_routes_to_review():
    # A malformed document with extractable over-limit text is a
    # manual-review case; the policy breach must not outrank the
    # documented structural-error path (#88).
    xml = (
        "<Document><GrpHdr><MsgId>A</MsgId>"
        "<CreDtTm>2026-01-01T00:00:00</CreDtTm></GrpHdr>"
        "<CdtTrfTxInf>"
        '<IntrBkSttlmAmt Ccy="USD">2000000</IntrBkSttlmAmt>'
        "<Dbtr><Nm>ACME CORP</Nm></Dbtr>"
        "<DbtrAgt>A</DbtrAgt><CdtrAgt>B</CdtrAgt>"
        "</CdtTrfTxInf></Document>"
    )
    result = UCPIntegration().verify_iso20022_payment(
        xml, ["SOMEONE ELSE"]
    )
    assert result.status == PaymentStatus.PENDING_REVIEW
    assert result.can_proceed is False
    assert any("exceeds max" in v for v in result.violations)


def test_capability_advertises_kyc_verified_input():
    capability = UCPIntegration.get_capability_definition()
    operation = next(
        op for op in capability["supported_operations"]
        if op["name"] == "verify_iso20022_payment"
    )
    assert "kyc_verified" in operation["input"]


def test_non_string_message_fails_closed_for_screening():
    # None (or any non-str) must route to the refused-for-screening
    # path, never raise before verdicts are computed (#88).
    result = UCPIntegration().verify_iso20022_payment(None, ["SOMEONE ELSE"])
    assert result.status == PaymentStatus.BLOCKED
    assert result.can_proceed is False


def test_hash_input_covers_non_string_payloads():
    # Receipt hashing accepts dicts and scalars as well as strings; the
    # non-string branches must stay exercised by the receipt suite (#88).
    payload = {"amount": "1000", "currencies": ["USD"]}
    digest = ReceiptGenerator.hash_input(payload)
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8", "surrogatepass")
    ).hexdigest()
    assert digest == expected
    assert len(ReceiptGenerator.hash_input(12345)) == 64
    # Injective encoding: an unpaired surrogate and the literal escape
    # text are different documents and must never share a receipt hash.
    assert ReceiptGenerator.hash_input(
        "\ud800"
    ) != ReceiptGenerator.hash_input("\\ud800")


def test_parse_xml_non_string_fails_closed():
    # Environments without lxml reach _parse_xml directly; non-str input
    # must return None (malformed) instead of raising AttributeError (#88).
    assert MessageGuard._parse_xml(None) is None
    assert MessageGuard._parse_xml(123) is None


def test_zero_and_negative_amounts_block():
    # Neither zero nor a negative settlement is a legitimate payment: with
    # the positive-amount rule both are deterministic breaches (#88).
    for amount in ("0", "-100"):
        result = UCPIntegration().verify_iso20022_payment(
            _pacs(amount=amount), ["SOMEONE ELSE"], kyc_verified=True
        )
        assert result.status == PaymentStatus.BLOCKED, amount
        assert result.can_proceed is False
        assert any("positive" in v for v in result.violations), amount


def test_positive_amount_guard_reports_both_verdicts():
    rules = CrossGuard().check_business_rules(
        _pacs(amount="100"),
        {"allowed_currencies": _ALLOWED, "positive_amount": True},
    )
    assert rules.guard_results.get("BusinessRule.positive_amount") is True
    assert rules.policy_breach is False
    zero = CrossGuard().check_business_rules(
        _pacs(amount="0"),
        {"allowed_currencies": _ALLOWED, "positive_amount": True},
    )
    assert zero.guard_results.get("BusinessRule.positive_amount") is False
    assert zero.policy_breach is True


def test_unlimited_max_amount_does_not_crash():
    # None means "no limit": the bound is skipped, not converted to
    # Decimal("None"), and a clean payment still approves (#88).
    result = UCPIntegration(max_transaction_amount=None).verify_iso20022_payment(
        _pacs(amount="500"), ["SOMEONE ELSE"], kyc_verified=True
    )
    assert result.status == PaymentStatus.APPROVED
    assert result.can_proceed is True


def test_zero_occurrences_currency_violation_reports_absence():
    # Zero occurrences is an absence, not a disagreement: the audit
    # trail must not claim currencies conflicted when none exist (#88).
    rules = CrossGuard().check_business_rules(
        "<Document></Document>", {"allowed_currencies": _ALLOWED}
    )
    assert rules.guard_results.get("BusinessRule.currency") is False
    assert not any("must agree" in v for v in rules.violations)
    assert any("no occurrence to verify currency" in v for v in rules.violations)


def test_unparseable_amount_outranks_currency_breach():
    # Structural precedence: an unparseable amount routes to manual
    # review even when a disallowed currency is also present — never
    # BLOCKED on a policy verdict the engine cannot fully ground (#88).
    rules = CrossGuard().check_business_rules(
        _pacs(amount="nan", ccy="RUB"),
        {"allowed_currencies": ["USD"], "max_amount": 1000000},
    )
    assert rules.policy_breach is False
    result = UCPIntegration().verify_iso20022_payment(
        _pacs(amount="nan", ccy="RUB"), ["SOMEONE ELSE"], kyc_verified=True
    )
    assert result.status == PaymentStatus.PENDING_REVIEW
    assert result.can_proceed is False


def test_none_allow_list_fails_closed_without_crash():
    # A None allow-list is a misconfiguration: membership against it
    # must fail closed (empty list), never raise TypeError (#88).
    rules = CrossGuard().check_business_rules(
        _pacs(), {"allowed_currencies": None}
    )
    assert rules.guard_results.get("BusinessRule.currency") is False
    assert any("not in allowed list" in v for v in rules.violations)


def test_ccy_attribute_name_boundary_enforced():
    # NotCcy="USD" must never be read as the currency attribute: the
    # spoofed attribute is a substring match, the real Ccy="RUB" is
    # what the business rule must judge (#88).
    spoofed = _pacs().replace(
        '<IntrBkSttlmAmt Ccy="USD">',
        '<IntrBkSttlmAmt NotCcy="USD" Ccy="RUB">',
    )
    rules = CrossGuard().check_business_rules(
        spoofed, {"allowed_currencies": _ALLOWED}
    )
    assert rules.guard_results.get("BusinessRule.currency") is False
    assert rules.policy_breach is True
    result = UCPIntegration().verify_iso20022_payment(
        spoofed, ["SOMEONE ELSE"], kyc_verified=True
    )
    assert result.status == PaymentStatus.BLOCKED
    assert result.can_proceed is False


def test_quoted_decoy_ccy_inside_attribute_value_is_ignored():
    # Note=" Ccy='USD'" carries a decoy inside a quoted value: the
    # extractor must read the real Ccy attribute pair, not raw text (#88).
    decoy = _pacs().replace(
        '<IntrBkSttlmAmt Ccy="USD">',
        '<IntrBkSttlmAmt Note=" Ccy=\'USD\'" Ccy="RUB">',
    )
    rules = CrossGuard().check_business_rules(
        decoy, {"allowed_currencies": _ALLOWED}
    )
    assert rules.guard_results.get("BusinessRule.currency") is False
    assert rules.policy_breach is True
    result = UCPIntegration().verify_iso20022_payment(
        decoy, ["SOMEONE ELSE"], kyc_verified=True
    )
    assert result.status == PaymentStatus.BLOCKED


def test_qualified_currency_attribute_is_recognized():
    # ns0:Ccy is the currency attribute under a namespace prefix: a
    # structurally clean payment must approve, not degrade to review (#88).
    xml = (
        _pacs()
        .replace("<Document>", '<Document xmlns:ns0="urn:test">')
        .replace(
            '<IntrBkSttlmAmt Ccy="USD">',
            '<ns0:IntrBkSttlmAmt ns0:Ccy="USD">',
        )
        .replace("</IntrBkSttlmAmt>", "</ns0:IntrBkSttlmAmt>")
    )
    result = UCPIntegration().verify_iso20022_payment(
        xml, ["SOMEONE ELSE"], kyc_verified=True
    )
    assert result.status == PaymentStatus.APPROVED
    assert result.can_proceed is True
