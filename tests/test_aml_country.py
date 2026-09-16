"""Regression tests for AML country canonicalization (#70).

Covers normalize_country_code plus the fail-closed handling at both
entry points (ComplianceGuard.verify_aml_flag and the open_responses
tool twin): punctuation, alpha-3, full names, non-strings, NFKC input,
unassigned codes, and missing values.
"""

import pytest

from qwed_finance.compliance_guard import ComplianceGuard, normalize_country_code
from qwed_finance.integrations.open_responses import OpenResponsesIntegration
from qwed_finance.integrations.ucp import PaymentStatus, UCPIntegration


@pytest.mark.parametrize("raw,expected", [
    ("YE", "YE"),
    ("ye", "YE"),
    (" YE ", "YE"),
    ("us", "US"),
    ("CV", "CV"),
    ("SZ", "SZ"),
])
def test_normalize_accepts_canonical_forms(raw, expected):
    assert normalize_country_code(raw) == expected


def test_normalize_nfkc_fullwidth():
    assert normalize_country_code("\uff39\uff25") == "YE"


@pytest.mark.parametrize("raw", [
    "ZZ", "AA",  # unassigned shape-valid codes must not clear
    "YEM", "Yemen", "Y E", "YE.", "U S",
    "", "USA", "Ye s",
    42, None, ["US"], {"code": "US"}, b"US",
])
def test_normalize_rejects_unevaluable(raw):
    with pytest.raises(ValueError):
        normalize_country_code(raw)


@pytest.mark.parametrize("raw", ["YE", " YE ", "ye"])
def test_guard_flags_high_risk_spellings(raw):
    result = ComplianceGuard().verify_aml_flag(
        amount=100, country_code=raw, llm_flagged=False
    )
    assert result.compliant is False
    assert result.expected_action == "FLAG"


@pytest.mark.parametrize("raw", ["YEM", "ZZ", " YE. ", 42, None])
def test_guard_fails_closed_on_unevaluable(raw):
    result = ComplianceGuard().verify_aml_flag(
        amount=100, country_code=raw, llm_flagged=False
    )
    assert result.compliant is False
    assert result.rule_violated == "AML_COUNTRY_UNVERIFIABLE"
    assert result.expected_action == "FLAG"


def test_guard_still_clears_legitimate():
    result = ComplianceGuard().verify_aml_flag(
        amount=100, country_code=" us ", llm_flagged=False
    )
    assert result.compliant is True


@pytest.mark.parametrize("raw", ["YE", " YE ", "YEM", "ZZ", 42, None])
def test_tool_twin_flags_unevaluable(raw):
    result = OpenResponsesIntegration().handle_tool_call(
        "check_aml_compliance", {"amount": 100, "country_code": raw}
    )
    assert result.result["needs_flagging"] is True


def test_tool_twin_missing_country_flagged():
    result = OpenResponsesIntegration().handle_tool_call(
        "check_aml_compliance", {"amount": 100}
    )
    assert result.result["needs_flagging"] is True
    assert "country" in result.result["reason"].lower()


def test_tool_twin_still_clears_legitimate():
    result = OpenResponsesIntegration().handle_tool_call(
        "check_aml_compliance", {"amount": 100, "country_code": "US"}
    )
    assert result.result["needs_flagging"] is False
    assert result.result["reason"] == "Clear"


def test_ucp_missing_customer_country_pending_review():
    result = UCPIntegration().verify_payment_token(
        {"amount": 100, "currency": "USD", "kyc_verified": True}
    )
    assert result.status == PaymentStatus.PENDING_REVIEW
    assert result.can_proceed is False
    assert any(
        "AML_COUNTRY_UNVERIFIABLE" in (receipt.violations or [])
        for receipt in result.receipts
    )


def test_ucp_explicit_country_still_clears():
    result = UCPIntegration().verify_payment_token(
        {
            "amount": 100,
            "currency": "USD",
            "customer_country": "US",
            "kyc_verified": True,
        }
    )
    assert result.can_proceed is True
