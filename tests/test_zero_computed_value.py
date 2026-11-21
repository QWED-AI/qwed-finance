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

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with pandas
    np = None

# Only the NumPy tests skip without NumPy; the rest of the module still runs.
needs_numpy = pytest.mark.skipif(np is None, reason="numpy is not installed")

# NumPy float types by name, looked up explicitly rather than by getattr.
NUMPY_FLOATS = (
    {}
    if np is None
    else {"float16": np.float16, "float32": np.float32, "float64": np.float64}
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
    assert R.verify_expected_shortfall(1_000_000, 0, 0, claimed).verified is expected


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
        lambda: B.verify_ytm(1000, 0.0, 1000, 10, "0%"),
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
        "ytm-zero-coupon-at-par",
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
@pytest.mark.parametrize("position", ["portfolio_value", "var_amount", "tail_loss_avg"])
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
        lambda c: R.verify_expected_shortfall(1_000_000, 0, 0, c),
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
    assert verified is True
    assert pct == Decimal("0.5")
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
    """The absolute report pinned at the helper. Through the public API a
    zero yield comes from a zero-coupon bond priced at par, which never
    reaches the solver's lower bound (#100); convexity with at least one
    coupon period is always positive."""
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


# -- a zero-coupon bond at par: any claim verified on main ---------------------


@pytest.mark.parametrize(
    "claimed, expected",
    [
        ("0%", True),
        ("0.0000%", True),
        ("0", True),
        ("0.00005%", False),
        ("25%", False),
        ("999%", False),
    ],
)
def test_zero_yield_at_par_compares_absolutely(claimed, expected):
    """At par a zero-coupon bond yields exactly 0, which the solver returns
    before its lower bound applies. main skipped the comparison and verified
    every claim, 999 % included."""
    result = B.verify_ytm(1000, 0.0, 1000, 10, claimed)
    assert result.computed_value == "0.0000%"
    assert result.verified is expected


# -- expected shortfall cannot be below VaR -------------------------------------


@pytest.mark.parametrize(
    "var_amount, tail_loss_avg, verifies",
    [
        (32900, 0, False),
        (32900, 32899.99, False),
        (32900, 32900, True),
        (32900, 45000, True),
        (0, 0, True),
    ],
)
def test_expected_shortfall_below_var_is_refused(var_amount, tail_loss_avg, verifies):
    claimed = f"${tail_loss_avg:,.2f}"
    result = R.verify_expected_shortfall(1_000_000, var_amount, tail_loss_avg, claimed)
    assert result.verified is verifies
    if not verifies:
        assert refused(result)


# -- coupon periods: bounded, and counted exactly -------------------------------


@pytest.mark.parametrize("call", ["ytm", "convexity"])
@pytest.mark.parametrize("years", [1e308, 1e18, 100.1])
def test_maturity_past_the_period_bound_is_refused(call, years):
    """1e308 overflowed the float period count and raised OverflowError; a
    large finite maturity was an unbounded amount of solver work."""
    if call == "ytm":
        result = B.verify_ytm(1000, 0.05, 950, years, "5%", frequency=12)
    else:
        result = B.verify_convexity(1000, 0.05, 0.06, years, "5", frequency=12)
    assert refused(result)
    assert "1200 coupon periods" in result.computed_value


def test_maturity_at_the_period_bound_is_computed():
    result = B.verify_ytm(1000, 0.05, 950, 100, "5.2646%", frequency=12)
    assert result.verified is True
    assert result.details["periods"] == 1200


# -- a refused claim is echoed as one escaped line --------------------------------

HOSTILE_CLAIMS = [
    "5\n::warning::injected",
    "5\r\n::error::injected",
    "5\r::set-output name=x::y",
    "5\u2028::warning::line separator",
    "5\x85::warning::next line",
    "5\x1b[31mred",
    "x" * 5000,
]


@pytest.mark.parametrize("hostile", HOSTILE_CLAIMS)
@pytest.mark.parametrize(
    "call",
    [
        lambda c: R.verify_var(1_000_000, 0.02, 0.95, 1, c),
        lambda c: R.verify_expected_shortfall(1_000_000, 32900, 45000, c),
        lambda c: R.verify_sortino_ratio(0.1, 0.0, [-0.1, 0.05], c),
        lambda c: B.verify_ytm(1000, 0.05, 950, 10, c),
        lambda c: B.verify_convexity(1000, 0.05, 0.06, 10, c),
    ],
    ids=["var", "es", "sortino", "ytm", "convexity"],
)
def test_refused_claims_are_echoed_on_one_short_line(call, hostile):
    """Callers print results; the GitHub Action writes them to its log, where
    a line starting with :: is a workflow command."""
    result = call(hostile)
    assert result.verified is False
    assert result.llm_value.isprintable()
    assert len(result.llm_value) <= 80


def test_shown_keeps_short_printable_claims_readable():
    from qwed_finance._numeric import shown

    assert shown("lots") == "'lots'"
    assert shown(None) == "<non-string claim>"
    assert shown("5\n::x") == "'5\\n::x'"


# -- round 2 -------------------------------------------------------------------


@pytest.mark.parametrize("months", [1, 2, 4, 8, 11])
def test_monthly_float_maturities_count_every_period(months):
    """months/12 in float carries representation error: Decimal(str(2/12)) * 12
    is 1.99...92, which truncated to one period. A float count within float
    error of a whole number is that number."""
    result = B.verify_ytm(1000, 0.05, 999, months / 12, "5%", frequency=12)
    assert result.details["periods"] == months


def test_two_month_convexity_prices_two_periods():
    assert (
        B.verify_convexity(1000, 0, 0, 2 / 12, "0.0417", frequency=12).verified is True
    )


def test_one_month_bond_is_priced_not_refused():
    result = B.verify_convexity(1000, 0, 0, 1 / 12, "0", frequency=12)
    assert not result.computed_value.startswith("UNVERIFIABLE")


def test_an_explicit_decimal_maturity_is_never_snapped():
    """A Decimal maturity is exact: 0.16666666666666666 years is just under
    two monthly periods, and counts as one."""
    result = B.verify_ytm(
        1000, 0.05, 999, Decimal("0.16666666666666666"), "5%", frequency=12
    )
    assert result.details["periods"] == 1


@pytest.mark.parametrize(
    "years, frequency, periods", [(1.75, 2, 3), (0.9, 2, 1), (2.5, 4, 10)]
)
def test_genuine_fractional_periods_still_truncate(years, frequency, periods):
    result = B.verify_ytm(1000, 0.05, 999, years, "5%", frequency=frequency)
    assert result.details["periods"] == periods


def test_a_solver_stuck_at_its_bound_is_refused():
    """True yield 0.005 %, below the solver's 0.01 % floor: the solver ran out
    of iterations at the floor and returned it, which verified a 0.0100 %
    claim twice the real yield."""
    result = B.verify_ytm(1000, 0, 999.500131, 10, "0.0100%")
    assert refused(result)
    assert "did not converge" in result.computed_value


@pytest.mark.parametrize(
    "price, coupon, years, frequency",
    [(1050, 0.0, 5, 2), (1200, 0.0, 10, 1), (1500, 0.01, 30, 12)],
)
def test_negative_yield_bonds_are_refused_not_verified_at_the_floor(
    price, coupon, years, frequency
):
    """Priced above par with too little coupon, these yield below zero, which
    the solver cannot reach (#100). The floor value it stopped at must not
    verify."""
    result = B.verify_ytm(1000, coupon, price, years, "0.0100%", frequency=frequency)
    assert refused(result)


def test_half_unit_compares_the_exact_claim():
    """abs() rounds to the context precision; copy_abs() does not."""
    claimed = "$0.004" + "9" * 60
    assert R.verify_var(1_000_000, 0, 0.95, 1, claimed).verified is True


def test_a_refused_half_cent_displays_as_a_cent():
    result = R.verify_var(1_000_000, 0, 0.95, 1, "$0.005")
    assert result.verified is False
    assert result.llm_value == "$0.01"
    assert result.difference == "$0.01"


class _RaisingRepr:
    def __repr__(self):
        raise RuntimeError("no repr")


class _InjectingStr(str):
    def __repr__(self):
        return "ok\n::warning::from a str subclass"


@pytest.mark.parametrize(
    "hostile",
    [
        10**5000,
        _RaisingRepr(),
        type("a\n::warning::class name", (), {})(),
        _InjectingStr("lots\n::x"),
    ],
    ids=[
        "int-past-digit-limit",
        "raising-repr",
        "newline-in-class-name",
        "str-subclass-repr",
    ],
)
@pytest.mark.parametrize(
    "call",
    [
        lambda c: R.verify_var(1_000_000, 0.02, 0.95, 1, c),
        lambda c: R.verify_expected_shortfall(1_000_000, 32900, 45000, c),
        lambda c: B.verify_ytm(1000, 0.05, 950, 10, c),
        lambda c: B.verify_convexity(1000, 0.05, 0.06, 10, c),
    ],
    ids=["var", "es", "ytm", "convexity"],
)
def test_claims_whose_repr_is_caller_code_are_still_refused_safely(call, hostile):
    """repr() of a non-string, or of a str subclass, is caller code: it can
    raise, inject a line break, or be unrepresentable."""
    result = call(hostile)
    assert result.verified is False
    assert result.llm_value.isprintable()
    assert len(result.llm_value) <= 80


@pytest.mark.parametrize(
    "call, claimed",
    [
        # Zero downside deviation: the ratio is undefined.
        (lambda c: R.verify_sortino_ratio(0.1, 0.0, [0.0], c), "9" * 100),
        # A long claim that parses (leading zeros) and overflows the comparison.
        (
            lambda c: R.verify_sortino_ratio(0.1, 0.0, [-0.1, 0.05], c),
            "0" * 90 + "1e999999",
        ),
    ],
    ids=["zero-downside-deviation", "outside-range"],
)
def test_every_sortino_unverifiable_refusal_is_capped(call, claimed):
    result = call(claimed)
    assert result.computed_value.startswith("UNVERIFIABLE")
    assert len(result.llm_value) <= 80


def test_an_overflowing_input_is_not_blamed_on_the_claim():
    result = R.verify_var(1e300, 0.02, 0.95, 1, "$1")
    assert result.computed_value == "UNVERIFIABLE (value outside verifiable range)"


# -- round 3 -------------------------------------------------------------------


@needs_numpy
@pytest.mark.parametrize(
    "call",
    [
        lambda: R.verify_var(np.int64(1_000_000), 0.02, 0.95, 1, "$32,900"),
        lambda: R.verify_var(1_000_000, np.float32(0.02), 0.95, 1, "$32,900"),
        lambda: R.verify_var(1_000_000, np.float64(0.02), 0.95, np.int32(1), "$32,900"),
        lambda: B.verify_ytm(
            1000, 0.05, 950, np.float64(10), "5.66%", frequency=np.int64(2)
        ),
        lambda: B.verify_convexity(
            np.int64(1000), 0.05, 0.06, 10, "71.7854", frequency=np.int8(2)
        ),
    ],
    ids=[
        "int64",
        "float32",
        "float64-and-int32",
        "ytm-int64-frequency",
        "convexity-int8-frequency",
    ],
)
def test_numpy_scalars_are_accepted_as_on_main(call):
    assert call().verified is True


@needs_numpy
@pytest.mark.parametrize(
    "call",
    [
        lambda: R.verify_var(1_000_000, np.bool_(True), 0.95, 1, "$32,900"),
        lambda: B.verify_ytm(1000, 0.05, 950, 10, "5.66%", frequency=np.float64(2.0)),
        lambda: B.verify_ytm(1000, 0.05, 950, 10, "5.66%", frequency=np.bool_(True)),
        lambda: R.verify_var(1_000_000, np.float64("nan"), 0.95, 1, "$32,900"),
    ],
    ids=["bool_", "float-frequency", "bool_-frequency", "nan"],
)
def test_numpy_values_that_are_not_valid_inputs_are_refused(call):
    assert refused(call())


def test_a_yield_found_on_the_last_allowed_step_converges():
    """The candidate the last Newton step produces is priced before the
    solver reports non-convergence."""
    assert (
        BondGuard(max_iterations=3).verify_ytm(1000, 0.05, 950, 10, "5.66%").verified
        is True
    )


def test_a_last_candidate_outside_the_residual_is_still_refused():
    assert refused(BondGuard(max_iterations=2).verify_ytm(1000, 0.05, 950, 10, "5.66%"))


def test_a_tiny_bond_is_held_to_the_same_precision():
    """With an absolute residual of 1e-10, every price of a 1e-12 bond was
    already "converged": the solver stopped at its starting guess, 0, and
    verified a 0 % claim for a bond yielding about 7.05 %."""
    assert B.verify_ytm(1e-12, 0, 5e-13, 10, "0%").verified is False
    assert B.verify_ytm(1e-12, 0, 5e-13, 10, "7.05%").verified is True


@pytest.mark.parametrize(
    "as_percent, as_fraction",
    [
        ("0.00004" + "9" * 60 + "%", "0.0000004" + "9" * 60),  # just under half a unit
        ("0.00005%", "0.0000005"),  # exactly half a unit
        ("0.00005" + "0" * 59 + "1%", "0.0000005" + "0" * 59 + "1"),  # just over
    ],
    ids=["under", "at", "over"],
)
def test_percent_and_fraction_spellings_get_the_same_verdict(as_percent, as_fraction):
    """Dividing by 100 rounded a long percentage onto the bound; the
    exponent is shifted exactly instead."""
    by_percent = B.verify_ytm(1000, 0.0, 1000, 10, as_percent).verified
    by_fraction = B.verify_ytm(1000, 0.0, 1000, 10, as_fraction).verified
    assert by_percent is by_fraction


def test_a_coupon_bond_at_exactly_zero_yield_is_refused_not_misreported():
    """Priced at the sum of its cash flows, this bond yields exactly 0, which
    the solver cannot reach from a positive start past its 0.01 % floor
    (#100). It is refused rather than reported at the floor."""
    assert refused(B.verify_ytm(1000, 0.01, 1050, 5, "0%", frequency=1))


@pytest.mark.parametrize("claimed", ["NaN%", "Infinity%", "-Infinity %", "sNaN%"])
def test_non_finite_percentage_claims_are_refused(claimed):
    assert refused(B.verify_ytm(1000, 0.05, 950, 10, claimed))


# -- round 4: lower-precision NumPy floats ----------------------------------------


@needs_numpy
@pytest.mark.parametrize("dtype", ["float16", "float32", "float64"])
@pytest.mark.parametrize("years, frequency, periods", [(1.75, 2, 3), (0.9, 2, 1)])
def test_numpy_float_fractional_periods_still_truncate(
    dtype, years, frequency, periods
):
    result = B.verify_ytm(
        1000, 0.05, 999, NUMPY_FLOATS[dtype](years), "5%", frequency=frequency
    )
    assert result.details["periods"] == periods


@needs_numpy
def test_an_exact_low_precision_maturity_is_counted():
    """float16 represents 30 exactly, so 360 monthly periods is exact."""
    result = B.verify_ytm(1000, 0.05, 999, np.float16(30), "5%", frequency=12)
    assert result.details["periods"] == 360


@needs_numpy
def test_a_genuine_fraction_of_a_period_is_truncated_not_rounded_up():
    """float16 8.3125 years is exact and 99.75 monthly periods. A tolerance of
    four epsilons rounded it up to 100 and verified the 100-period convexity;
    it is 99 periods, because 100 periods is not this float."""
    years = NUMPY_FLOATS["float16"](8.3125)
    assert (
        B.verify_ytm(1000, 0.05, 999, years, "5%", frequency=12).details["periods"]
        == 99
    )
    assert B.verify_convexity(1000, 0, 0, years, "68.75", frequency=12).verified is True
    assert (
        B.verify_convexity(1000, 0, 0, years, "70.1389", frequency=12).verified is False
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda f: R.verify_var(1_000_000, f, 0.95, 1, "$32,900"),
        lambda f: B.verify_ytm(1000, 0.05, 950, f, "5.66%"),
    ],
    ids=["var", "ytm"],
)
def test_a_fraction_input_is_refused_with_a_clear_reason(call):
    from fractions import Fraction

    result = call(Fraction(3, 2))
    assert refused(result)
    assert "not Fraction" in result.computed_value


# -- round 6: the period count is main's, bounded -------------------------------


def _main_count(years, frequency):
    """main's count: the product in the maturity's own arithmetic, truncated."""
    return int(years * frequency)


@pytest.mark.parametrize(
    "years, frequency",
    [
        (2 / 12, 12),
        (0.57, 100),  # 56 on main and here; the intended 57 is #119
        (1.75, 2),
        (Decimal("0.16666666666666666"), 12),
        (Decimal("2.5"), 4),
        (10, 2),
    ],
)
def test_the_period_count_is_mains(years, frequency):
    result = B.verify_ytm(1000, 0.05, 999, years, "5%", frequency=frequency)
    assert result.details["periods"] == _main_count(years, frequency)


@needs_numpy
@pytest.mark.parametrize(
    "make, frequency",
    [
        (lambda: np.float16(5 / 6), 6),
        (lambda: np.float16(2 / 12), 12),
        (lambda: np.float32(5 / 6), 6),
        (lambda: np.float32(11 / 12), 12),
        (lambda: np.float16(1.02), 1150),
        (lambda: np.longdouble(5) / 12, 12),
    ],
    ids=[
        "f16-5/6",
        "f16-2/12",
        "f32-5/6",
        "f32-11/12",
        "f16-1.02x1150",
        "longdouble-5/12",
    ],
)
def test_the_period_count_is_mains_for_numpy_floats(make, frequency):
    years = make()
    result = B.verify_ytm(1000, 0.05, 999, years, "5%", frequency=frequency)
    expected = _main_count(years, frequency)
    if expected < 1:
        assert refused(result)
    else:
        assert result.details["periods"] == expected


def test_a_computed_maturity_just_under_one_period_is_refused_not_priced_empty():
    """1.4 - 0.9 is 0.4999999999999999: under one semi-annual period. main
    priced an empty sum and verified any convexity; it is refused (#119)."""
    assert refused(B.verify_convexity(1000, 0.05, 0.06, 1.4 - 0.9, "9999"))
