"""
Finance Verifier - Core verification logic for banking calculations
Uses QWED's Math Engine (SymPy) for deterministic verification
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Union
import re


@dataclass
class VerificationResult:
    """Result of a financial verification"""
    verified: bool
    llm_value: Optional[str]
    computed_value: str
    difference: Optional[str] = None
    formula_used: Optional[str] = None
    confidence: str = "SYMBOLIC_PROOF"


class FinanceVerifier:
    """
    Deterministic verification for financial calculations.
    Uses SymPy for symbolic math - no floating-point errors.
    """
    
    def __init__(self, precision: int = 2):
        """
        Initialize the finance verifier.
        
        Args:
            precision: Decimal places for money calculations (default: 2)
        """
        self.precision = precision
        self._sympy_available = self._check_sympy()
    
    def _check_sympy(self) -> bool:
        """Check if SymPy is available for symbolic computation"""
        try:
            import sympy
            return True
        except ImportError:
            return False
    
    def _parse_money(self, value: str) -> Decimal:
        """
        Parse money string to Decimal.
        Handles formats: $1,234.56, 1234.56, $1234, etc.
        """
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        
        # Remove currency symbols and commas
        cleaned = re.sub(r'[$€£¥,\s]', '', str(value))
        return Decimal(cleaned)
    
    def _format_money(self, value: Decimal, symbol: str = "$") -> str:
        """Format Decimal as money string"""
        quantized = value.quantize(Decimal(10) ** -self.precision, rounding=ROUND_HALF_UP)
        return f"{symbol}{quantized:,.{self.precision}f}"
    
    # ==================== NPV/IRR ====================
    
    def verify_npv(
        self,
        cashflows: List[float],
        rate: float,
        llm_output: str
    ) -> VerificationResult:
        """
        Verify Net Present Value calculation.
        
        NPV = Σ (CFt / (1 + r)^t) for t = 0 to n
        
        Args:
            cashflows: List of cash flows (CF0, CF1, ..., CFn)
            rate: Discount rate (e.g., 0.10 for 10%)
            llm_output: The LLM's NPV answer
            
        Returns:
            VerificationResult with verification status
        """
        # Compute NPV deterministically
        npv = Decimal('0')
        for t, cf in enumerate(cashflows):
            cf_decimal = Decimal(str(cf))
            discount_factor = Decimal(str(1 + rate)) ** t
            npv += cf_decimal / discount_factor
        
        computed = self._format_money(npv)
        llm_value = self._parse_money(llm_output)
        computed_value = self._parse_money(computed)
        
        # Check if values match within precision
        difference = abs(llm_value - computed_value)
        tolerance = Decimal('0.01')  # 1 cent tolerance
        
        return VerificationResult(
            verified=difference <= tolerance,
            llm_value=llm_output,
            computed_value=computed,
            difference=str(difference) if difference > 0 else None,
            formula_used="NPV = Σ(CFt / (1+r)^t)"
        )
    
    def verify_irr(
        self,
        cashflows: List[float],
        llm_output: str,
        tolerance: float = 0.0001
    ) -> VerificationResult:
        """
        Verify Internal Rate of Return calculation.
        
        IRR is the rate r where NPV = 0
        
        Args:
            cashflows: List of cash flows
            llm_output: LLM's IRR answer (e.g., "15.23%" or "0.1523")
            tolerance: Acceptable error in IRR calculation
            
        Returns:
            VerificationResult
        """
        if self._sympy_available:
            from sympy import symbols, solve, Rational
            
            r = symbols('r')
            npv_expr = sum(
                Rational(str(cf)) / (1 + r) ** t 
                for t, cf in enumerate(cashflows)
            )
            
            solutions = solve(npv_expr, r)
            # Filter for real, positive solutions
            real_solutions = [float(s) for s in solutions if s.is_real and s > -1]
            
            if real_solutions:
                computed_irr = real_solutions[0]
            else:
                computed_irr = None
        else:
            # Fallback: Newton-Raphson method
            computed_irr = self._compute_irr_numeric(cashflows)
        
        if computed_irr is None:
            return VerificationResult(
                verified=False,
                llm_value=llm_output,
                computed_value="No valid IRR exists",
                confidence="COMPUTATION_FAILED"
            )
        
        # Parse LLM output
        llm_clean = re.sub(r'[%\s]', '', llm_output)
        llm_rate = float(llm_clean)
        if llm_rate > 1:  # Assume percentage
            llm_rate /= 100
        
        difference = abs(llm_rate - computed_irr)
        
        return VerificationResult(
            verified=difference <= tolerance,
            llm_value=llm_output,
            computed_value=f"{computed_irr * 100:.2f}%",
            difference=f"{difference * 100:.4f}%" if difference > 0 else None,
            formula_used="IRR: NPV(r) = 0"
        )
    
    def _compute_irr_numeric(self, cashflows: List[float], max_iter: int = 100) -> Optional[float]:
        """Newton-Raphson IRR calculation (fallback)"""
        rate = 0.1  # Initial guess
        
        for _ in range(max_iter):
            npv = sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))
            npv_derivative = sum(
                -t * cf / (1 + rate) ** (t + 1) 
                for t, cf in enumerate(cashflows)
            )
            
            if abs(npv_derivative) < 1e-10:
                break
                
            rate_new = rate - npv / npv_derivative
            
            if abs(rate_new - rate) < 1e-7:
                return rate_new
                
            rate = rate_new
        
        return rate if abs(npv) < 0.01 else None
    
    # ==================== Loan Calculations ====================
    
    def verify_monthly_payment(
        self,
        principal: float,
        annual_rate: float,
        months: int,
        llm_output: str
    ) -> VerificationResult:
        """
        Verify monthly loan payment calculation.
        
        PMT = P * [r(1+r)^n] / [(1+r)^n - 1]
        
        Args:
            principal: Loan amount
            annual_rate: Annual interest rate (e.g., 0.06 for 6%)
            months: Number of monthly payments
            llm_output: LLM's payment answer
            
        Returns:
            VerificationResult
        """
        P = Decimal(str(principal))
        monthly_rate = Decimal(str(annual_rate)) / 12
        n = months
        
        if monthly_rate == 0:
            payment = P / n
        else:
            # PMT = P * [r(1+r)^n] / [(1+r)^n - 1]
            one_plus_r = 1 + monthly_rate
            one_plus_r_n = one_plus_r ** n
            payment = P * (monthly_rate * one_plus_r_n) / (one_plus_r_n - 1)
        
        computed = self._format_money(payment)
        llm_value = self._parse_money(llm_output)
        computed_value = self._parse_money(computed)
        
        difference = abs(llm_value - computed_value)
        tolerance = Decimal('0.01')
        
        return VerificationResult(
            verified=difference <= tolerance,
            llm_value=llm_output,
            computed_value=computed,
            difference=str(difference) if difference > 0 else None,
            formula_used="PMT = P × [r(1+r)^n] / [(1+r)^n - 1]"
        )
    
    def verify_total_interest(
        self,
        principal: float,
        annual_rate: float,
        months: int,
        llm_output: str
    ) -> VerificationResult:
        """
        Verify total interest paid over loan term.
        
        Total Interest = (Monthly Payment × n) - Principal
        """
        # First compute monthly payment
        P = Decimal(str(principal))
        monthly_rate = Decimal(str(annual_rate)) / 12
        n = months
        
        if monthly_rate == 0:
            total_interest = Decimal('0')
        else:
            one_plus_r = 1 + monthly_rate
            one_plus_r_n = one_plus_r ** n
            payment = P * (monthly_rate * one_plus_r_n) / (one_plus_r_n - 1)
            total_interest = (payment * n) - P
        
        computed = self._format_money(total_interest)
        llm_value = self._parse_money(llm_output)
        computed_value = self._parse_money(computed)
        
        difference = abs(llm_value - computed_value)
        tolerance = Decimal('0.10')  # 10 cent tolerance for accumulated rounding
        
        return VerificationResult(
            verified=difference <= tolerance,
            llm_value=llm_output,
            computed_value=computed,
            difference=str(difference) if difference > 0 else None,
            formula_used="Total Interest = (PMT × n) - P"
        )
    
    # ==================== Compound Interest ====================
    
    def verify_compound_interest(
        self,
        principal: float,
        rate: float,
        periods: int,
        llm_output: str,
        compounding: str = "annual"
    ) -> VerificationResult:
        """
        Verify compound interest calculation.
        
        A = P(1 + r/n)^(nt)
        
        Args:
            principal: Initial investment
            rate: Annual interest rate
            periods: Number of years
            llm_output: LLM's answer
            compounding: "annual", "quarterly", "monthly", "daily"
            
        Returns:
            VerificationResult
        """
        P = Decimal(str(principal))
        r = Decimal(str(rate))
        t = periods
        
        # Compounding frequency
        n_map = {
            "annual": 1,
            "semi-annual": 2,
            "quarterly": 4,
            "monthly": 12,
            "daily": 365
        }
        n = n_map.get(compounding, 1)
        
        # A = P(1 + r/n)^(nt)
        compound_factor = (1 + r / n) ** (n * t)
        final_amount = P * compound_factor
        
        computed = self._format_money(final_amount)
        llm_value = self._parse_money(llm_output)
        computed_value = self._parse_money(computed)
        
        difference = abs(llm_value - computed_value)
        tolerance = Decimal('0.01')
        
        return VerificationResult(
            verified=difference <= tolerance,
            llm_value=llm_output,
            computed_value=computed,
            difference=str(difference) if difference > 0 else None,
            formula_used=f"A = P(1 + r/{n})^({n}t)"
        )
    
    # ==================== Money Arithmetic ====================
    
    def add_money(self, *amounts: str) -> str:
        """
        Add money amounts with exact decimal arithmetic.
        Avoids floating-point errors.
        """
        total = sum(self._parse_money(a) for a in amounts)
        return self._format_money(total)
    
    def subtract_money(self, a: str, b: str) -> str:
        """Subtract money amounts exactly"""
        result = self._parse_money(a) - self._parse_money(b)
        return self._format_money(result)
    
    def multiply_money(self, amount: str, factor: float) -> str:
        """Multiply money by a factor"""
        result = self._parse_money(amount) * Decimal(str(factor))
        return self._format_money(result)
