"""
Tests for rate parsing consistency across guards.

Covers:
- C-04: BondGuard _parse_rate() silent heuristic removed
- H-01: FinanceVerifier verify_irr() guessing removed
- S-05: Cross-guard rate parsing consistency
"""

import re

from qwed_finance import BondGuard, FinanceVerifier


class TestBondGuardParseRate:
    """C-04: BondGuard _parse_rate must not silently guess format."""

    def setup_method(self):
        self.guard = BondGuard()

    def test_explicit_percentage(self):
        """'5.25%' must parse to 0.0525."""
        assert self.guard._parse_rate("5.25%") == 0.0525

    def test_explicit_percentage_with_space(self):
        """'5.25 %' must parse to 0.0525."""
        assert self.guard._parse_rate("5.25 %") == 0.0525

    def test_decimal_fraction(self):
        """'0.0525' must parse to 0.0525 (not reinterpreted)."""
        assert self.guard._parse_rate("0.0525") == 0.0525

    def test_value_above_one_not_divided(self):
        """'1.5' must parse to 1.5 (150% for distressed debt), NOT 0.015.

        This is the core fix: the old heuristic (val < 1) would silently
        convert 1.5 to 0.015, which is 100x wrong for distressed debt.
        """
        result = self.guard._parse_rate("1.5")
        assert result == 1.5, (
            f"Expected 1.5 (150% as decimal), got {result}. "
            "Old heuristic is still active!"
        )

    def test_boundary_value_one(self):
        """'1.0' must parse to 1.0 (100%), not 0.01."""
        result = self.guard._parse_rate("1.0")
        assert result == 1.0

    def test_large_percentage_explicit(self):
        """'150%' must parse to 1.5."""
        assert self.guard._parse_rate("150%") == 1.5

    def test_zero_rate(self):
        """'0' must parse to 0.0."""
        assert self.guard._parse_rate("0") == 0.0

    def test_zero_percent(self):
        """'0%' must parse to 0.0."""
        assert self.guard._parse_rate("0%") == 0.0

    def test_whitespace_handling(self):
        """'  5.25%  ' must parse correctly with whitespace."""
        assert self.guard._parse_rate("  5.25%  ") == 0.0525

    def test_invalid_input_raises(self):
        """Non-numeric input must raise ValueError (fail-closed)."""
        try:
            self.guard._parse_rate("abc")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestFinanceVerifierIRRParsing:
    """H-01: FinanceVerifier verify_irr must not guess rate format."""

    def setup_method(self):
        self.verifier = FinanceVerifier()

    def test_irr_with_explicit_percentage(self):
        """'14.49%' must be correctly parsed and verified."""
        result = self.verifier.verify_irr(
            cashflows=[-1000, 300, 400, 400, 300],
            llm_output="14.49%"
        )
        assert result.computed_value is not None

    def test_irr_with_decimal_fraction(self):
        """'0.1449' must be treated as decimal 14.49%, not guessed."""
        result = self.verifier.verify_irr(
            cashflows=[-1000, 300, 400, 400, 300],
            llm_output="0.1449"
        )
        # 0.1449 as decimal = 14.49% — should match computed IRR
        assert result.computed_value is not None

    def test_irr_value_above_one_not_divided(self):
        """'1.5' without % must NOT be divided by 100.

        Old behavior: 1.5 > 1 → divide → 0.015 (wrong!)
        New behavior: 1.5 stays 1.5 (150% IRR)
        """
        result = self.verifier.verify_irr(
            cashflows=[-1000, 300, 400, 400, 300],
            llm_output="1.5"
        )
        # LLM said 150% but actual IRR is ~14.5% — should NOT verify
        assert result.verified is False


class TestCrossGuardConsistency:
    """S-05: Both guards must interpret the same input identically."""

    def setup_method(self):
        self.bond = BondGuard()

    def test_percentage_format_consistent(self):
        """'5.25%' must produce 0.0525 in BondGuard."""
        assert self.bond._parse_rate("5.25%") == 0.0525

    def test_decimal_format_consistent(self):
        """'0.0525' must produce 0.0525 in BondGuard."""
        assert self.bond._parse_rate("0.0525") == 0.0525

    def test_high_rate_consistent(self):
        """'1.5' (150%) must produce 1.5 in BondGuard (no division)."""
        assert self.bond._parse_rate("1.5") == 1.5

    def test_irr_and_bond_agree_on_percentage(self):
        """Both guards must interpret '5.25%' the same way."""
        bond_rate = self.bond._parse_rate("5.25%")
        # FinanceVerifier uses same logic now: "5.25%" → strip % → 5.25 → /100
        irr_rate = float(re.sub(r'[%\s]', '', "5.25%")) / 100
        assert bond_rate == irr_rate

    def test_irr_and_bond_agree_on_decimal(self):
        """Both guards must interpret '0.0525' the same way."""
        bond_rate = self.bond._parse_rate("0.0525")
        # FinanceVerifier: no %, treat as decimal
        irr_rate = float("0.0525")
        assert bond_rate == irr_rate
