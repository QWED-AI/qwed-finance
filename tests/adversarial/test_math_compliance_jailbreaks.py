"""
Adversarial Tests - Math and Compliance Guard Jailbreaks
"""

import pytest
from qwed_finance import FinanceVerifier, ComplianceGuard


class TestFloatingPointAttacks:
    """
    Test edge cases designed to exploit floating-point precision.
    These simulate an LLM outputting boundary values to confuse verification.
    """
    
    def setup_method(self):
        self.verifier = FinanceVerifier()
    
    def test_floating_point_boundary(self):
        """Classic 0.1 + 0.2 != 0.3 attack"""
        # If verifier uses float internally, this could fail
        result = self.verifier.add_money("$0.10", "$0.20")
        assert result == "$0.30"  # Must be exact
    
    def test_large_number_precision(self):
        """Large numbers that lose precision in float64"""
        # 2^53 + 1 cannot be represented exactly in float64
        large_num = 9007199254740993  # 2^53 + 1
        result = self.verifier.add_money(f"${large_num}", "$0.00")
        # Should handle large numbers correctly
        # Should handle large numbers correctly
        # The result includes commas for formatting
        assert "9,007,199,254,740,993" in result
    
    def test_very_small_number(self):
        """Numbers smaller than machine epsilon"""
        result = self.verifier.add_money("$0.001", "$0.001")
        # Our precision is 2 decimal places, so this should round
        assert result == "$0.00"  # Rounded to 2 decimals
    
    def test_currency_overflow(self):
        """Extremely large currency amount"""
        huge = "999999999999999999.99"
        result = self.verifier.add_money(f"${huge}", "$0.01")
        assert "$1,000,000,000,000,000,000.00" in result
    
    def test_negative_money(self):
        """Negative money amounts (should work for balances)"""
        result = self.verifier.subtract_money("$100.00", "$150.00")
        assert "-$50.00" in result or "$-50.00" in result or "-50" in result


class TestComplianceGuardBypasses:
    """
    Test attempts to bypass compliance rules.
    """
    
    def setup_method(self):
        self.guard = ComplianceGuard()
    
    def test_amount_just_under_threshold(self):
        """Amount at $9,999.99 should NOT trigger AML"""
        result = self.guard.verify_aml_flag(
            amount=9999.99,
            country_code="US",
            llm_flagged=False
        )
        assert result.compliant == True  # Should NOT flag
    
    def test_amount_at_threshold(self):
        """Amount at exactly $10,000 MUST trigger AML"""
        result = self.guard.verify_aml_flag(
            amount=10000.00,
            country_code="US",
            llm_flagged=False  # LLM didn't flag it
        )
        assert result.compliant == False  # LLM was wrong!
    
    def test_amount_just_over_threshold(self):
        """Amount at $10,000.01 MUST trigger AML"""
        result = self.guard.verify_aml_flag(
            amount=10000.01,
            country_code="US",
            llm_flagged=True
        )
        assert result.compliant == True
    
    def test_structuring_detection(self):
        """Multiple transactions just under threshold (structuring)"""
        # This tests a single transaction, but the concept applies
        # In production, you'd aggregate transactions
        result = self.guard.verify_aml_flag(
            amount=9500,
            country_code="US",
            llm_flagged=False
        )
        # Single transaction under threshold is compliant
        assert result.compliant == True
    
    def test_high_risk_country_low_amount(self):
        """Low amount from high-risk country MUST flag"""
        result = self.guard.verify_aml_flag(
            amount=100,  # Small amount
            country_code="KP",  # North Korea - sanctioned
            llm_flagged=False
        )
        assert result.compliant == False  # Must flag regardless of amount
    
    def test_case_sensitivity_country(self):
        """Country code case should be normalized"""
        result1 = self.guard.verify_aml_flag(100, "kp", True)
        result2 = self.guard.verify_aml_flag(100, "KP", True)
        assert result1.compliant == result2.compliant


class TestKYCBypasses:
    """Test KYC verification edge cases"""
    
    def setup_method(self):
        self.guard = ComplianceGuard()
    
    def test_incomplete_kyc_approved(self):
        """LLM approves with incomplete KYC - must reject"""
        result = self.guard.verify_kyc_complete(
            has_id=True,
            has_address_proof=False,  # Missing!
            has_tax_id=False,
            llm_approved=True,  # LLM incorrectly approved
            transaction_type="standard"
        )
        assert result.compliant == False
        assert "KYC" in result.rule_violated or "incomplete" in str(result.proof).lower()
    
    def test_simplified_kyc_id_only(self):
        """Simplified KYC only requires ID"""
        result = self.guard.verify_kyc_complete(
            has_id=True,
            has_address_proof=False,
            has_tax_id=False,
            llm_approved=True,
            transaction_type="simplified"
        )
        assert result.compliant == True  # Only ID required for simplified
    
    def test_enhanced_kyc_full_docs(self):
        """Enhanced KYC requires all documents"""
        result = self.guard.verify_kyc_complete(
            has_id=True,
            has_address_proof=True,
            has_tax_id=False,  # Missing tax ID for enhanced
            llm_approved=True,
            transaction_type="enhanced"
        )
        assert result.compliant == False


class TestSanctionsEvasion:
    """Test sanctions screening edge cases"""
    
    def setup_method(self):
        self.guard = ComplianceGuard()
    
    def test_sanctioned_entity_approved(self):
        """Sanctioned entity MUST be blocked"""
        result = self.guard.verify_sanctions_check(
            entity_name="ACME Corp",
            is_on_sanctions_list=True,
            llm_approved=True  # LLM incorrectly approved
        )
        assert result.compliant == False
        assert "OFAC" in result.rule_violated or "SANCTIONS" in result.rule_violated
    
    def test_clear_entity_approved(self):
        """Non-sanctioned entity should be allowed"""
        result = self.guard.verify_sanctions_check(
            entity_name="Legitimate Business Inc",
            is_on_sanctions_list=False,
            llm_approved=True
        )
        assert result.compliant == True
    
    def test_clear_entity_rejected(self):
        """Non-sanctioned entity incorrectly rejected"""
        result = self.guard.verify_sanctions_check(
            entity_name="Legitimate Business Inc",
            is_on_sanctions_list=False,
            llm_approved=False  # LLM rejected a good entity
        )
        # This is a false positive - compliant but unnecessary rejection
        assert result.compliant == True  # The check itself is compliant


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
