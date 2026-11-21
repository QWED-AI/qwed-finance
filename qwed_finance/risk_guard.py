"""
Risk Guard - Portfolio risk metrics verification
Deterministic verification for VaR, Beta, Sharpe, and other risk measures

All financial math uses Decimal for exact arithmetic.
"""

from dataclasses import dataclass
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP, getcontext
from typing import Any, List, Optional
from enum import Enum

from ._numeric import UnverifiableError, claim, number, shown, within_tolerance

# Set precision high enough for statistical calculations
getcontext().prec = 50


class VaRMethod(Enum):
    """VaR calculation methods"""
    PARAMETRIC = "parametric"      # Variance-covariance
    HISTORICAL = "historical"       # Historical simulation
    MONTE_CARLO = "monte_carlo"    # Monte Carlo simulation


class ConfidenceLevel(Enum):
    """Standard VaR confidence levels"""
    NINETY = 0.90
    NINETY_FIVE = 0.95
    NINETY_NINE = 0.99


_ZERO = Decimal("0")

# Z-scores for standard confidence levels (stored as Decimal strings)
Z_SCORES = {
    0.90: Decimal("1.282"),
    0.95: Decimal("1.645"),
    0.99: Decimal("2.326")
}


@dataclass
class RiskResult:
    """Result of a risk verification"""
    verified: bool
    llm_value: Optional[str]
    computed_value: str
    difference: Optional[str] = None
    formula_used: Optional[str] = None
    confidence: str = "SYMBOLIC_PROOF"
    details: Optional[dict] = None


class RiskGuard:
    """
    Deterministic verification for portfolio risk metrics.
    Uses parametric methods for VaR — 100% deterministic.

    All internal math uses Decimal for exact arithmetic,
    following the TradingGuard gold standard.
    """
    
    VAR_FORMULA = "VaR = P × σ × z × √t"
    ES_FORMULA = "ES = E[Loss | Loss > VaR]"

    def __init__(self, tolerance_pct: float = 1.0):
        """
        Initialize the Risk Guard.
        
        Args:
            tolerance_pct: Acceptable % difference for verification
        """
        self.tolerance_pct = Decimal(str(tolerance_pct))
    
    def verify_var(
        self,
        portfolio_value: float,
        daily_volatility: float,
        confidence_level: float,
        holding_period_days: int,
        llm_var: str
    ) -> RiskResult:
        """
        Verify Parametric Value at Risk calculation.
        
        VaR = Portfolio × σ × z × √t
        
        Where:
        - σ = daily volatility (standard deviation)
        - z = z-score for confidence level
        - t = holding period in days
        
        Args:
            portfolio_value: Total portfolio value
            daily_volatility: Daily volatility (e.g., 0.02 for 2%)
            confidence_level: Confidence level (0.95, 0.99, etc.)
            holding_period_days: Holding period in days
            llm_var: LLM's VaR answer
            
        Returns:
            RiskResult with verification status
        """
        try:
            llm_val = claim(self._parse_money, llm_var)
            # A negative portfolio or volatility gives a negative "VaR", and a
            # non-positive holding period a zero or undefined one; none is a
            # value at risk the formula defines (#98).
            portfolio = number(portfolio_value, "portfolio_value", minimum=_ZERO)
            volatility = number(daily_volatility, "daily_volatility", minimum=_ZERO)
            confidence = number(
                confidence_level, "confidence_level", minimum=_ZERO, exclusive=True
            )
            if confidence >= 1:
                raise UnverifiableError("confidence_level must be < 1")
            holding_d = number(
                holding_period_days, "holding_period_days", minimum=_ZERO, exclusive=True
            )

            # Get z-score (interpolate if not standard)
            z_score = Z_SCORES.get(confidence_level, self._interpolate_z(confidence_level))

            # Parametric VaR formula — fully Decimal
            # Use Decimal.sqrt() instead of math.sqrt() to avoid float leak
            sqrt_holding = holding_d.sqrt()

            var = portfolio * volatility * z_score * sqrt_holding
            computed_var = var.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Compare
            verified, diff_pct = within_tolerance(
                computed_var, llm_val, self.tolerance_pct, Decimal("0.01")
            )

            return RiskResult(
                verified=verified,
                llm_value=f"${self._cents(llm_val):,.2f}",
                computed_value=f"${computed_var:,.2f}",
                difference=self._difference(diff_pct, computed_var, llm_val, verified),
                formula_used=self.VAR_FORMULA,
                details={
                    "portfolio_value": f"${portfolio:,.0f}",
                    "daily_volatility": f"{volatility * 100}%",
                    "z_score": str(z_score),
                    "holding_period": f"{holding_period_days} days",
                    "confidence": f"{confidence * 100}%"
                }
            )
        except UnverifiableError as reason:
            return self._unverifiable(llm_var, reason, self.VAR_FORMULA)
        except DecimalException:
            return self._unverifiable(
                llm_var, "value outside verifiable range", self.VAR_FORMULA
            )
    
    def verify_beta(
        self,
        asset_returns: List[float],
        market_returns: List[float],
        llm_beta: str
    ) -> RiskResult:
        """
        Verify Portfolio Beta calculation.
        
        β = Cov(r_asset, r_market) / Var(r_market)
        
        Beta measures systematic risk relative to the market.
        Uses Decimal to prevent catastrophic cancellation when
        returns are close to their mean.
        
        Args:
            asset_returns: List of asset returns
            market_returns: List of market returns (same length)
            llm_beta: LLM's beta answer
            
        Returns:
            RiskResult with verification status
        """
        llm_val = Decimal(llm_beta.strip())
        
        if len(asset_returns) != len(market_returns):
            return RiskResult(
                verified=False,
                llm_value=llm_beta,
                computed_value="ERROR",
                difference="Mismatched return series lengths",
                formula_used="β = Cov(Ra, Rm) / Var(Rm)"
            )
        
        n = len(asset_returns)
        
        # Convert to Decimal for exact accumulation
        asset_d = [Decimal(str(r)) for r in asset_returns]
        market_d = [Decimal(str(r)) for r in market_returns]
        n_d = Decimal(str(n))
        
        # Calculate means
        mean_asset = sum(asset_d) / n_d
        mean_market = sum(market_d) / n_d
        
        # Calculate covariance and variance using Decimal
        # This prevents catastrophic cancellation when returns ≈ mean
        covariance = sum(
            (asset_d[i] - mean_asset) * (market_d[i] - mean_market)
            for i in range(n)
        ) / (n_d - 1)
        
        variance_market = sum(
            (market_d[i] - mean_market) ** 2
            for i in range(n)
        ) / (n_d - 1)
        
        # Beta
        if variance_market > 0:
            computed_beta = covariance / variance_market
        else:
            computed_beta = Decimal("0")
        computed_beta_q = computed_beta.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed_beta_q - llm_val)
        verified = diff <= Decimal("0.05")  # Within 0.05 tolerance
        
        return RiskResult(
            verified=verified,
            llm_value=f"{llm_val}",
            computed_value=f"{computed_beta_q}",
            difference=f"{diff.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="β = Cov(Ra, Rm) / Var(Rm)",
            details={
                "observations": n,
                "covariance": str(covariance.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
                "market_variance": str(variance_market.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
            }
        )
    
    def verify_sharpe_ratio(
        self,
        portfolio_return: float,
        risk_free_rate: float,
        portfolio_volatility: float,
        llm_sharpe: str,
        annualized: bool = True
    ) -> RiskResult:
        """
        Verify Sharpe Ratio calculation.
        
        Sharpe = (R_p - R_f) / σ_p
        
        Args:
            portfolio_return: Portfolio return (annual or period)
            risk_free_rate: Risk-free rate (same period as return)
            portfolio_volatility: Standard deviation of returns
            llm_sharpe: LLM's Sharpe ratio answer
            annualized: Whether inputs are already annualized
            
        Returns:
            RiskResult with verification status
        """
        llm_val = Decimal(llm_sharpe.strip())
        
        # Convert to Decimal
        rp = Decimal(str(portfolio_return))
        rf = Decimal(str(risk_free_rate))
        vol = Decimal(str(portfolio_volatility))
        
        # Sharpe ratio
        excess_return = rp - rf
        if vol > 0:
            computed_sharpe = excess_return / vol
        else:
            computed_sharpe = Decimal("0")
        computed_sharpe_q = computed_sharpe.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed_sharpe_q - llm_val)
        verified = diff <= Decimal("0.05")  # Within 0.05 tolerance
        
        return RiskResult(
            verified=verified,
            llm_value=f"{llm_val}",
            computed_value=f"{computed_sharpe_q}",
            difference=f"{diff.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="Sharpe = (Rp - Rf) / σp",
            details={
                "portfolio_return": f"{rp * 100}%",
                "risk_free_rate": f"{rf * 100}%",
                "excess_return": f"{excess_return * 100}%",
                "volatility": f"{vol * 100}%"
            }
        )
    
    #: Canonical formula label for Sortino verdicts.
    SORTINO_FORMULA = "Sortino = (Rp - Rt) / downside_deviation"

    def verify_sortino_ratio(
        self,
        portfolio_return: float,
        target_return: float,
        downside_returns: List[float],
        llm_sortino: str
    ) -> RiskResult:
        """
        Verify Sortino Ratio calculation.
        
        Sortino = (R_p - R_target) / σ_downside
        
        Only considers downside volatility (returns below target).
        
        Args:
            portfolio_return: Portfolio return
            target_return: Target/minimum acceptable return (often risk-free)
            downside_returns: List of returns BELOW target (for downside deviation)
            llm_sortino: LLM's Sortino ratio answer
            
        Returns:
            RiskResult with verification status
        """
        try:
            llm_val = Decimal(llm_sortino.strip())
        except (InvalidOperation, AttributeError, ValueError):
            # Fail closed: an unparseable claim cannot be verified, and a
            # verifier must never raise on caller input.
            return RiskResult(
                verified=False,
                llm_value=shown(llm_sortino),
                computed_value="UNVERIFIABLE (unparseable claim)",
                formula_used=self.SORTINO_FORMULA
            )
        if not llm_val.is_finite():
            # Decimal accepts NaN/sNaN/Infinity at parse time; each would
            # crash the comparison or formatting below with InvalidOperation
            # instead of verdicting. Reject up front (Greptile P1).
            return RiskResult(
                verified=False,
                llm_value=shown(llm_sortino),
                computed_value="UNVERIFIABLE (non-finite claim)",
                formula_used=self.SORTINO_FORMULA
            )

        if not downside_returns:
            # No downside observations: there is no recomputation to compare
            # the claim against, so no claim can verify (#43). An "infinite"
            # Sortino here would endorse literally any number.
            return RiskResult(
                verified=False,
                llm_value=shown(llm_sortino),
                computed_value="UNVERIFIABLE (no downside observations)",
                formula_used=self.SORTINO_FORMULA
            )
        
        # Convert to Decimal
        rp = Decimal(str(portfolio_return))
        rt = Decimal(str(target_return))
        downside_d = [Decimal(str(r)) for r in downside_returns]
        n = len(downside_returns)
        n_d = Decimal(str(n))
        
        # Calculate downside deviation using Decimal
        downside_squared = sum(
            (r - rt) ** 2 for r in downside_d if r < rt
        )
        if n > 0 and downside_squared > 0:
            downside_deviation = (downside_squared / n_d).sqrt()
        else:
            downside_deviation = Decimal("0")
        
        # Sortino ratio
        excess_return = rp - rt
        if downside_deviation > 0:
            computed_sortino = excess_return / downside_deviation
        else:
            # Zero downside deviation makes the ratio undefined: no claim
            # can verify against it. The old `llm_val > 10` heuristic
            # endorsed any large number without recomputation (#43).
            return RiskResult(
                verified=False,
                llm_value=shown(llm_sortino),
                computed_value="UNVERIFIABLE (zero downside deviation)",
                formula_used=self.SORTINO_FORMULA
            )
        
        try:
            computed_sortino_q = computed_sortino.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

            # Compare
            diff = abs(computed_sortino_q - llm_val)
            verified = diff <= Decimal("0.1")  # Within 0.1 tolerance

            return RiskResult(
                verified=verified,
                llm_value=f"{llm_val}",
                computed_value=f"{computed_sortino_q}",
                difference=f"{diff.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}" if not verified else None,
                formula_used=self.SORTINO_FORMULA,
                details={
                    "downside_deviation": f"{(downside_deviation * 100).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}%",
                    "observations_below_target": n
                }
            )
        except DecimalException:
            # Extreme finite claims (e.g. 1e999999) overflow the Decimal
            # context during comparison/formatting: verdict, never raise.
            return RiskResult(
                verified=False,
                llm_value=shown(llm_sortino),
                computed_value="UNVERIFIABLE (claim outside verifiable range)",
                formula_used=self.SORTINO_FORMULA
            )
    
    def verify_max_drawdown(
        self,
        portfolio_values: List[float],
        llm_max_dd: str
    ) -> RiskResult:
        """
        Verify Maximum Drawdown calculation.
        
        Max Drawdown = (Peak - Trough) / Peak
        
        Args:
            portfolio_values: Time series of portfolio values
            llm_max_dd: LLM's max drawdown answer (e.g., "-15%" or "15%")
            
        Returns:
            RiskResult with verification status
        """
        # Parse LLM's value (handle negative sign)
        llm_val = abs(Decimal(llm_max_dd.replace("%", "").strip())) / 100
        
        # Convert to Decimal
        values_d = [Decimal(str(v)) for v in portfolio_values]
        
        # Calculate max drawdown using Decimal
        peak = values_d[0]
        max_drawdown = Decimal("0")
        
        for value in values_d:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        computed_dd = max_drawdown.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed_dd - llm_val)
        verified = diff <= Decimal("0.005")  # Within 0.5% tolerance
        
        return RiskResult(
            verified=verified,
            llm_value=f"-{(llm_val * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%",
            computed_value=f"-{(computed_dd * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%",
            difference=f"{(diff * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%" if not verified else None,
            formula_used="Max DD = max((Peak - Trough) / Peak)",
            details={
                "observations": len(portfolio_values),
                "peak_value": f"${max(values_d):,.2f}"
            }
        )
    
    def verify_expected_shortfall(
        self,
        portfolio_value: float,
        var_amount: float,
        tail_loss_avg: float,
        llm_es: str
    ) -> RiskResult:
        """
        Verify Expected Shortfall (CVaR) calculation.
        
        ES = E[Loss | Loss > VaR]
        
        Expected Shortfall is the average loss beyond VaR.
        
        Args:
            portfolio_value: Total portfolio value
            var_amount: VaR amount
            tail_loss_avg: Average loss in the tail (beyond VaR)
            llm_es: LLM's Expected Shortfall answer
            
        Returns:
            RiskResult with verification status
        """
        try:
            llm_val = claim(self._parse_money, llm_es)
            # Losses are positive amounts here, as verify_var reports VaR; a
            # negative average tail "loss" is a gain this formula does not
            # cover (#98).
            number(portfolio_value, "portfolio_value", minimum=_ZERO)
            computed_es = number(tail_loss_avg, "tail_loss_avg", minimum=_ZERO)
            var_d = number(var_amount, "var_amount", minimum=_ZERO)
            if computed_es < var_d:
                # The tail average is taken over losses beyond VaR, so it
                # cannot be below VaR; such inputs describe no distribution.
                raise UnverifiableError("tail_loss_avg must be >= var_amount")

            # ES is simply the average of tail losses
            computed_es = computed_es.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Compare
            verified, diff_pct = within_tolerance(
                computed_es, llm_val, self.tolerance_pct, Decimal("0.01")
            )

            es_to_var = computed_es / var_d if var_d > 0 else Decimal("0")

            return RiskResult(
                verified=verified,
                llm_value=f"${self._cents(llm_val):,.2f}",
                computed_value=f"${computed_es:,.2f}",
                difference=self._difference(diff_pct, computed_es, llm_val, verified),
                formula_used=self.ES_FORMULA,
                details={
                    "VaR": f"${var_d:,.2f}",
                    "ES_to_VaR_ratio": f"{es_to_var.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}x"
                }
            )
        except UnverifiableError as reason:
            return self._unverifiable(llm_es, reason, self.ES_FORMULA)
        except DecimalException:
            return self._unverifiable(
                llm_es, "value outside verifiable range", self.ES_FORMULA
            )
    
    def verify_information_ratio(
        self,
        portfolio_return: float,
        benchmark_return: float,
        tracking_error: float,
        llm_ir: str
    ) -> RiskResult:
        """
        Verify Information Ratio calculation.
        
        IR = (R_p - R_b) / Tracking Error
        
        Measures risk-adjusted return relative to benchmark.
        
        Args:
            portfolio_return: Portfolio return
            benchmark_return: Benchmark return
            tracking_error: Standard deviation of excess returns
            llm_ir: LLM's Information Ratio answer
            
        Returns:
            RiskResult with verification status
        """
        llm_val = Decimal(llm_ir.strip())
        
        # Convert to Decimal
        rp = Decimal(str(portfolio_return))
        rb = Decimal(str(benchmark_return))
        te = Decimal(str(tracking_error))
        
        # Information ratio
        active_return = rp - rb
        if te > 0:
            computed_ir = active_return / te
        else:
            computed_ir = Decimal("0")
        computed_ir_q = computed_ir.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed_ir_q - llm_val)
        verified = diff <= Decimal("0.05")
        
        return RiskResult(
            verified=verified,
            llm_value=f"{llm_val}",
            computed_value=f"{computed_ir_q}",
            difference=f"{diff.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="IR = (Rp - Rb) / TE",
            details={
                "active_return": f"{(active_return * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%",
                "tracking_error": f"{(te * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"
            }
        )
    
    @staticmethod
    def _cents(value: Decimal) -> Decimal:
        """Round a money amount half up to cents for display."""
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _unverifiable(raw_claim: Any, reason: Any, formula: str) -> RiskResult:
        """A verdict for an input or claim the guard cannot verify (#98)."""
        return RiskResult(
            verified=False,
            llm_value=shown(raw_claim),
            computed_value=f"UNVERIFIABLE ({reason})",
            formula_used=formula,
        )

    @staticmethod
    def _difference(
        diff_pct: Optional[Decimal],
        computed: Decimal,
        claimed: Decimal,
        verified: bool,
    ) -> Optional[str]:
        """How far a refused monetary claim is from the computed value.

        A relative difference when the computed value is non-zero; the
        absolute amount when it is zero, where a percentage has no scale.
        """
        if verified:
            return None
        if diff_pct is None:
            return f"${RiskGuard._cents(abs(claimed - computed)):,.2f}"
        return f"{diff_pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"

    def _interpolate_z(self, confidence: float) -> Decimal:
        """Interpolate z-score for non-standard confidence levels"""
        c = Decimal(str(confidence))
        if c <= Decimal("0.90"):
            return Z_SCORES[0.90]
        elif c <= Decimal("0.95"):
            return Z_SCORES[0.90] + (c - Decimal("0.90")) / Decimal("0.05") * (Z_SCORES[0.95] - Z_SCORES[0.90])
        elif c <= Decimal("0.99"):
            return Z_SCORES[0.95] + (c - Decimal("0.95")) / Decimal("0.04") * (Z_SCORES[0.99] - Z_SCORES[0.95])
        else:
            return Z_SCORES[0.99]
    
    def _parse_money(self, value: str) -> Decimal:
        """Parse money string to Decimal"""
        import re
        cleaned = re.sub(r'[,$]', '', str(value).strip())
        return Decimal(cleaned)
