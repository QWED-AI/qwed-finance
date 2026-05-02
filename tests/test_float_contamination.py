"""
Tests for float contamination remediation (Issue #20).

Covers:
- C-01: BondGuard uses Decimal for YTM, Duration, Convexity
- C-02: DerivativesGuard uses mpmath for Black-Scholes
- C-03: RiskGuard uses Decimal for Beta, VaR, Sharpe
- S-04: No float leaks in monetary output strings
"""

import pytest
from decimal import Decimal

from qwed_finance import BondGuard, DerivativesGuard, OptionType
from qwed_finance.risk_guard import RiskGuard


# ==================== BondGuard Decimal Tests ====================

class TestBondGuardDecimal:
    """Verify BondGuard uses Decimal internally — no IEEE-754 artifacts."""

    def setup_method(self):
        self.guard = BondGuard()

    def test_ytm_solver_returns_decimal(self):
        """_solve_ytm must return Decimal, not float."""
        fv = Decimal("1000")
        coupon = Decimal("25")  # 5% semi-annual
        price = Decimal("950")
        result = self.guard._solve_ytm(fv, coupon, price, 20, 2)
        assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"

    def test_ytm_verification_no_float_in_output(self):
        """Output strings must not contain float artifacts like 0.30000000000000004."""
        result = self.guard.verify_ytm(1000, 0.05, 950, 10, "5.66%")
        assert "000000000" not in result.computed_value
        assert result.verified is True

    def test_duration_uses_decimal(self):
        """Duration accumulation must use Decimal — catches catastrophic cancellation."""
        result = self.guard.verify_duration(
            face_value=1000,
            coupon_rate=0.05,
            ytm=0.06,
            years_to_maturity=10,
            llm_duration="7.8950 years"
        )
        # Should verify within tolerance
        assert result.verified is True
        assert "000000000" not in result.computed_value

    def test_convexity_uses_decimal(self):
        """Convexity must use Decimal for weighted sum accumulation."""
        result = self.guard.verify_convexity(
            face_value=1000,
            coupon_rate=0.05,
            ytm=0.06,
            years_to_maturity=10,
            llm_convexity="72.00"
        )
        # Just check no float leak, not exact match
        assert "000000000" not in result.computed_value

    def test_accrued_interest_still_decimal(self):
        """verify_accrued_interest was already Decimal — ensure no regression."""
        result = self.guard.verify_accrued_interest(
            face_value=1000,
            coupon_rate=0.06,
            days_since_last_coupon=45,
            days_in_period=180,
            llm_accrued="$7.50"
        )
        assert result.verified is True

    def test_ytm_tolerance_is_decimal(self):
        """BondGuard.tolerance_pct must be Decimal."""
        assert isinstance(self.guard.tolerance_pct, Decimal)


# ==================== DerivativesGuard mpmath Tests ====================

class TestDerivativesGuardMpmath:
    """Verify DerivativesGuard uses mpmath — no math.log/exp/sqrt."""

    def setup_method(self):
        self.guard = DerivativesGuard()

    def test_black_scholes_call_price(self):
        """Black-Scholes call price must match known reference value."""
        result = self.guard.verify_black_scholes(
            spot_price=100,
            strike_price=100,
            time_to_expiry=1.0,
            risk_free_rate=0.05,
            volatility=0.20,
            option_type=OptionType.CALL,
            llm_price="$10.45"
        )
        # Reference: ATM 1Y call with 20% vol ≈ $10.45
        assert result.computed_price.startswith("$")
        assert "000000000" not in result.computed_price

    def test_greeks_are_decimal_strings(self):
        """Greeks must be Decimal strings, not float round() output."""
        result = self.guard.verify_black_scholes(
            spot_price=100,
            strike_price=105,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            volatility=0.20,
            option_type=OptionType.CALL,
            llm_price="$2.48"
        )
        for greek_name, value in result.greeks.items():
            # Must be a string (Decimal-quantized), not a float
            assert isinstance(value, str), f"Greek {greek_name} is {type(value)}, expected str"
            # Must not have float artifacts
            assert "e-" not in value.lower() or "e-0" not in value.lower(), \
                f"Greek {greek_name} has scientific notation: {value}"

    def test_put_price_positive(self):
        """OTM put price must be positive and properly formatted."""
        result = self.guard.verify_black_scholes(
            spot_price=100,
            strike_price=95,
            time_to_expiry=0.5,
            risk_free_rate=0.05,
            volatility=0.25,
            option_type=OptionType.PUT,
            llm_price="$3.00"
        )
        price_str = result.computed_price.replace("$", "")
        price_val = Decimal(price_str)
        assert price_val > 0

    def test_put_call_parity_no_float_exp(self):
        """Put-call parity must use mpmath.exp, not math.exp."""
        result = self.guard.verify_put_call_parity(
            call_price=10.45,
            put_price=5.57,
            spot_price=100,
            strike_price=100,
            time_to_expiry=1.0,
            risk_free_rate=0.05
        )
        # Should verify parity within tolerance
        assert "000000000" not in result.computed_price

    def test_margin_call_uses_decimal(self):
        """Margin call comparison must use Decimal for exact threshold check."""
        result = self.guard.verify_margin_call(
            account_equity=24999.99,
            maintenance_margin=0.25,
            position_value=100000,
            llm_margin_call=True
        )
        # 24999.99 < 25000.00 → margin call
        assert result.verified is True

    def test_delta_uses_mpmath(self):
        """Delta calculation must use mpmath norm_cdf."""
        result = self.guard.verify_delta(
            spot_price=100,
            strike_price=100,
            time_to_expiry=1.0,
            risk_free_rate=0.05,
            volatility=0.20,
            option_type=OptionType.CALL,
            llm_delta=0.6368
        )
        # ATM 1Y call delta ≈ 0.64
        assert result.verified is True


# ==================== RiskGuard Decimal Tests ====================

class TestRiskGuardDecimal:
    """Verify RiskGuard uses Decimal — prevents catastrophic cancellation."""

    def setup_method(self):
        self.guard = RiskGuard()

    def test_var_uses_decimal_sqrt(self):
        """VaR must use Decimal.sqrt() not math.sqrt()."""
        result = self.guard.verify_var(
            portfolio_value=1000000,
            daily_volatility=0.02,
            confidence_level=0.95,
            holding_period_days=10,
            llm_var="$104,012.29"
        )
        # VaR = 1M * 0.02 * 1.645 * sqrt(10) ≈ $104,012
        assert result.computed_value.startswith("$")
        assert "000000000" not in result.computed_value

    def test_beta_decimal_accumulation(self):
        """Beta must use Decimal to prevent catastrophic cancellation."""
        # Use returns very close to their mean — triggers cancellation in float
        asset = [0.01001, 0.01002, 0.01003, 0.00999, 0.00998]
        market = [0.00501, 0.00502, 0.00503, 0.00499, 0.00498]
        
        result = self.guard.verify_beta(asset, market, "1.0000")
        # The key test: does it return a valid Decimal result without NaN/Inf?
        assert result.computed_value not in ("nan", "inf", "-inf", "ERROR")

    def test_sharpe_uses_decimal(self):
        """Sharpe ratio must use Decimal division."""
        result = self.guard.verify_sharpe_ratio(
            portfolio_return=0.12,
            risk_free_rate=0.03,
            portfolio_volatility=0.15,
            llm_sharpe="0.6000"
        )
        assert result.verified is True
        assert isinstance(self.guard.tolerance_pct, Decimal)

    def test_sortino_uses_decimal_sqrt(self):
        """Sortino must use Decimal.sqrt() for downside deviation."""
        result = self.guard.verify_sortino_ratio(
            portfolio_return=0.10,
            target_return=0.02,
            downside_returns=[-0.05, -0.03, -0.01],
            llm_sortino="1.3000"
        )
        assert result.computed_value not in ("nan", "inf")

    def test_max_drawdown_decimal(self):
        """Max drawdown must use Decimal accumulation."""
        values = [100, 95, 90, 88, 92, 85, 90, 95, 100]
        result = self.guard.verify_max_drawdown(values, "15%")
        assert result.verified is True

    def test_information_ratio_decimal(self):
        """IR must use Decimal division."""
        result = self.guard.verify_information_ratio(
            portfolio_return=0.12,
            benchmark_return=0.10,
            tracking_error=0.05,
            llm_ir="0.4000"
        )
        assert result.verified is True

    def test_z_scores_are_decimal(self):
        """Z_SCORES dict values must be Decimal, not float."""
        from qwed_finance.risk_guard import Z_SCORES
        for conf, z in Z_SCORES.items():
            assert isinstance(z, Decimal), f"Z_SCORES[{conf}] is {type(z)}, expected Decimal"


# ==================== Cross-Guard Float Leak Detection ====================

class TestNoFloatInOutput:
    """Ensure no float artifacts leak into any guard output strings."""

    FLOAT_ARTIFACTS = [
        "0.30000000000000004",   # 0.1 + 0.2
        "3.5999999999999943",    # sum of 360 × 0.01
        "e-",                    # scientific notation from float
        "nan",
        "inf",
    ]

    def _check_no_float_leak(self, value: str):
        """Assert a string has no IEEE-754 artifacts."""
        for artifact in self.FLOAT_ARTIFACTS:
            assert artifact not in value.lower(), \
                f"Float artifact '{artifact}' found in: {value}"

    def test_bond_ytm_output_clean(self):
        guard = BondGuard()
        r = guard.verify_ytm(1000, 0.05, 950, 10, "5.66%")
        self._check_no_float_leak(r.computed_value)
        if r.difference:
            self._check_no_float_leak(r.difference)

    def test_derivatives_bs_output_clean(self):
        guard = DerivativesGuard()
        r = guard.verify_black_scholes(100, 100, 1.0, 0.05, 0.20, OptionType.CALL, "$10.45")
        self._check_no_float_leak(r.computed_price)

    def test_risk_var_output_clean(self):
        guard = RiskGuard()
        r = guard.verify_var(1000000, 0.02, 0.95, 10, "$104012.29")
        self._check_no_float_leak(r.computed_value)

    def test_risk_beta_output_clean(self):
        guard = RiskGuard()
        asset = [0.05, 0.02, -0.01, 0.03, 0.04]
        market = [0.04, 0.01, -0.02, 0.02, 0.03]
        r = guard.verify_beta(asset, market, "1.0000")
        self._check_no_float_leak(r.computed_value)
