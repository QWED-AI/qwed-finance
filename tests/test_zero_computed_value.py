"""A computed value of zero, or an input the formula cannot use, never verifies (#98).

verify_var, verify_expected_shortfall, verify_convexity and verify_ytm
compared a claim as a percentage of the computed value and skipped the
comparison when that value was zero or negative, so any claim verified.
Zero is now compared absolutely, and inputs the formula cannot evaluate,
and claims that cannot be read, are refused as UNVERIFIABLE instead of
verifying or raising.
"""

from decimal import Decimal

import pytest

from qwed_finance import BondGuard, RiskGuard
from qwed_finance._numeric import (
    UnverifiableError,
    claim,
    number,
    positive_int,
    within_tolerance,
)

R = RiskGuard()
B = BondGuard()


def refused(result) -> bool:
    return result.verified is False and result.computed_value.startswith("UNVERIFIABLE")


# -- the reproduction in #98 --------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: R.verify_var(1_000_000, 0, 0.95, 1, "$5,000,000"),
        lambda: R.verify_var(1_000_000, -0.02, 0.95, 1, "$1"),
        lambda: R.verify_expected_shortfall(1_000_000, 32900, 0, "$999,999"),
        lambda: B.verify_convexity(1000, 0.05, 0.06, 0, "9999"),
    ],
    ids=[
        "var-zero-volatility",
        "var-negative-volatility",
        "es-zero-tail",
        "convexity-zero-maturity",
    ],
)
def test_issue_98_reproduction_no_longer_verifies(call):
    assert call().verified is False


# -- zero compares absolutely ------------------------------------------------


@pytest.mark.parametrize(
    "claimed, expected",
    [
        ("$0.00", True),
        ("$0", True),
        ("0", True),
        ("-0.00", True),
        ("$0.004", True),  # rounds to $0.00
        ("$0.005", False),  # rounds to $0.01: the first claim off zero
        ("$0.01", False),
        ("-$0.01", False),
        ("$1", False),
        ("$5,000,000", False),
    ],
)
def test_zero_var_compares_absolutely(claimed, expected):
    result = R.verify_var(1_000_000, 0, 0.95, 1, claimed)
    assert result.computed_value == "$0.00"
    assert result.verified is expected


def test_zero_var_from_a_zero_portfolio():
    assert R.verify_var(0, 0.02, 0.95, 1, "$0.00").verified is True
    assert R.verify_var(0, 0.02, 0.95, 1, "$1").verified is False


@pytest.mark.parametrize(
    "claimed, expected",
    [("$0.00", True), ("$0.004", True), ("$0.005", False), ("$999,999", False)],
)
def test_zero_expected_shortfall_compares_absolutely(claimed, expected):
    assert (
        R.verify_expected_shortfall(1_000_000, 32900, 0, claimed).verified is expected
    )


def test_refused_zero_claim_reports_an_absolute_difference():
    result = R.verify_var(1_000_000, 0, 0.95, 1, "$1,234.50")
    assert result.verified is False
    assert result.difference == "$1,234.50"


# -- correct answers still verify -------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: R.verify_var(1_000_000, 0.02, 0.95, 1, "$32,900"),
        lambda: R.verify_var(1_000_000, 0.02, 0.95, 10, "$104,038.94"),
        lambda: R.verify_expected_shortfall(1_000_000, 32900, 45000, "$45,000"),
        lambda: B.verify_ytm(1000, 0.05, 950, 10, "5.66%"),
        lambda: B.verify_ytm(1000, 0.0, 613.91, 10, "4.94%"),
        lambda: B.verify_convexity(1000, 0.05, 0.06, 10, "71.7854"),
        lambda: B.verify_convexity(1000, 0.0, 0.06, 5, "25.9214"),
        lambda: B.verify_convexity(1000, 0.05, 0.06, 0.5, "0.4713"),
    ],
    ids=[
        "var-1d",
        "var-10d",
        "es",
        "ytm",
        "ytm-zero-coupon",
        "convexity",
        "convexity-zero-coupon",
        "convexity-one-period",
    ],
)
def test_correct_answers_still_verify(call):
    assert call().verified is True


@pytest.mark.parametrize(
    "call",
    [
        lambda: R.verify_var(1_000_000, 0.02, 0.95, 1, "$40,000"),
        lambda: R.verify_expected_shortfall(1_000_000, 32900, 45000, "$50,000"),
        lambda: B.verify_ytm(1000, 0.05, 950, 10, "7%"),
        lambda: B.verify_convexity(1000, 0.05, 0.06, 10, "90"),
    ],
    ids=["var", "es", "ytm", "convexity"],
)
def test_wrong_answers_are_refused_with_a_relative_difference(call):
    result = call()
    assert result.verified is False
    assert result.difference.endswith("%")


# -- inputs the formula cannot use ---------------------------------------------

BAD_NUMBERS = [float("nan"), float("inf"), float("-inf"), True, None, "100", [1]]


@pytest.mark.parametrize("bad", BAD_NUMBERS)
@pytest.mark.parametrize(
    "position",
    ["portfolio_value", "daily_volatility", "confidence_level", "holding_period_days"],
)
def test_var_refuses_inputs_it_cannot_evaluate(position, bad):
    args = dict(
        portfolio_value=1_000_000,
        daily_volatility=0.02,
        confidence_level=0.95,
        holding_period_days=1,
        llm_var="$32,900",
    )
    args[position] = bad
    assert refused(R.verify_var(**args))


@pytest.mark.parametrize(
    "position, value",
    [
        ("portfolio_value", -1),
        ("daily_volatility", -0.02),
        ("daily_volatility", -1e-12),
        ("holding_period_days", 0),
        ("holding_period_days", -1),
        ("confidence_level", 0),
        ("confidence_level", 1),
        ("confidence_level", 1.5),
        ("confidence_level", -0.95),
    ],
)
def test_var_refuses_inputs_outside_the_formula(position, value):
    args = dict(
        portfolio_value=1_000_000,
        daily_volatility=0.02,
        confidence_level=0.95,
        holding_period_days=1,
        llm_var="$1",
    )
    args[position] = value
    assert refused(R.verify_var(**args))


@pytest.mark.parametrize("bad", BAD_NUMBERS + [-100, -0.01])
@pytest.mark.parametrize("position", ["var_amount", "tail_loss_avg"])
def test_expected_shortfall_refuses_bad_inputs(position, bad):
    args = dict(
        portfolio_value=1_000_000, var_amount=32900, tail_loss_avg=45000, llm_es="$5"
    )
    args[position] = bad
    assert refused(R.verify_expected_shortfall(**args))


@pytest.mark.parametrize(
    "position, value",
    [
        ("face_value", 0),
        ("face_value", -1000),
        ("coupon_rate", -0.05),
        ("price", 0),
        ("price", -950),
        ("years_to_maturity", 0),
        ("years_to_maturity", -10),
        ("years_to_maturity", 0.49),  # under one semi-annual period
        ("frequency", 0),
        ("frequency", -2),
        ("frequency", 2.0),
        ("frequency", True),
        ("face_value", float("nan")),
        ("price", float("inf")),
        ("coupon_rate", True),
    ],
)
def test_ytm_refuses_bonds_with_no_yield_to_solve(position, value):
    args = dict(
        face_value=1000,
        coupon_rate=0.05,
        price=950,
        years_to_maturity=10,
        llm_ytm="5.2632%",  # the solver's starting guess for this bond
    )
    args[position] = value
    assert refused(B.verify_ytm(**args))


@pytest.mark.parametrize(
    "position, value",
    [
        ("face_value", 0),
        ("face_value", -1000),
        ("coupon_rate", -0.05),
        ("years_to_maturity", 0),
        ("years_to_maturity", 0.3),
        ("years_to_maturity", 0.49),
        ("frequency", 0),
        ("frequency", 2.0),
        ("frequency", True),
        ("ytm", -2),  # 1 + y/n == 0
        ("ytm", -3),  # 1 + y/n < 0
        ("ytm", float("nan")),
        ("ytm", True),
    ],
)
def test_convexity_refuses_bonds_it_cannot_price(position, value):
    args = dict(
        face_value=1000,
        coupon_rate=0.05,
        ytm=0.06,
        years_to_maturity=10,
        llm_convexity="0",
    )
    args[position] = value
    assert refused(B.verify_convexity(**args))


def test_convexity_just_above_the_discount_factor_bound_computes():
    # 1 + y/n = 0.0005 > 0: an extreme but defined yield is computed, not refused.
    result = B.verify_convexity(1000, 0.05, -1.999, 1, "0")
    assert not result.computed_value.startswith("UNVERIFIABLE")


# -- claims that cannot be read --------------------------------------------------

BAD_CLAIMS = ["NaN", "-NaN", "sNaN", "Infinity", "-Infinity", "inf", "lots", "", "  "]


@pytest.mark.parametrize("bad", BAD_CLAIMS + [None, 5, 5.0, b"5"])
@pytest.mark.parametrize(
    "call",
    [
        lambda c: R.verify_var(1_000_000, 0.02, 0.95, 1, c),
        lambda c: R.verify_var(1_000_000, 0, 0.95, 1, c),
        lambda c: R.verify_expected_shortfall(1_000_000, 32900, 0, c),
        lambda c: B.verify_ytm(1000, 0.05, 950, 10, c),
        lambda c: B.verify_convexity(1000, 0.05, 0.06, 10, c),
    ],
    ids=["var", "var-zero", "es-zero", "ytm", "convexity"],
)
def test_unreadable_claims_are_refused_not_raised(call, bad):
    assert refused(call(bad))


@pytest.mark.parametrize("huge", ["1e999999", "-1e999999", "9" * 5000])
def test_claims_too_large_to_compare_are_refused(huge):
    """Each used to raise InvalidOperation formatting the claim; now a verdict."""
    assert refused(R.verify_var(1_000_000, 0.02, 0.95, 1, huge))
    assert refused(R.verify_expected_shortfall(1_000_000, 32900, 45000, huge))
    assert refused(B.verify_ytm(1000, 0.05, 950, 10, huge))
    assert refused(B.verify_convexity(1000, 0.05, 0.06, 10, huge))


# -- the shared helpers ------------------------------------------------------------


def test_within_tolerance_scales_by_the_absolute_value():
    """A negative computed value compares relatively too, not as a pass."""
    verified, pct = within_tolerance(
        Decimal("-100"), Decimal("-100.5"), Decimal("1"), Decimal("0.01")
    )
    assert verified is True and pct == Decimal("0.5")
    verified, _ = within_tolerance(
        Decimal("-100"), Decimal("100"), Decimal("1"), Decimal("0.01")
    )
    assert verified is False
    verified, _ = within_tolerance(
        Decimal("-100"), Decimal("999999"), Decimal("1"), Decimal("0.01")
    )
    assert verified is False


def test_within_tolerance_zero_is_absolute():
    assert within_tolerance(
        Decimal("0"), Decimal("0.004"), Decimal("1"), Decimal("0.01")
    ) == (True, None)
    assert within_tolerance(
        Decimal("0"), Decimal("0.005"), Decimal("1"), Decimal("0.01")
    ) == (False, None)
    assert within_tolerance(
        Decimal("0"), Decimal("-0.005"), Decimal("1"), Decimal("0.01")
    ) == (False, None)


@pytest.mark.parametrize(
    "bad", [True, False, None, "1", float("nan"), Decimal("NaN"), Decimal("Infinity")]
)
def test_number_refuses_non_numbers(bad):
    with pytest.raises(UnverifiableError):
        number(bad, "x")


def test_number_bounds_are_inclusive_unless_exclusive():
    assert number(0, "x", minimum=Decimal("0")) == 0
    with pytest.raises(UnverifiableError):
        number(0, "x", minimum=Decimal("0"), exclusive=True)
    with pytest.raises(UnverifiableError):
        number(-1e-12, "x", minimum=Decimal("0"))


@pytest.mark.parametrize("bad", [0, -1, 2.0, True, None, "2"])
def test_positive_int_refuses_non_counts(bad):
    with pytest.raises(UnverifiableError):
        positive_int(bad, "n")


def test_claim_refuses_non_strings_and_non_finite_values():
    for bad in (None, 5, b"5", "NaN", "Infinity"):
        with pytest.raises(UnverifiableError):
            claim(Decimal, bad)
    assert claim(Decimal, "1.5") == Decimal("1.5")


def test_within_tolerance_refuses_a_difference_too_large_to_scale():
    with pytest.raises(UnverifiableError):
        within_tolerance(
            Decimal("1"), Decimal("9e999999"), Decimal("1"), Decimal("0.01")
        )


def test_number_handles_integers_past_the_digit_limit():
    """str() of a huge int raises ValueError on 3.10.7+, where the input is
    refused; with no digit limit it is an exact, finite number."""
    huge = 10**5000
    try:
        result = number(huge, "x")
    except UnverifiableError:
        return
    assert result == Decimal(huge)


def test_bond_difference_is_absolute_when_the_computed_value_is_zero():
    """No bond reaches a zero computed value today: convexity is positive
    with at least one coupon period, and the solver's lower bound keeps a
    yield positive (#100). The absolute report is pinned for when it can."""
    report = BondGuard._difference(
        None, Decimal("0"), Decimal("1.23456"), False, Decimal("0.0001"), "%"
    )
    assert report == "1.2346%"
    assert (
        BondGuard._difference(
            None, Decimal("0"), Decimal("0"), True, Decimal("0.01"), ""
        )
        is None
    )
