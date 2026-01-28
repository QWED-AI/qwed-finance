"""
FX Guard - Foreign Exchange rate verification
Deterministic verification for forward rates, cross rates, and FX swaps
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple
from enum import Enum
import math


class QuoteConvention(Enum):
    """FX quote conventions"""
    DIRECT = "direct"      # Domestic per foreign (e.g., USD/EUR = 1.10)
    INDIRECT = "indirect"  # Foreign per domestic


@dataclass
class FXResult:
    """Result of an FX verification"""
    verified: bool
    llm_value: Optional[str]
    computed_value: str
    difference: Optional[str] = None
    formula_used: Optional[str] = None
    confidence: str = "SYMBOLIC_PROOF"
    details: Optional[dict] = None


class FXGuard:
    """
    Deterministic verification for FX calculations.
    Uses Interest Rate Parity and cross rate triangulation.
    """
    
    def __init__(self, pip_tolerance: int = 5):
        """
        Initialize the FX Guard.
        
        Args:
            pip_tolerance: Acceptable pip difference (default 5 pips)
        """
        self.pip_tolerance = pip_tolerance
    
    def verify_forward_rate(
        self,
        spot_rate: float,
        domestic_rate: float,
        foreign_rate: float,
        days: int,
        llm_forward: str,
        day_count: int = 360
    ) -> FXResult:
        """
        Verify Forward Rate calculation using Interest Rate Parity.
        
        Forward = Spot × (1 + rd × T) / (1 + rf × T)
        
        Where:
        - rd = domestic interest rate
        - rf = foreign interest rate
        - T = time fraction (days/360 or days/365)
        
        Args:
            spot_rate: Current spot rate
            domestic_rate: Domestic interest rate (annual, e.g., 0.05)
            foreign_rate: Foreign interest rate (annual)
            days: Number of days to forward date
            llm_forward: LLM's forward rate answer
            day_count: Day count convention (360 or 365)
            
        Returns:
            FXResult with verification status
        """
        # Parse LLM's forward rate
        llm_rate = float(llm_forward.replace(",", "").strip())
        
        # Time fraction
        T = Decimal(str(days)) / Decimal(str(day_count))
        
        # Interest rate parity formula
        spot = Decimal(str(spot_rate))
        rd = Decimal(str(domestic_rate))
        rf = Decimal(str(foreign_rate))
        
        forward = spot * (1 + rd * T) / (1 + rf * T)
        computed_forward = float(forward.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))
        
        # Calculate pip difference (assuming 4 decimal places for most pairs)
        pip_diff = abs(computed_forward - llm_rate) * 10000
        verified = pip_diff <= self.pip_tolerance
        
        return FXResult(
            verified=verified,
            llm_value=f"{llm_rate:.5f}",
            computed_value=f"{computed_forward:.5f}",
            difference=f"{pip_diff:.1f} pips" if not verified else None,
            formula_used="F = S × (1 + rd × T) / (1 + rf × T)",
            details={
                "spot": spot_rate,
                "domestic_rate": f"{domestic_rate * 100}%",
                "foreign_rate": f"{foreign_rate * 100}%",
                "days": days,
                "forward_points": f"{(computed_forward - spot_rate) * 10000:.1f} pips"
            }
        )
    
    def verify_cross_rate(
        self,
        rate_a_b: float,
        rate_b_c: float,
        llm_rate_a_c: str,
        pair_a: str = "A",
        pair_b: str = "B",
        pair_c: str = "C"
    ) -> FXResult:
        """
        Verify Cross Rate triangulation.
        
        A/C = (A/B) × (B/C)
        
        This ensures no arbitrage opportunity exists.
        
        Args:
            rate_a_b: Rate for A/B (e.g., EUR/USD = 1.10)
            rate_b_c: Rate for B/C (e.g., USD/JPY = 150)
            llm_rate_a_c: LLM's cross rate A/C (e.g., EUR/JPY = 165)
            pair_a, pair_b, pair_c: Currency codes for logging
            
        Returns:
            FXResult with verification status
        """
        llm_rate = float(llm_rate_a_c.replace(",", "").strip())
        
        # Cross rate calculation
        computed_cross = Decimal(str(rate_a_b)) * Decimal(str(rate_b_c))
        computed_cross = float(computed_cross.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
        
        # Tolerance depends on the rate magnitude
        # For JPY pairs, use absolute tolerance
        if computed_cross > 10:
            tolerance = 0.05  # 5 pips for high-value pairs
        else:
            tolerance = 0.0005  # 5 pips for low-value pairs
        
        diff = abs(computed_cross - llm_rate)
        verified = diff <= tolerance
        
        return FXResult(
            verified=verified,
            llm_value=f"{llm_rate:.4f}",
            computed_value=f"{computed_cross:.4f}",
            difference=f"{diff:.4f}" if not verified else None,
            formula_used=f"{pair_a}/{pair_c} = ({pair_a}/{pair_b}) × ({pair_b}/{pair_c})",
            details={
                f"{pair_a}/{pair_b}": rate_a_b,
                f"{pair_b}/{pair_c}": rate_b_c
            }
        )
    
    def verify_swap_points(
        self,
        spot_rate: float,
        forward_rate: float,
        llm_swap_points: str
    ) -> FXResult:
        """
        Verify FX Swap Points calculation.
        
        Swap Points = (Forward - Spot) × 10000
        
        Args:
            spot_rate: Current spot rate
            forward_rate: Forward rate
            llm_swap_points: LLM's swap points answer (in pips)
            
        Returns:
            FXResult with verification status
        """
        llm_points = float(llm_swap_points.replace("pips", "").replace("pts", "").strip())
        
        # Calculate swap points
        computed_points = (Decimal(str(forward_rate)) - Decimal(str(spot_rate))) * 10000
        computed_points = float(computed_points.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        
        diff = abs(computed_points - llm_points)
        verified = diff <= 1  # Within 1 pip tolerance
        
        return FXResult(
            verified=verified,
            llm_value=f"{llm_points:.1f} pips",
            computed_value=f"{computed_points:.1f} pips",
            difference=f"{diff:.1f} pips" if not verified else None,
            formula_used="Swap Points = (F - S) × 10000"
        )
    
    def verify_ndf_settlement(
        self,
        notional: float,
        contract_rate: float,
        fixing_rate: float,
        llm_settlement: str
    ) -> FXResult:
        """
        Verify Non-Deliverable Forward (NDF) settlement amount.
        
        Settlement = Notional × (Fixing Rate - Contract Rate) / Fixing Rate
        
        For USD-settled NDFs. Positive = party receives USD.
        
        Args:
            notional: Notional amount in foreign currency
            contract_rate: Agreed NDF rate
            fixing_rate: Fixing/settlement rate
            llm_settlement: LLM's settlement amount (in USD)
            
        Returns:
            FXResult with verification status
        """
        llm_val = self._parse_money(llm_settlement)
        
        # NDF settlement formula
        notional_dec = Decimal(str(notional))
        contract = Decimal(str(contract_rate))
        fixing = Decimal(str(fixing_rate))
        
        settlement = notional_dec * (fixing - contract) / fixing
        computed = settlement.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        diff = abs(computed - llm_val)
        verified = diff <= Decimal("0.01")
        
        return FXResult(
            verified=verified,
            llm_value=f"${llm_val:,.2f}",
            computed_value=f"${computed:,.2f}",
            difference=f"${diff:.2f}" if not verified else None,
            formula_used="Settlement = N × (Fix - Contract) / Fix",
            details={
                "notional": f"{notional:,.0f}",
                "contract_rate": contract_rate,
                "fixing_rate": fixing_rate
            }
        )
    
    def verify_currency_conversion(
        self,
        amount: float,
        rate: float,
        llm_converted: str,
        from_currency: str = "USD",
        to_currency: str = "EUR"
    ) -> FXResult:
        """
        Verify simple currency conversion.
        
        Converted = Amount × Rate (for direct quote)
        Converted = Amount / Rate (for indirect quote)
        
        Args:
            amount: Amount to convert
            rate: Exchange rate
            llm_converted: LLM's converted amount
            from_currency, to_currency: Currency codes
            
        Returns:
            FXResult with verification status
        """
        llm_val = self._parse_money(llm_converted)
        
        # Simple multiplication (assuming direct quote)
        computed = Decimal(str(amount)) * Decimal(str(rate))
        computed = computed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        diff = abs(computed - llm_val)
        tolerance = max(Decimal("0.01"), computed * Decimal("0.0001"))  # 0.01% or 1 cent
        verified = diff <= tolerance
        
        return FXResult(
            verified=verified,
            llm_value=f"{to_currency} {llm_val:,.2f}",
            computed_value=f"{to_currency} {computed:,.2f}",
            difference=f"{to_currency} {diff:.2f}" if not verified else None,
            formula_used=f"{to_currency} = {from_currency} Amount × Rate"
        )
    
    def verify_triangular_arbitrage(
        self,
        rate_ab: float,
        rate_bc: float,
        rate_ca: float,
        llm_arbitrage_exists: bool
    ) -> FXResult:
        """
        Verify if triangular arbitrage opportunity exists.
        
        No arbitrage if: (A/B) × (B/C) × (C/A) = 1
        Arbitrage exists if product != 1 (within tolerance)
        
        Args:
            rate_ab: Rate A/B
            rate_bc: Rate B/C
            rate_ca: Rate C/A
            llm_arbitrage_exists: LLM claims arbitrage exists
            
        Returns:
            FXResult with verification status
        """
        # Calculate round-trip product
        product = Decimal(str(rate_ab)) * Decimal(str(rate_bc)) * Decimal(str(rate_ca))
        product = float(product.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))
        
        # Arbitrage exists if product deviates from 1 by more than transaction costs (~0.1%)
        TRANSACTION_COST_THRESHOLD = 0.001
        computed_arbitrage = abs(product - 1) > TRANSACTION_COST_THRESHOLD
        
        verified = computed_arbitrage == llm_arbitrage_exists
        
        return FXResult(
            verified=verified,
            llm_value=f"Arbitrage: {llm_arbitrage_exists}",
            computed_value=f"Arbitrage: {computed_arbitrage}",
            difference=None if verified else "LLM incorrectly assessed arbitrage",
            formula_used="Product = (A/B) × (B/C) × (C/A), Arbitrage if |Product - 1| > 0.1%",
            details={
                "round_trip_product": product,
                "deviation_from_1": f"{abs(product - 1) * 100:.4f}%"
            }
        )
    
    def _parse_money(self, value: str) -> Decimal:
        """Parse money string to Decimal"""
        import re
        cleaned = re.sub(r'[,$€£¥]', '', str(value).strip())
        return Decimal(cleaned)
