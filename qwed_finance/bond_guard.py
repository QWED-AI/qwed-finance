"""
Bond Guard - Fixed income verification for bond pricing
Deterministic verification for YTM, Duration, Convexity calculations
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
from enum import Enum
import math


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
    Uses Newton-Raphson for YTM solving - 100% deterministic.
    """
    
    def __init__(self, tolerance_pct: float = 0.5, max_iterations: int = 100):
        """
        Initialize the Bond Guard.
        
        Args:
            tolerance_pct: Acceptable % difference for verification
            max_iterations: Max iterations for YTM solver
        """
        self.tolerance_pct = tolerance_pct
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
        llm_rate = self._parse_rate(llm_ytm)
        
        # Calculate periodic values
        n_periods = int(years_to_maturity * frequency)
        coupon_payment = (face_value * coupon_rate) / frequency
        
        # Newton-Raphson to find YTM
        computed_ytm = self._solve_ytm(
            face_value, coupon_payment, price, n_periods, frequency
        )
        
        # Compare
        diff_pct = abs(computed_ytm - llm_rate) / computed_ytm * 100 if computed_ytm > 0 else 0
        verified = diff_pct <= self.tolerance_pct
        
        return BondResult(
            verified=verified,
            llm_value=f"{llm_rate * 100:.4f}%",
            computed_value=f"{computed_ytm * 100:.4f}%",
            difference=f"{diff_pct:.4f}%" if not verified else None,
            formula_used="Newton-Raphson YTM Solver",
            details={
                "face_value": face_value,
                "coupon_rate": f"{coupon_rate * 100}%",
                "price": price,
                "periods": n_periods,
                "frequency": frequency
            }
        )
    
    def _solve_ytm(
        self,
        face_value: float,
        coupon: float,
        price: float,
        n_periods: int,
        frequency: int
    ) -> float:
        """Newton-Raphson YTM solver"""
        # Initial guess (current yield)
        ytm = (coupon * frequency) / price
        
        for _ in range(self.max_iterations):
            # Bond price at current ytm
            pv_coupons = sum(
                coupon / ((1 + ytm / frequency) ** t) 
                for t in range(1, n_periods + 1)
            )
            pv_face = face_value / ((1 + ytm / frequency) ** n_periods)
            bond_price = pv_coupons + pv_face
            
            # Derivative (duration-based approximation)
            dpv = -sum(
                t * coupon / ((1 + ytm / frequency) ** (t + 1)) / frequency
                for t in range(1, n_periods + 1)
            )
            dpv -= n_periods * face_value / ((1 + ytm / frequency) ** (n_periods + 1)) / frequency
            
            # Newton step
            diff = bond_price - price
            if abs(diff) < 1e-10:
                break
            
            if abs(dpv) > 1e-10:
                ytm = ytm - diff / dpv
            
            # Keep YTM reasonable
            ytm = max(0.0001, min(ytm, 1.0))
        
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
        llm_dur = float(llm_duration.replace("years", "").replace("yrs", "").strip())
        
        # Calculate duration
        n_periods = int(years_to_maturity * frequency)
        coupon_payment = (face_value * coupon_rate) / frequency
        periodic_rate = ytm / frequency
        
        # Calculate price and weighted time
        weighted_time = 0
        price = 0
        
        for t in range(1, n_periods + 1):
            pv = coupon_payment / ((1 + periodic_rate) ** t)
            price += pv
            weighted_time += (t / frequency) * pv
        
        # Add face value
        pv_face = face_value / ((1 + periodic_rate) ** n_periods)
        price += pv_face
        weighted_time += years_to_maturity * pv_face
        
        # Macaulay duration
        computed_duration = weighted_time / price
        
        # Compare
        diff = abs(computed_duration - llm_dur)
        verified = diff <= 0.05  # Within 0.05 years tolerance
        
        return BondResult(
            verified=verified,
            llm_value=f"{llm_dur:.4f} years",
            computed_value=f"{computed_duration:.4f} years",
            difference=f"{diff:.4f} years" if not verified else None,
            formula_used="Macaulay Duration = Σ(t × PV(CFt)) / Price",
            details={
                "price": f"${price:.2f}",
                "modified_duration": f"{computed_duration / (1 + periodic_rate):.4f} years"
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
        llm_conv = float(llm_convexity.replace("years²", "").strip())
        
        # Calculate convexity
        n_periods = int(years_to_maturity * frequency)
        coupon_payment = (face_value * coupon_rate) / frequency
        periodic_rate = ytm / frequency
        
        # Calculate weighted sum and price
        weighted_sum = 0
        price = 0
        
        for t in range(1, n_periods + 1):
            pv = coupon_payment / ((1 + periodic_rate) ** t)
            price += pv
            weighted_sum += t * (t + 1) * pv
        
        pv_face = face_value / ((1 + periodic_rate) ** n_periods)
        price += pv_face
        weighted_sum += n_periods * (n_periods + 1) * pv_face
        
        # Convexity in years
        computed_convexity = weighted_sum / (price * ((1 + periodic_rate) ** 2) * (frequency ** 2))
        
        # Compare
        diff_pct = abs(computed_convexity - llm_conv) / computed_convexity * 100 if computed_convexity > 0 else 0
        verified = diff_pct <= self.tolerance_pct
        
        return BondResult(
            verified=verified,
            llm_value=f"{llm_conv:.4f}",
            computed_value=f"{computed_convexity:.4f}",
            difference=f"{diff_pct:.2f}%" if not verified else None,
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
            llm_value=f"${llm_val:.2f}",
            computed_value=f"${computed:.2f}",
            difference=f"${diff:.2f}" if not verified else None,
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
            llm_value=f"${llm_val:.2f}",
            computed_value=f"${computed:.2f}",
            difference=f"${diff:.2f}" if not verified else None,
            formula_used="Dirty Price = Clean Price + Accrued Interest"
        )
    
    def _parse_rate(self, rate_str: str) -> float:
        """Parse rate string to float (handles % and decimal)"""
        rate_str = rate_str.strip()
        if "%" in rate_str:
            return float(rate_str.replace("%", "").strip()) / 100
        val = float(rate_str)
        return val if val < 1 else val / 100
    
    def _parse_money(self, value: str) -> Decimal:
        """Parse money string to Decimal"""
        import re
        cleaned = re.sub(r'[,$]', '', str(value).strip())
        return Decimal(cleaned)
