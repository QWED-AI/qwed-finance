"""
Risk Guard - Portfolio risk metrics verification
Deterministic verification for VaR, Beta, Sharpe, and other risk measures
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
from enum import Enum
import math


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


# Z-scores for standard confidence levels
Z_SCORES = {
    0.90: 1.282,
    0.95: 1.645,
    0.99: 2.326
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
    Uses parametric methods for VaR - 100% deterministic.
    """
    
    def __init__(self, tolerance_pct: float = 1.0):
        """
        Initialize the Risk Guard.
        
        Args:
            tolerance_pct: Acceptable % difference for verification
        """
        self.tolerance_pct = tolerance_pct
    
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
        llm_val = self._parse_money(llm_var)
        
        # Get z-score (interpolate if not standard)
        z_score = Z_SCORES.get(confidence_level, self._interpolate_z(confidence_level))
        
        # Parametric VaR formula
        var = Decimal(str(portfolio_value)) * Decimal(str(daily_volatility)) * Decimal(str(z_score)) * Decimal(str(math.sqrt(holding_period_days)))
        computed_var = var.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff_pct = abs(computed_var - llm_val) / computed_var * 100 if computed_var > 0 else 0
        verified = float(diff_pct) <= self.tolerance_pct
        
        return RiskResult(
            verified=verified,
            llm_value=f"${llm_val:,.2f}",
            computed_value=f"${computed_var:,.2f}",
            difference=f"{diff_pct:.2f}%" if not verified else None,
            formula_used="VaR = P × σ × z × √t",
            details={
                "portfolio_value": f"${portfolio_value:,.0f}",
                "daily_volatility": f"{daily_volatility * 100:.2f}%",
                "z_score": z_score,
                "holding_period": f"{holding_period_days} days",
                "confidence": f"{confidence_level * 100:.0f}%"
            }
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
        
        Args:
            asset_returns: List of asset returns
            market_returns: List of market returns (same length)
            llm_beta: LLM's beta answer
            
        Returns:
            RiskResult with verification status
        """
        llm_val = float(llm_beta.strip())
        
        if len(asset_returns) != len(market_returns):
            return RiskResult(
                verified=False,
                llm_value=llm_beta,
                computed_value="ERROR",
                difference="Mismatched return series lengths",
                formula_used="β = Cov(Ra, Rm) / Var(Rm)"
            )
        
        n = len(asset_returns)
        
        # Calculate means
        mean_asset = sum(asset_returns) / n
        mean_market = sum(market_returns) / n
        
        # Calculate covariance and variance
        covariance = sum(
            (asset_returns[i] - mean_asset) * (market_returns[i] - mean_market)
            for i in range(n)
        ) / (n - 1)
        
        variance_market = sum(
            (market_returns[i] - mean_market) ** 2
            for i in range(n)
        ) / (n - 1)
        
        # Beta
        computed_beta = covariance / variance_market if variance_market > 0 else 0
        computed_beta = round(computed_beta, 4)
        
        # Compare
        diff = abs(computed_beta - llm_val)
        verified = diff <= 0.05  # Within 0.05 tolerance
        
        return RiskResult(
            verified=verified,
            llm_value=f"{llm_val:.4f}",
            computed_value=f"{computed_beta:.4f}",
            difference=f"{diff:.4f}" if not verified else None,
            formula_used="β = Cov(Ra, Rm) / Var(Rm)",
            details={
                "observations": n,
                "covariance": f"{covariance:.6f}",
                "market_variance": f"{variance_market:.6f}"
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
        llm_val = float(llm_sharpe.strip())
        
        # Sharpe ratio
        excess_return = portfolio_return - risk_free_rate
        computed_sharpe = excess_return / portfolio_volatility if portfolio_volatility > 0 else 0
        computed_sharpe = round(computed_sharpe, 4)
        
        # Compare
        diff = abs(computed_sharpe - llm_val)
        verified = diff <= 0.05  # Within 0.05 tolerance
        
        return RiskResult(
            verified=verified,
            llm_value=f"{llm_val:.4f}",
            computed_value=f"{computed_sharpe:.4f}",
            difference=f"{diff:.4f}" if not verified else None,
            formula_used="Sharpe = (Rp - Rf) / σp",
            details={
                "portfolio_return": f"{portfolio_return * 100:.2f}%",
                "risk_free_rate": f"{risk_free_rate * 100:.2f}%",
                "excess_return": f"{excess_return * 100:.2f}%",
                "volatility": f"{portfolio_volatility * 100:.2f}%"
            }
        )
    
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
        llm_val = float(llm_sortino.strip())
        
        if not downside_returns:
            # No downside returns = infinite Sortino (perfect)
            return RiskResult(
                verified=True,
                llm_value=llm_sortino,
                computed_value="∞ (no downside)",
                formula_used="Sortino = (Rp - Rt) / σ_downside"
            )
        
        # Calculate downside deviation
        n = len(downside_returns)
        downside_squared = sum(
            (r - target_return) ** 2 for r in downside_returns if r < target_return
        )
        downside_deviation = math.sqrt(downside_squared / n) if n > 0 else 0
        
        # Sortino ratio
        excess_return = portfolio_return - target_return
        computed_sortino = excess_return / downside_deviation if downside_deviation > 0 else float('inf')
        
        if math.isinf(computed_sortino):
            verified = llm_val > 10  # High LLM value expected for near-infinite
            return RiskResult(
                verified=verified,
                llm_value=f"{llm_val:.4f}",
                computed_value="Very High (low downside)",
                formula_used="Sortino = (Rp - Rt) / σ_downside"
            )
        
        computed_sortino = round(computed_sortino, 4)
        
        # Compare
        diff = abs(computed_sortino - llm_val)
        verified = diff <= 0.1  # Within 0.1 tolerance
        
        return RiskResult(
            verified=verified,
            llm_value=f"{llm_val:.4f}",
            computed_value=f"{computed_sortino:.4f}",
            difference=f"{diff:.4f}" if not verified else None,
            formula_used="Sortino = (Rp - Rt) / σ_downside",
            details={
                "downside_deviation": f"{downside_deviation * 100:.4f}%",
                "observations_below_target": n
            }
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
        llm_val = abs(float(llm_max_dd.replace("%", "").strip())) / 100
        
        # Calculate max drawdown
        peak = portfolio_values[0]
        max_drawdown = 0
        
        for value in portfolio_values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        computed_dd = round(max_drawdown, 6)
        
        # Compare
        diff = abs(computed_dd - llm_val)
        verified = diff <= 0.005  # Within 0.5% tolerance
        
        return RiskResult(
            verified=verified,
            llm_value=f"-{llm_val * 100:.2f}%",
            computed_value=f"-{computed_dd * 100:.2f}%",
            difference=f"{diff * 100:.2f}%" if not verified else None,
            formula_used="Max DD = max((Peak - Trough) / Peak)",
            details={
                "observations": len(portfolio_values),
                "peak_value": f"${max(portfolio_values):,.2f}"
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
        llm_val = self._parse_money(llm_es)
        
        # ES is simply the average of tail losses
        computed_es = Decimal(str(tail_loss_avg))
        computed_es = computed_es.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff_pct = abs(computed_es - llm_val) / computed_es * 100 if computed_es > 0 else 0
        verified = float(diff_pct) <= self.tolerance_pct
        
        return RiskResult(
            verified=verified,
            llm_value=f"${llm_val:,.2f}",
            computed_value=f"${computed_es:,.2f}",
            difference=f"{diff_pct:.2f}%" if not verified else None,
            formula_used="ES = E[Loss | Loss > VaR]",
            details={
                "VaR": f"${var_amount:,.2f}",
                "ES_to_VaR_ratio": f"{float(computed_es) / var_amount:.2f}x" if var_amount > 0 else "N/A"
            }
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
        llm_val = float(llm_ir.strip())
        
        # Information ratio
        active_return = portfolio_return - benchmark_return
        computed_ir = active_return / tracking_error if tracking_error > 0 else 0
        computed_ir = round(computed_ir, 4)
        
        # Compare
        diff = abs(computed_ir - llm_val)
        verified = diff <= 0.05
        
        return RiskResult(
            verified=verified,
            llm_value=f"{llm_val:.4f}",
            computed_value=f"{computed_ir:.4f}",
            difference=f"{diff:.4f}" if not verified else None,
            formula_used="IR = (Rp - Rb) / TE",
            details={
                "active_return": f"{active_return * 100:.2f}%",
                "tracking_error": f"{tracking_error * 100:.2f}%"
            }
        )
    
    def _interpolate_z(self, confidence: float) -> float:
        """Interpolate z-score for non-standard confidence levels"""
        # Linear interpolation between known z-scores
        if confidence <= 0.90:
            return Z_SCORES[0.90]
        elif confidence <= 0.95:
            return Z_SCORES[0.90] + (confidence - 0.90) / 0.05 * (Z_SCORES[0.95] - Z_SCORES[0.90])
        elif confidence <= 0.99:
            return Z_SCORES[0.95] + (confidence - 0.95) / 0.04 * (Z_SCORES[0.99] - Z_SCORES[0.95])
        else:
            return Z_SCORES[0.99]
    
    def _parse_money(self, value: str) -> Decimal:
        """Parse money string to Decimal"""
        import re
        cleaned = re.sub(r'[,$]', '', str(value).strip())
        return Decimal(cleaned)
