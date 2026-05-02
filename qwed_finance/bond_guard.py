"""
Bond Guard - Fixed income verification for bond pricing
Deterministic verification for YTM, Duration, Convexity calculations

All financial math uses Decimal for exact arithmetic.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import List, Optional, Tuple
from enum import Enum

# Set precision high enough for Newton-Raphson convergence
getcontext().prec = 50


class DayCountConvention(Enum):
    """Bond day count conventions"""
    THIRTY_360 = "30/360"
    ACTUAL_360 = "ACT/360"
    ACTUAL_365 = "ACT/365"
    ACTUAL_ACTUAL = "ACT/ACT"


@dataclass
class BondResult:
    """Result of a bond verification"""
    verified: bool
    llm_value: Optional[str]
    computed_value: str
    difference: Optional[str] = None
    formula_used: Optional[str] = None
    confidence: str = "SYMBOLIC_PROOF"
    details: Optional[dict] = None


class BondGuard:
    """
    Deterministic verification for bond calculations.
    Uses Newton-Raphson for YTM solving — 100% deterministic.

    All internal math uses Decimal for exact arithmetic,
    following the TradingGuard gold standard.
    """
    
    def __init__(self, tolerance_pct: float = 0.5, max_iterations: int = 100):
        """
        Initialize the Bond Guard.
        
        Args:
            tolerance_pct: Acceptable % difference for verification
            max_iterations: Max iterations for YTM solver
        """
        self.tolerance_pct = Decimal(str(tolerance_pct))
        self.max_iterations = max_iterations
    
    def verify_ytm(
        self,
        face_value: float,
        coupon_rate: float,
        price: float,
        years_to_maturity: float,
        llm_ytm: str,
        frequency: int = 2  # Semi-annual default
    ) -> BondResult:
        """
        Verify Yield to Maturity calculation.
        
        YTM is the rate r where:
        Price = Σ (C / (1+r/n)^t) + (FV / (1+r/n)^n)
        
        Uses Newton-Raphson iteration for solving.
        
        Args:
            face_value: Par value of bond (e.g., 1000)
            coupon_rate: Annual coupon rate (e.g., 0.05 for 5%)
            price: Current market price
            years_to_maturity: Years until maturity
            frequency: Coupon payments per year (1=annual, 2=semi, 4=quarterly)
            llm_ytm: LLM's YTM answer (e.g., "5.25%" or "0.0525")
            
        Returns:
            BondResult with verification status
        """
        # Parse LLM's YTM
        llm_rate_d = self._parse_rate(llm_ytm)
        
        # Convert inputs to Decimal at the boundary
        fv = Decimal(str(face_value))
        cr = Decimal(str(coupon_rate))
        p = Decimal(str(price))
        freq = Decimal(str(frequency))
        
        # Calculate periodic values
        n_periods = int(years_to_maturity * frequency)
        coupon_payment = (fv * cr) / freq
        
        # Newton-Raphson to find YTM
        computed_ytm = self._solve_ytm(
            fv, coupon_payment, p, n_periods, frequency
        )
        
        # Compare
        if computed_ytm > 0:
            diff_pct = abs(computed_ytm - llm_rate_d) / computed_ytm * 100
        else:
            diff_pct = Decimal("0")
        verified = diff_pct <= self.tolerance_pct
        
        # Format output with quantized precision
        computed_pct = (computed_ytm * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        llm_pct = (llm_rate_d * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        return BondResult(
            verified=verified,
            llm_value=f"{llm_pct}%",
            computed_value=f"{computed_pct}%",
            difference=f"{diff_pct.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}%" if not verified else None,
            formula_used="Newton-Raphson YTM Solver",
            details={
                "face_value": str(fv),
                "coupon_rate": f"{cr * 100}%",
                "price": str(p),
                "periods": n_periods,
                "frequency": frequency
            }
        )
    
    def _solve_ytm(
        self,
        face_value: Decimal,
        coupon: Decimal,
        price: Decimal,
        n_periods: int,
        frequency: int
    ) -> Decimal:
        """Newton-Raphson YTM solver using Decimal arithmetic."""
        freq = Decimal(str(frequency))
        
        # Initial guess (current yield)
        ytm = (coupon * freq) / price
        
        for _ in range(self.max_iterations):
            # Bond price at current ytm
            pv_coupons = Decimal("0")
            for t in range(1, n_periods + 1):
                pv_coupons += coupon / ((1 + ytm / freq) ** t)
            
            pv_face = face_value / ((1 + ytm / freq) ** n_periods)
            bond_price = pv_coupons + pv_face
            
            # Derivative (duration-based approximation)
            dpv = Decimal("0")
            for t in range(1, n_periods + 1):
                dpv -= Decimal(str(t)) * coupon / ((1 + ytm / freq) ** (t + 1)) / freq
            dpv -= Decimal(str(n_periods)) * face_value / ((1 + ytm / freq) ** (n_periods + 1)) / freq
            
            # Newton step
            diff = bond_price - price
            if abs(diff) < Decimal("1E-10"):
                break
            
            if abs(dpv) > Decimal("1E-10"):
                ytm = ytm - diff / dpv
            
            # Keep YTM in a reasonable range for convergence
            # Upper bound 10.0 (1000%) supports distressed debt scenarios
            ytm = max(Decimal("0.0001"), min(ytm, Decimal("10")))
        
        return ytm
    
    def verify_duration(
        self,
        face_value: float,
        coupon_rate: float,
        ytm: float,
        years_to_maturity: float,
        llm_duration: str,
        frequency: int = 2
    ) -> BondResult:
        """
        Verify Macaulay Duration calculation.
        
        Duration = Σ (t × PV(CFt)) / Price
        
        Duration measures interest rate sensitivity.
        
        Args:
            face_value: Par value of bond
            coupon_rate: Annual coupon rate
            ytm: Yield to maturity (annual)
            years_to_maturity: Years until maturity
            frequency: Coupon payments per year
            llm_duration: LLM's duration answer (in years)
            
        Returns:
            BondResult with verification status
        """
        # Parse LLM's duration
        llm_dur = Decimal(llm_duration.replace("years", "").replace("yrs", "").strip())
        
        # Convert to Decimal
        fv = Decimal(str(face_value))
        cr = Decimal(str(coupon_rate))
        y = Decimal(str(ytm))
        freq = Decimal(str(frequency))
        
        # Calculate duration
        n_periods = int(years_to_maturity * frequency)
        coupon_payment = (fv * cr) / freq
        periodic_rate = y / freq
        
        # Calculate price and weighted time
        weighted_time = Decimal("0")
        price = Decimal("0")
        
        for t in range(1, n_periods + 1):
            pv = coupon_payment / ((1 + periodic_rate) ** t)
            price += pv
            weighted_time += (Decimal(str(t)) / freq) * pv
        
        # Add face value
        pv_face = fv / ((1 + periodic_rate) ** n_periods)
        price += pv_face
        weighted_time += Decimal(str(years_to_maturity)) * pv_face
        
        # Macaulay duration
        computed_duration = weighted_time / price
        computed_dur_q = computed_duration.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed_dur_q - llm_dur)
        verified = diff <= Decimal("0.05")  # Within 0.05 years tolerance
        
        # Modified duration
        mod_duration = computed_duration / (1 + periodic_rate)
        mod_dur_q = mod_duration.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        return BondResult(
            verified=verified,
            llm_value=f"{llm_dur} years",
            computed_value=f"{computed_dur_q} years",
            difference=f"{diff.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)} years" if not verified else None,
            formula_used="Macaulay Duration = Σ(t × PV(CFt)) / Price",
            details={
                "price": f"${price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
                "modified_duration": f"{mod_dur_q} years"
            }
        )
    
    def verify_convexity(
        self,
        face_value: float,
        coupon_rate: float,
        ytm: float,
        years_to_maturity: float,
        llm_convexity: str,
        frequency: int = 2
    ) -> BondResult:
        """
        Verify Convexity calculation.
        
        Convexity = Σ (t(t+1) × PV(CFt)) / (Price × (1+y)²)
        
        Convexity measures curvature of price-yield relationship.
        
        Args:
            face_value: Par value of bond
            coupon_rate: Annual coupon rate
            ytm: Yield to maturity
            years_to_maturity: Years until maturity
            frequency: Coupon payments per year
            llm_convexity: LLM's convexity answer
            
        Returns:
            BondResult with verification status
        """
        # Parse LLM's convexity
        llm_conv = Decimal(llm_convexity.replace("years²", "").strip())
        
        # Convert to Decimal
        fv = Decimal(str(face_value))
        cr = Decimal(str(coupon_rate))
        y = Decimal(str(ytm))
        freq = Decimal(str(frequency))
        
        # Calculate convexity
        n_periods = int(years_to_maturity * frequency)
        coupon_payment = (fv * cr) / freq
        periodic_rate = y / freq
        
        # Calculate weighted sum and price
        weighted_sum = Decimal("0")
        price = Decimal("0")
        
        for t in range(1, n_periods + 1):
            td = Decimal(str(t))
            pv = coupon_payment / ((1 + periodic_rate) ** t)
            price += pv
            weighted_sum += td * (td + 1) * pv
        
        pv_face = fv / ((1 + periodic_rate) ** n_periods)
        price += pv_face
        nd = Decimal(str(n_periods))
        weighted_sum += nd * (nd + 1) * pv_face
        
        # Convexity in years
        computed_convexity = weighted_sum / (price * ((1 + periodic_rate) ** 2) * (freq ** 2))
        computed_conv_q = computed_convexity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        # Compare
        if computed_convexity > 0:
            diff_pct = abs(computed_convexity - llm_conv) / computed_convexity * 100
        else:
            diff_pct = Decimal("0")
        verified = diff_pct <= self.tolerance_pct
        
        return BondResult(
            verified=verified,
            llm_value=f"{llm_conv}",
            computed_value=f"{computed_conv_q}",
            difference=f"{diff_pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%" if not verified else None,
            formula_used="Convexity = Σ(t(t+1) × PV(CFt)) / (P × (1+y)²)"
        )
    
    def verify_accrued_interest(
        self,
        face_value: float,
        coupon_rate: float,
        days_since_last_coupon: int,
        days_in_period: int,
        llm_accrued: str
    ) -> BondResult:
        """
        Verify Accrued Interest calculation.
        
        Accrued = (Days Since Coupon / Days in Period) × Coupon Payment
        
        Args:
            face_value: Par value
            coupon_rate: Annual coupon rate
            days_since_last_coupon: Days elapsed since last coupon
            days_in_period: Total days in coupon period
            llm_accrued: LLM's accrued interest answer
            
        Returns:
            BondResult with verification status
        """
        # Parse LLM's value
        llm_val = self._parse_money(llm_accrued)
        
        # Semi-annual coupon
        coupon = (face_value * coupon_rate) / 2
        
        # Accrued interest
        accrued = Decimal(str(days_since_last_coupon)) / Decimal(str(days_in_period)) * Decimal(str(coupon))
        computed = accrued.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed - llm_val)
        verified = diff <= Decimal("0.01")
        
        return BondResult(
            verified=verified,
            llm_value=f"${llm_val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            computed_value=f"${computed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            difference=f"${diff.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="Accrued = (Days/Period) × Coupon"
        )
    
    def verify_dirty_price(
        self,
        clean_price: float,
        accrued_interest: float,
        llm_dirty: str
    ) -> BondResult:
        """
        Verify Dirty Price (Full Price) calculation.
        
        Dirty Price = Clean Price + Accrued Interest
        
        Args:
            clean_price: Quoted market price
            accrued_interest: Accrued interest
            llm_dirty: LLM's dirty price answer
            
        Returns:
            BondResult with verification status
        """
        llm_val = self._parse_money(llm_dirty)
        computed = Decimal(str(clean_price)) + Decimal(str(accrued_interest))
        computed = computed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        diff = abs(computed - llm_val)
        verified = diff <= Decimal("0.01")
        
        return BondResult(
            verified=verified,
            llm_value=f"${llm_val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            computed_value=f"${computed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            difference=f"${diff.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="Dirty Price = Clean Price + Accrued Interest"
        )
    
    def _parse_rate(self, rate_str: str) -> Decimal:
        """Parse rate string to Decimal — fail-closed, no silent guessing.

        Rules:
          - "5.25%" or "5.25 %" → Decimal("0.0525")  (explicit percentage)
          - "0.0525"            → Decimal("0.0525")  (explicit decimal fraction)
          - "5.25" (no %)       → Decimal("5.25")    (no guessing; caller must include '%' for percent format)

        QWED philosophy: if format is ambiguous, do NOT guess.
        Callers must use explicit '%' suffix for percentage values.
        """
        rate_str = rate_str.strip()
        if "%" in rate_str:
            return Decimal(rate_str.replace("%", "").strip()) / Decimal("100")
        # No % symbol: treat as decimal fraction (0.05 means 5%)
        return Decimal(rate_str)
    
    def _parse_money(self, value: str) -> Decimal:
        """Parse money string to Decimal"""
        import re
        cleaned = re.sub(r'[,$]', '', str(value).strip())
        return Decimal(cleaned)
