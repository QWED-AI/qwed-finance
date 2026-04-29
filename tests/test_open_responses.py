"""
Tests for OpenResponsesIntegration fail-closed behavior.

Covers:
- S-01: Tools without verification_fn must be REJECTED (not APPROVED)
- S-02: Built-in verification functions must use COMPUTED status (not APPROVED)
- S-06: AML high-risk country list must match ComplianceGuard
"""


import re

from qwed_finance.integrations.open_responses import (
    OpenResponsesIntegration,
    ToolCallStatus,
    VerifiedToolCall,
)
from qwed_finance.compliance_guard import ComplianceGuard


class TestFailClosedDefault:
    """S-01: Tools without verification_fn must be REJECTED."""

    def setup_method(self):
        self.integration = OpenResponsesIntegration()

    def test_unregistered_tool_returns_error(self):
        """Calling a tool that doesn't exist returns ERROR."""
        result = self.integration.handle_tool_call(
            "nonexistent_tool", {"foo": "bar"}
        )
        assert result.status == ToolCallStatus.ERROR
        assert "Unknown tool" in result.error

    def test_tool_without_verification_fn_is_rejected(self):
        """S-01: A tool registered without verification_fn must be REJECTED."""
        self.integration.register_tool(
            name="transfer_funds",
            description="Transfer money between accounts",
            parameters={"amount": {"type": "number"}},
            # NO verification_fn
        )

        result = self.integration.handle_tool_call(
            "transfer_funds", {"amount": 999999999}
        )

        assert result.status == ToolCallStatus.REJECTED
        assert result.error is not None
        assert "verification function" in result.error.lower()
        assert result.verified_args is None

    def test_tool_without_verification_fn_has_audit_receipt(self):
        """Rejected tools should produce audit receipts for compliance."""
        self.integration.register_tool(
            name="dangerous_tool",
            description="No verification",
            parameters={},
        )

        result = self.integration.handle_tool_call(
            "dangerous_tool", {"action": "delete_everything"}
        )

        assert result.status == ToolCallStatus.REJECTED
        assert result.receipt is not None
        assert result.receipt.verified is False

    def test_tool_with_verification_fn_is_not_rejected(self):
        """A tool WITH verification_fn should not be REJECTED."""
        def dummy_verify(args):
            return VerifiedToolCall(
                status=ToolCallStatus.APPROVED,
                tool_name="safe_tool",
                original_args=args,
                verified_args=args,
            )

        self.integration.register_tool(
            name="safe_tool",
            description="Has verification",
            parameters={},
            verification_fn=dummy_verify,
        )

        result = self.integration.handle_tool_call("safe_tool", {"x": 1})
        assert result.status == ToolCallStatus.APPROVED

    def test_invalid_json_returns_error(self):
        """Malformed JSON arguments return ERROR."""
        result = self.integration.handle_tool_call(
            "calculate_npv", "not valid json{{"
        )
        assert result.status == ToolCallStatus.ERROR
        assert "Invalid JSON" in result.error


class TestComputedStatus:
    """S-02: Built-in functions must return COMPUTED, not APPROVED."""

    def setup_method(self):
        self.integration = OpenResponsesIntegration()

    def test_npv_returns_computed(self):
        """NPV tool call must return COMPUTED status."""
        result = self.integration.handle_tool_call(
            "calculate_npv",
            {"cashflows": [-1000, 300, 400, 500], "rate": 0.1},
        )

        assert result.status == ToolCallStatus.COMPUTED
        assert result.result is not None
        assert result.result["computed"] is True
        assert result.result["verified_against_llm"] is False

    def test_npv_receipt_not_verified(self):
        """NPV receipt must show verified=False."""
        result = self.integration.handle_tool_call(
            "calculate_npv",
            {"cashflows": [-1000, 300, 400, 500], "rate": 0.1},
        )

        assert result.receipt is not None
        assert result.receipt.verified is False

    def test_loan_payment_returns_computed(self):
        """Loan payment tool call must return COMPUTED status."""
        result = self.integration.handle_tool_call(
            "calculate_loan_payment",
            {"principal": 100000, "annual_rate": 0.06, "months": 360},
        )

        assert result.status == ToolCallStatus.COMPUTED
        assert result.result["computed"] is True
        assert result.result["verified_against_llm"] is False
        assert result.receipt.verified is False

    def test_aml_returns_computed(self):
        """AML check tool call must return COMPUTED status."""
        result = self.integration.handle_tool_call(
            "check_aml_compliance",
            {"amount": 15000, "country_code": "US"},
        )

        assert result.status == ToolCallStatus.COMPUTED
        assert result.result["computed"] is True
        assert result.result["verified_against_llm"] is False
        assert result.receipt.verified is False

    def test_option_price_returns_computed(self):
        """Option pricing tool call must return COMPUTED status."""
        result = self.integration.handle_tool_call(
            "price_option",
            {
                "spot_price": 100,
                "strike_price": 105,
                "time_to_expiry": 0.5,
                "risk_free_rate": 0.05,
                "volatility": 0.2,
                "option_type": "call",
            },
        )

        assert result.status == ToolCallStatus.COMPUTED
        assert result.result["computed"] is True
        assert result.result["verified_against_llm"] is False
        assert result.receipt.verified is False

    def test_no_builtin_tool_returns_approved(self):
        """No built-in tool should return APPROVED (they only compute)."""
        builtin_tools = [
            ("calculate_npv", {"cashflows": [-100, 50, 60], "rate": 0.1}),
            ("calculate_loan_payment", {"principal": 10000, "annual_rate": 0.05, "months": 12}),
            ("check_aml_compliance", {"amount": 5000, "country_code": "US"}),
            ("price_option", {
                "spot_price": 100, "strike_price": 100,
                "time_to_expiry": 1, "risk_free_rate": 0.05,
                "volatility": 0.2, "option_type": "call",
            }),
        ]

        for tool_name, args in builtin_tools:
            result = self.integration.handle_tool_call(tool_name, args)
            assert result.status == ToolCallStatus.COMPUTED, (
                f"{tool_name} returned {result.status} but should return COMPUTED"
            )


class TestAMLCountryConsistency:
    """S-06: Integration must use same country list as ComplianceGuard."""

    def setup_method(self):
        self.integration = OpenResponsesIntegration()
        self.compliance = ComplianceGuard()

    def test_yemen_flagged_via_integration(self):
        """Yemen (YE) must be flagged via integration path."""
        result = self.integration.handle_tool_call(
            "check_aml_compliance",
            {"amount": 5000, "country_code": "YE"},
        )
        assert result.result["needs_flagging"] is True

    def test_venezuela_flagged_via_integration(self):
        """Venezuela (VE) must be flagged via integration path."""
        result = self.integration.handle_tool_call(
            "check_aml_compliance",
            {"amount": 5000, "country_code": "VE"},
        )
        assert result.result["needs_flagging"] is True

    def test_pakistan_flagged_via_integration(self):
        """Pakistan (PK) must be flagged via integration path."""
        result = self.integration.handle_tool_call(
            "check_aml_compliance",
            {"amount": 5000, "country_code": "PK"},
        )
        assert result.result["needs_flagging"] is True

    def test_all_high_risk_countries_match(self):
        """Every country in ComplianceGuard.high_risk_countries must be flagged."""
        for country in self.compliance.high_risk_countries:
            result = self.integration.handle_tool_call(
                "check_aml_compliance",
                {"amount": 1, "country_code": country},  # Below $ threshold
            )
            assert result.result["needs_flagging"] is True, (
                f"Country {country} not flagged via integration but is in "
                f"ComplianceGuard.high_risk_countries"
            )

    def test_safe_country_not_flagged(self):
        """A safe country below threshold should NOT be flagged."""
        result = self.integration.handle_tool_call(
            "check_aml_compliance",
            {"amount": 5000, "country_code": "US"},
        )
        assert result.result["needs_flagging"] is False


class TestFormatForResponsesAPI:
    """Verify format_for_responses_api handles COMPUTED correctly."""

    def setup_method(self):
        self.integration = OpenResponsesIntegration()

    def test_computed_result_shows_computed_only_status(self):
        """COMPUTED results must show status='computed_only' in output."""
        result = self.integration.handle_tool_call(
            "calculate_npv",
            {"cashflows": [-100, 50, 60], "rate": 0.1},
        )

        formatted = self.integration.format_for_responses_api(result)

        assert formatted["is_error"] is False
        import json
        content = json.loads(formatted["content"]["text"])
        assert content["verification"]["status"] == "computed_only"
        assert content["verification"]["verified"] is False

    def test_rejected_result_is_error(self):
        """REJECTED results must be flagged as errors."""
        self.integration.register_tool(
            name="unverified_tool",
            description="No verification",
            parameters={},
        )
        result = self.integration.handle_tool_call("unverified_tool", {})
        formatted = self.integration.format_for_responses_api(result)

        assert formatted["is_error"] is True


class TestNPVPrecision:
    """Verify NPV output preserves Decimal precision (S-04 partial fix)."""

    def setup_method(self):
        self.integration = OpenResponsesIntegration()

    def test_npv_no_float_in_output(self):
        """NPV result string must not exhibit float artifacts like 0.30000000000000004."""
        result = self.integration.handle_tool_call(
            "calculate_npv",
            {"cashflows": [-100, 50, 60], "rate": 0.1},
        )

        npv_str = result.result["npv"]
        # Should be currency-formatted with exactly 2 decimal places
        assert re.fullmatch(r"\$-?\d+\.\d{2}", npv_str), (
            f"Unexpected NPV currency format (possible precision leak): {npv_str}"
        )


class TestVerificationFnErrorBoundary:
    """Verify that a crashing verification_fn returns ERROR, not exception."""

    def setup_method(self):
        self.integration = OpenResponsesIntegration()

    def test_crashing_verification_fn_returns_error(self):
        """A verification_fn that raises should return ERROR status."""
        def crashing_verify(args):
            raise ValueError("Something went wrong")

        self.integration.register_tool(
            name="crashing_tool",
            description="Will crash",
            parameters={},
            verification_fn=crashing_verify,
        )

        result = self.integration.handle_tool_call("crashing_tool", {"x": 1})
        assert result.status == ToolCallStatus.ERROR
        assert "Verification function failed" in result.error


class TestBlackScholesInputGuard:
    """Verify Black-Scholes rejects zero/negative inputs."""

    def setup_method(self):
        self.integration = OpenResponsesIntegration()

    def test_zero_volatility_rejected(self):
        """Volatility=0 would cause ZeroDivisionError — must be REJECTED."""
        result = self.integration.handle_tool_call(
            "price_option",
            {
                "spot_price": 100, "strike_price": 100,
                "time_to_expiry": 1, "risk_free_rate": 0.05,
                "volatility": 0, "option_type": "call",
            },
        )
        assert result.status == ToolCallStatus.REJECTED
        assert "must be > 0" in result.error

    def test_zero_time_rejected(self):
        """time_to_expiry=0 would cause ZeroDivisionError — must be REJECTED."""
        result = self.integration.handle_tool_call(
            "price_option",
            {
                "spot_price": 100, "strike_price": 100,
                "time_to_expiry": 0, "risk_free_rate": 0.05,
                "volatility": 0.2, "option_type": "call",
            },
        )
        assert result.status == ToolCallStatus.REJECTED

    def test_negative_spot_rejected(self):
        """Negative spot price is nonsensical — must be REJECTED."""
        result = self.integration.handle_tool_call(
            "price_option",
            {
                "spot_price": -100, "strike_price": 100,
                "time_to_expiry": 1, "risk_free_rate": 0.05,
                "volatility": 0.2, "option_type": "call",
            },
        )
        assert result.status == ToolCallStatus.REJECTED
