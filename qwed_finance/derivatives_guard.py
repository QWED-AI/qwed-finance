"""
Derivatives Guard - Black-Scholes options pricing and margin verification
Deterministic verification for derivatives trading
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple
from enum import Enum
import math


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
    Uses Black-Scholes formula (pure calculus) for options verification.
    """
    
    def __init__(self, tolerance_pct: float = 1.0):
        """
        Initialize the Derivatives Guard.
        
        Args:
            tolerance_pct: Acceptable % difference for price verification
        """
        self.tolerance_pct = tolerance_pct
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
        S = spot_price
        K = strike_price
        T = time_to_expiry
        r = risk_free_rate
        sigma = volatility
        
        # Calculate d1 and d2
        d1 = (math.log(S / K) + (r + (sigma ** 2) / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        # Calculate option price
        if option_type == OptionType.CALL:
            price = S * self._norm_cdf(d1) - K * math.exp(-r * T) * self._norm_cdf(d2)
        else:  # PUT
            price = K * math.exp(-r * T) * self._norm_cdf(-d2) - S * self._norm_cdf(-d1)
        
        # Calculate Greeks
        greeks = self._calculate_greeks(S, K, T, r, sigma, option_type, d1, d2)
        
        # Parse LLM price
        import re
        llm_clean = re.sub(r'[$,\s]', '', llm_price)
        llm_decimal = float(llm_clean)
        
        # Compare
        difference = abs(llm_decimal - price)
        difference_pct = (difference / price) * 100 if price > 0 else 0
        
        verified = difference_pct <= self.tolerance_pct
        
        return DerivativesResult(
            verified=verified,
            llm_price=llm_price,
            computed_price=f"${price:.2f}",
            difference=f"${difference:.2f} ({difference_pct:.2f}%)" if not verified else None,
            greeks=greeks,
            formula_used="Black-Scholes: C = S·N(d₁) - K·e^(-rT)·N(d₂)"
        )
    
    def _norm_cdf(self, x: float) -> float:
        """Standard normal cumulative distribution function"""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    
    def _norm_pdf(self, x: float) -> float:
        """Standard normal probability density function"""
        return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)
    
    def _calculate_greeks(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: OptionType,
        d1: float,
        d2: float
    ) -> dict:
        """
        Calculate option Greeks (risk sensitivities).
        
        All are pure calculus - 100% deterministic.
        """
        sqrt_T = math.sqrt(T)
        
        # Delta: ∂V/∂S
        if option_type == OptionType.CALL:
            delta = self._norm_cdf(d1)
        else:
            delta = self._norm_cdf(d1) - 1
        
        # Gamma: ∂²V/∂S²
        gamma = self._norm_pdf(d1) / (S * sigma * sqrt_T)
        
        # Theta: ∂V/∂T (per day, so divide by 365)
        theta_base = -(S * self._norm_pdf(d1) * sigma) / (2 * sqrt_T)
        if option_type == OptionType.CALL:
            theta = theta_base - r * K * math.exp(-r * T) * self._norm_cdf(d2)
        else:
            theta = theta_base + r * K * math.exp(-r * T) * self._norm_cdf(-d2)
        theta_daily = theta / 365
        
        # Vega: ∂V/∂σ (per 1% move, so divide by 100)
        vega = S * sqrt_T * self._norm_pdf(d1)
        vega_pct = vega / 100
        
        # Rho: ∂V/∂r (per 1% move, so divide by 100)
        if option_type == OptionType.CALL:
            rho = K * T * math.exp(-r * T) * self._norm_cdf(d2)
        else:
            rho = -K * T * math.exp(-r * T) * self._norm_cdf(-d2)
        rho_pct = rho / 100
        
        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta_daily, 4),    # Per day
            "vega": round(vega_pct, 4),        # Per 1% vol move
            "rho": round(rho_pct, 4)           # Per 1% rate move
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
        S, K, T, r, sigma = spot_price, strike_price, time_to_expiry, risk_free_rate, volatility
        
        d1 = (math.log(S / K) + (r + (sigma ** 2) / 2) * T) / (sigma * math.sqrt(T))
        
        if option_type == OptionType.CALL:
            computed_delta = self._norm_cdf(d1)
        else:
            computed_delta = self._norm_cdf(d1) - 1
        
        difference = abs(llm_delta - computed_delta)
        verified = difference <= tolerance
        
        return DerivativesResult(
            verified=verified,
            llm_price=str(llm_delta),
            computed_price=f"{computed_delta:.4f}",
            difference=f"{difference:.4f}" if not verified else None,
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
        required_margin = maintenance_margin * position_value
        should_margin_call = account_equity < required_margin
        
        verified = (llm_margin_call == should_margin_call)
        
        return DerivativesResult(
            verified=verified,
            llm_price="MARGIN_CALL" if llm_margin_call else "NO_CALL",
            computed_price="MARGIN_CALL" if should_margin_call else "NO_CALL",
            margin_status=f"Equity: ${account_equity:.2f}, Required: ${required_margin:.2f}",
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
        S, K, T, r = spot_price, strike_price, time_to_expiry, risk_free_rate
        
        lhs = call_price - put_price
        rhs = S - K * math.exp(-r * T)
        
        difference = abs(lhs - rhs)
        verified = difference <= tolerance
        
        return DerivativesResult(
            verified=verified,
            llm_price=f"C-P = {lhs:.2f}",
            computed_price=f"S-Ke^(-rT) = {rhs:.2f}",
            difference=f"{difference:.2f}" if not verified else None,
            formula_used="Put-Call Parity: C - P = S - K·e^(-rT)"
        )
