"""
Derivatives Guard - Black-Scholes options pricing and margin verification
Deterministic verification for derivatives trading

Uses mpmath for arbitrary-precision transcendental functions (log, exp, sqrt, erf).
All monetary outputs use Decimal for exact representation.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Optional, Tuple
from enum import Enum
import mpmath

# Set precision for both Decimal and mpmath
getcontext().prec = 50
mpmath.mp.dps = 30  # 30 decimal places for mpmath


class OptionType(Enum):
    CALL = "call"
    PUT = "put"


@dataclass
class DerivativesResult:
    """Result of a derivatives verification"""
    verified: bool
    llm_price: Optional[str]
    computed_price: str
    difference: Optional[str] = None
    greeks: Optional[dict] = None
    formula_used: Optional[str] = None
    margin_status: Optional[str] = None


class DerivativesGuard:
    """
    Deterministic verification for derivatives pricing.
    Uses Black-Scholes formula with mpmath for arbitrary-precision
    transcendental functions (log, exp, sqrt, erf).

    All monetary outputs are quantized via Decimal for exact representation.
    """
    
    def __init__(self, tolerance_pct: float = 1.0):
        """
        Initialize the Derivatives Guard.
        
        Args:
            tolerance_pct: Acceptable % difference for price verification
        """
        self.tolerance_pct = Decimal(str(tolerance_pct))
        self._sympy_available = self._check_sympy()
    
    def _check_sympy(self) -> bool:
        """Check if SymPy is available"""
        try:
            import sympy
            return True
        except ImportError:
            return False
    
    # ==================== Black-Scholes ====================
    
    def verify_black_scholes(
        self,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        risk_free_rate: float,
        volatility: float,
        option_type: OptionType,
        llm_price: str
    ) -> DerivativesResult:
        """
        Verify Black-Scholes option price calculation.
        
        C = S*N(d1) - K*e^(-rT)*N(d2)  [Call]
        P = K*e^(-rT)*N(-d2) - S*N(-d1) [Put]
        
        Where:
        d1 = (ln(S/K) + (r + σ²/2)*T) / (σ*√T)
        d2 = d1 - σ*√T
        
        Uses mpmath for arbitrary-precision transcendental functions.
        
        Args:
            spot_price: Current price of underlying (S)
            strike_price: Strike price (K)
            time_to_expiry: Time to expiry in years (T)
            risk_free_rate: Risk-free interest rate (r)
            volatility: Implied volatility (σ)
            option_type: CALL or PUT
            llm_price: LLM's calculated option price
            
        Returns:
            DerivativesResult with verification
        """
        # Use mpmath for high-precision transcendental math
        S = mpmath.mpf(str(spot_price))
        K = mpmath.mpf(str(strike_price))
        T = mpmath.mpf(str(time_to_expiry))
        r = mpmath.mpf(str(risk_free_rate))
        sigma = mpmath.mpf(str(volatility))
        
        # Calculate d1 and d2
        d1 = (mpmath.log(S / K) + (r + (sigma ** 2) / 2) * T) / (sigma * mpmath.sqrt(T))
        d2 = d1 - sigma * mpmath.sqrt(T)
        
        # Calculate option price
        if option_type == OptionType.CALL:
            price = S * self._norm_cdf(d1) - K * mpmath.exp(-r * T) * self._norm_cdf(d2)
        else:  # PUT
            price = K * mpmath.exp(-r * T) * self._norm_cdf(-d2) - S * self._norm_cdf(-d1)
        
        # Calculate Greeks
        greeks = self._calculate_greeks(S, K, T, r, sigma, option_type, d1, d2)
        
        # Parse LLM price
        import re
        llm_clean = re.sub(r'[$,\s]', '', llm_price)
        llm_decimal = Decimal(llm_clean)
        
        # Convert price to Decimal for comparison
        price_d = Decimal(str(mpmath.nstr(price, 15)))
        price_q = price_d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # Compare
        difference = abs(llm_decimal - price_d)
        if price_d > 0:
            difference_pct = (difference / price_d) * 100
        else:
            difference_pct = Decimal("0")
        
        verified = difference_pct <= self.tolerance_pct
        
        return DerivativesResult(
            verified=verified,
            llm_price=llm_price,
            computed_price=f"${price_q}",
            difference=f"${difference.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} ({difference_pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%)" if not verified else None,
            greeks=greeks,
            formula_used="Black-Scholes: C = S·N(d₁) - K·e^(-rT)·N(d₂)"
        )
    
    def _norm_cdf(self, x) -> mpmath.mpf:
        """Standard normal cumulative distribution function using mpmath."""
        return mpmath.mpf("0.5") * (1 + mpmath.erf(x / mpmath.sqrt(2)))
    
    def _norm_pdf(self, x) -> mpmath.mpf:
        """Standard normal probability density function using mpmath."""
        return mpmath.exp(mpmath.mpf("-0.5") * x ** 2) / mpmath.sqrt(2 * mpmath.pi)
    
    def _calculate_greeks(
        self,
        spot, strike, time_exp, rate, sigma,
        option_type: OptionType,
        d1, d2
    ) -> dict:
        """
        Calculate option Greeks (risk sensitivities).
        
        All computed using mpmath for precision, then quantized to Decimal for output.
        """
        sqrt_time = mpmath.sqrt(time_exp)
        
        # Delta: ∂V/∂S
        if option_type == OptionType.CALL:
            delta = self._norm_cdf(d1)
        else:
            delta = self._norm_cdf(d1) - 1
        
        # Gamma: ∂²V/∂S²
        gamma = self._norm_pdf(d1) / (spot * sigma * sqrt_time)
        
        # Theta: ∂V/∂T (per day, so divide by 365)
        theta_base = -(spot * self._norm_pdf(d1) * sigma) / (2 * sqrt_time)
        if option_type == OptionType.CALL:
            theta = theta_base - rate * strike * mpmath.exp(-rate * time_exp) * self._norm_cdf(d2)
        else:
            theta = theta_base + rate * strike * mpmath.exp(-rate * time_exp) * self._norm_cdf(-d2)
        theta_daily = theta / 365
        
        # Vega: ∂V/∂σ (per 1% move, so divide by 100)
        vega = spot * sqrt_time * self._norm_pdf(d1)
        vega_pct = vega / 100
        
        # Rho: ∂V/∂r (per 1% move, so divide by 100)
        if option_type == OptionType.CALL:
            rho = strike * time_exp * mpmath.exp(-rate * time_exp) * self._norm_cdf(d2)
        else:
            rho = -strike * time_exp * mpmath.exp(-rate * time_exp) * self._norm_cdf(-d2)
        rho_pct = rho / 100
        
        # Quantize output via Decimal for exact representation
        def to_dec(val, places):
            return str(Decimal(str(mpmath.nstr(val, 15))).quantize(Decimal(places), rounding=ROUND_HALF_UP))
        
        return {
            "delta": to_dec(delta, "0.0001"),
            "gamma": to_dec(gamma, "0.000001"),
            "theta": to_dec(theta_daily, "0.0001"),    # Per day
            "vega": to_dec(vega_pct, "0.0001"),        # Per 1% vol move
            "rho": to_dec(rho_pct, "0.0001")           # Per 1% rate move
        }
    
    def verify_delta(
        self,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        risk_free_rate: float,
        volatility: float,
        option_type: OptionType,
        llm_delta: float,
        tolerance: float = 0.01
    ) -> DerivativesResult:
        """
        Verify option Delta calculation.
        
        Delta = ∂V/∂S = N(d₁) for calls, N(d₁)-1 for puts
        """
        S = mpmath.mpf(str(spot_price))
        K = mpmath.mpf(str(strike_price))
        T = mpmath.mpf(str(time_to_expiry))
        r = mpmath.mpf(str(risk_free_rate))
        sigma = mpmath.mpf(str(volatility))
        
        d1 = (mpmath.log(S / K) + (r + (sigma ** 2) / 2) * T) / (sigma * mpmath.sqrt(T))
        
        if option_type == OptionType.CALL:
            computed_delta = self._norm_cdf(d1)
        else:
            computed_delta = self._norm_cdf(d1) - 1
        
        # Convert to Decimal for comparison
        computed_d = Decimal(str(mpmath.nstr(computed_delta, 15)))
        llm_d = Decimal(str(llm_delta))
        tol_d = Decimal(str(tolerance))
        
        difference = abs(llm_d - computed_d)
        verified = difference <= tol_d
        
        return DerivativesResult(
            verified=verified,
            llm_price=str(llm_delta),
            computed_price=f"{computed_d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}",
            difference=f"{difference.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="Delta = N(d₁) for calls"
        )
    
    # ==================== Margin Verification ====================
    
    def verify_margin_call(
        self,
        account_equity: float,
        maintenance_margin: float,
        position_value: float,
        llm_margin_call: bool
    ) -> DerivativesResult:
        """
        Verify margin call decision.
        
        Rule: If equity < maintenance_margin * position_value, MUST margin call.
        
        Args:
            account_equity: Current equity in account
            maintenance_margin: Maintenance margin requirement (e.g., 0.25 for 25%)
            position_value: Total position value
            llm_margin_call: LLM's margin call decision
            
        Returns:
            DerivativesResult
        """
        # Use Decimal for exact comparison
        equity_d = Decimal(str(account_equity))
        maint_d = Decimal(str(maintenance_margin))
        pos_d = Decimal(str(position_value))
        
        required_margin = maint_d * pos_d
        should_margin_call = equity_d < required_margin
        
        verified = (llm_margin_call == should_margin_call)
        
        return DerivativesResult(
            verified=verified,
            llm_price="MARGIN_CALL" if llm_margin_call else "NO_CALL",
            computed_price="MARGIN_CALL" if should_margin_call else "NO_CALL",
            margin_status=f"Equity: ${equity_d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}, Required: ${required_margin.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            formula_used="Margin Call if Equity < MaintenanceReq × PositionValue"
        )
    
    def verify_initial_margin(
        self,
        position_value: float,
        margin_requirement: float,
        llm_margin: str
    ) -> DerivativesResult:
        """
        Verify initial margin calculation.
        
        Initial Margin = Position Value × Margin Requirement
        
        Args:
            position_value: Total position value
            margin_requirement: Initial margin % (e.g., 0.50 for 50%)
            llm_margin: LLM's calculated margin
            
        Returns:
            DerivativesResult
        """
        computed_margin = Decimal(str(position_value)) * Decimal(str(margin_requirement))
        computed_margin = computed_margin.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        import re
        llm_clean = re.sub(r'[$,\s]', '', llm_margin)
        llm_decimal = Decimal(llm_clean)
        
        difference = abs(llm_decimal - computed_margin)
        tolerance = Decimal('0.01')
        
        return DerivativesResult(
            verified=(difference <= tolerance),
            llm_price=llm_margin,
            computed_price=f"${computed_margin}",
            difference=f"${difference}" if difference > tolerance else None,
            formula_used="Initial Margin = Position × Requirement%"
        )
    
    # ==================== Put-Call Parity ====================
    
    def verify_put_call_parity(
        self,
        call_price: float,
        put_price: float,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        risk_free_rate: float,
        tolerance: float = 0.05
    ) -> DerivativesResult:
        """
        Verify Put-Call Parity relationship.
        
        C - P = S - K*e^(-rT)
        
        Uses mpmath for exp() to avoid float precision loss.
        
        Args:
            call_price: Market call price
            put_price: Market put price
            spot_price: Current underlying price
            strike_price: Strike price
            time_to_expiry: Time to expiry in years
            risk_free_rate: Risk-free rate
            tolerance: Acceptable deviation
            
        Returns:
            DerivativesResult
        """
        # Use mpmath for exp, then Decimal for comparison
        S = mpmath.mpf(str(spot_price))
        K = mpmath.mpf(str(strike_price))
        T = mpmath.mpf(str(time_to_expiry))
        r = mpmath.mpf(str(risk_free_rate))
        
        lhs = mpmath.mpf(str(call_price)) - mpmath.mpf(str(put_price))
        rhs = S - K * mpmath.exp(-r * T)
        
        # Convert to Decimal for exact comparison
        lhs_d = Decimal(str(mpmath.nstr(lhs, 15)))
        rhs_d = Decimal(str(mpmath.nstr(rhs, 15)))
        tol_d = Decimal(str(tolerance))
        
        difference = abs(lhs_d - rhs_d)
        verified = difference <= tol_d
        
        return DerivativesResult(
            verified=verified,
            llm_price=f"C-P = {lhs_d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            computed_price=f"S-Ke^(-rT) = {rhs_d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            difference=f"{difference.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="Put-Call Parity: C - P = S - K·e^(-rT)"
        )
