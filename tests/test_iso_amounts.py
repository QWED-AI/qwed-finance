"""Regression tests for ISO amount rules (#66).

Missing/unparseable/non-finite/ambiguous IntrBkSttlmAmt amounts must be
explicit False verdicts, never silent skips; multiple occurrences must
agree.
"""

import pytest

from qwed_finance.cross_guard import CrossGuard

_RULES = {"max_amount": 1000000, "min_amount": 1}


def _check(xml: str):
    return CrossGuard().verify_iso20022_with_rules(xml, _RULES)


def _amount_guards(result):
    return (
        result.guard_results.get("BusinessRule.amount"),
        result.guard_results.get("BusinessRule.max_amount"),
        result.guard_results.get("BusinessRule.min_amount"),
    )


def _doc(amounts: str) -> str:
    return f"<Document>{amounts}</Document>"


def _tag(amount: str) -> str:
    return f'<IntrBkSttlmAmt Ccy="USD">{amount}</IntrBkSttlmAmt>'


def test_single_agreed_amount_passes_bounds():
    assert _amount_guards(_check(_doc(_tag("100")))) == (True, True, True)


def test_missing_amount_is_explicit_false():
    result = _check(_doc(""))
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


@pytest.mark.parametrize("bad", ["nan", "Infinity", "-Infinity", "abc", ""])
def test_unparseable_or_nonfinite_amount_is_explicit_false(bad):
    result = _check(_doc(_tag(bad)))
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


def test_agreeing_duplicates_pass():
    xml = _doc(_tag("100") + _tag("100"))
    assert _amount_guards(_check(xml)) == (True, True, True)


def test_conflicting_duplicates_fail_closed():
    result = _check(_doc(_tag("100") + _tag("200")))
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


def test_comment_decoy_ignored_real_decides():
    xml = _doc("<!-- " + _tag("1") + " -->" + _tag("100"))
    assert _amount_guards(_check(xml)) == (True, True, True)


def test_comment_only_amount_is_missing():
    xml = _doc("<!-- " + _tag("1") + " -->")
    result = _check(xml)
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


def test_cdata_amount_evaluates_as_logical_value():
    xml = "<Document><IntrBkSttlmAmt><![CDATA[100]]></IntrBkSttlmAmt></Document>"
    assert _amount_guards(_check(xml)) == (True, True, True)


def test_cdata_exceeding_amount_fails_bounds():
    xml = "<Document><IntrBkSttlmAmt><![CDATA[9999999]]></IntrBkSttlmAmt></Document>"
    result = _check(xml)
    assert result.guard_results.get("BusinessRule.max_amount") is False
    assert result.passed is False


def test_empty_second_occurrence_fails_closed():
    xml = _doc(_tag("100") + "<IntrBkSttlmAmt></IntrBkSttlmAmt>")
    result = _check(xml)
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


def test_float_collapse_distinct_amounts_fail_closed():
    xml = _doc(_tag("9007199254740993") + _tag("9007199254740992"))
    result = _check(xml)
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.passed is False


def test_mixed_currencies_fail_closed():
    xml = (
        '<Document><IntrBkSttlmAmt Ccy="USD">100</IntrBkSttlmAmt>'
        '<IntrBkSttlmAmt Ccy="EUR">100</IntrBkSttlmAmt></Document>'
    )
    result = CrossGuard().verify_iso20022_with_rules(
        xml, {"allowed_currencies": ["USD", "EUR"]}
    )
    assert result.guard_results.get("BusinessRule.currency") is False
    assert result.passed is False


def test_allowed_ccy_plus_missing_ccy_fails_closed():
    xml = (
        '<Document><IntrBkSttlmAmt Ccy="USD">100</IntrBkSttlmAmt>'
        "<IntrBkSttlmAmt>100</IntrBkSttlmAmt></Document>"
    )
    result = CrossGuard().verify_iso20022_with_rules(
        xml, {"allowed_currencies": ["USD"]}
    )
    assert result.guard_results.get("BusinessRule.currency") is False
    assert result.passed is False


def test_missing_currency_with_configured_rule_fails_closed():
    xml = "<Document><IntrBkSttlmAmt>100</IntrBkSttlmAmt></Document>"
    result = CrossGuard().verify_iso20022_with_rules(
        xml, {"allowed_currencies": ["USD"]}
    )
    assert result.guard_results.get("BusinessRule.currency") is False
    assert result.passed is False


def test_unresolved_amount_keeps_configured_bound_verdicts():
    result = _check(_doc(_tag("nan")))
    assert result.guard_results.get("BusinessRule.amount") is False
    assert result.guard_results.get("BusinessRule.max_amount") is False
    assert result.guard_results.get("BusinessRule.min_amount") is False
    assert result.passed is False


def test_unconfigured_bounds_stay_absent_on_failure():
    xml = _doc(_tag("nan"))
    result = CrossGuard().verify_iso20022_with_rules(xml, {})
    assert result.guard_results.get("BusinessRule.amount") is False
    assert "BusinessRule.max_amount" not in result.guard_results
    assert "BusinessRule.min_amount" not in result.guard_results
    assert result.passed is False
