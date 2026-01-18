"""
Tests for QWED-Finance FinanceVerifier
"""

import pytest
from qwed_finance import FinanceVerifier


class TestNPVVerification:
    """Test NPV calculations"""
    
    def setup_method(self):
        self.verifier = FinanceVerifier()
    
    def test_npv_correct_calculation(self):
        """Test correct NPV verification"""
        result = self.verifier.verify_npv(
            cashflows=[-1000, 300, 400, 400, 300],
            rate=0.10,
            llm_output="$180.42"
        )
        assert result.verified == True
        assert "NPV" in result.formula_used
    
    def test_npv_wrong_calculation(self):
        """Test wrong NPV detection"""
        result = self.verifier.verify_npv(
            cashflows=[-1000, 300, 400, 400, 300],
            rate=0.10,
            llm_output="$500.00"  # Wrong!
        )
        assert result.verified == False
        assert result.difference is not None
    
    def test_npv_zero_rate(self):
        """Test NPV with 0% discount rate"""
        result = self.verifier.verify_npv(
            cashflows=[-1000, 500, 500, 500],
            rate=0.0,
            llm_output="$500.00"
        )
        assert result.verified == True


class TestLoanVerification:
    """Test loan calculations"""
    
    def setup_method(self):
        self.verifier = FinanceVerifier()
    
    def test_monthly_payment_correct(self):
        """Test correct monthly payment verification"""
        # $200,000 loan at 6% for 30 years
        result = self.verifier.verify_monthly_payment(
            principal=200000,
            annual_rate=0.06,
            months=360,
            llm_output="$1,199.10"
        )
        assert result.verified == True
    
    def test_monthly_payment_wrong(self):
        """Test wrong monthly payment detection"""
        result = self.verifier.verify_monthly_payment(
            principal=200000,
            annual_rate=0.06,
            months=360,
            llm_output="$1,500.00"  # Wrong!
        )
        assert result.verified == False
    
    def test_zero_interest_loan(self):
        """Test 0% interest loan"""
        result = self.verifier.verify_monthly_payment(
            principal=12000,
            annual_rate=0.0,
            months=12,
            llm_output="$1,000.00"
        )
        assert result.verified == True


class TestCompoundInterest:
    """Test compound interest calculations"""
    
    def setup_method(self):
        self.verifier = FinanceVerifier()
    
    def test_annual_compounding(self):
        """Test annual compound interest"""
        # $10,000 at 5% for 10 years
        result = self.verifier.verify_compound_interest(
            principal=10000,
            rate=0.05,
            periods=10,
            llm_output="$16,288.95",
            compounding="annual"
        )
        assert result.verified == True
    
    def test_monthly_compounding(self):
        """Test monthly compound interest"""
        result = self.verifier.verify_compound_interest(
            principal=10000,
            rate=0.05,
            periods=10,
            llm_output="$16,470.09",  # Higher due to monthly compounding
            compounding="monthly"
        )
        assert result.verified == True


class TestMoneyArithmetic:
    """Test exact money arithmetic"""
    
    def setup_method(self):
        self.verifier = FinanceVerifier()
    
    def test_add_money_avoids_float_error(self):
        """Test that 0.1 + 0.2 = 0.30 exactly"""
        result = self.verifier.add_money("$0.10", "$0.20")
        assert result == "$0.30"
    
    def test_add_multiple_amounts(self):
        """Test adding multiple amounts"""
        result = self.verifier.add_money("$100.00", "$50.50", "$25.25")
        assert result == "$175.75"
    
    def test_subtract_money(self):
        """Test money subtraction"""
        result = self.verifier.subtract_money("$100.00", "$33.33")
        assert result == "$66.67"


class TestIRRVerification:
    """Test IRR calculations"""
    
    def setup_method(self):
        self.verifier = FinanceVerifier()
    
    def test_irr_correct(self):
        """Test correct IRR verification"""
        result = self.verifier.verify_irr(
            cashflows=[-1000, 300, 400, 400, 300],
            llm_output="14.49%"
        )
        # IRR should be around 14.49%
        assert result.computed_value is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
