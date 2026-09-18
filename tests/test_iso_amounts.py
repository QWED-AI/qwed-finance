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
        result.guard_results.get("BusinessRule.max_amount"),
        result.guard_results.get("BusinessRule.min_amount"),
    )


def _doc(amounts: str) -> str:
    return f"<Document>{amounts}</Document>"


def _tag(amount: str) -> str:
    return f'<IntrBkSttlmAmt Ccy="USD">{amount}</IntrBkSttlmAmt>'


def test_single_agreed_amount_passes_bounds():
    assert _amount_guards(_check(_doc(_tag("100")))) == (True, True)


def test_missing_amount_is_explicit_false():
    assert _amount_guards(_check(_doc(""))) == (False, False)


@pytest.mark.parametrize("bad", ["nan", "Infinity", "-Infinity", "abc", ""])
def test_unparseable_or_nonfinite_amount_is_explicit_false(bad):
    assert _amount_guards(_check(_doc(_tag(bad)))) == (False, False)


def test_agreeing_duplicates_pass():
    xml = _doc(_tag("100") + _tag("100"))
    assert _amount_guards(_check(xml)) == (True, True)


def test_conflicting_duplicates_fail_closed():
    xml = _doc(_tag("100") + _tag("200"))
    assert _amount_guards(_check(xml)) == (False, False)


def test_comment_decoy_amount_fails_closed():
    xml = _doc("<!-- " + _tag("1") + " -->" + _tag("100"))
    assert _amount_guards(_check(xml)) == (False, False)


def test_cdata_amount_fails_closed():
    xml = "<Document><IntrBkSttlmAmt><![CDATA[100]]></IntrBkSttlmAmt></Document>"
    assert _amount_guards(_check(xml)) == (False, False)
