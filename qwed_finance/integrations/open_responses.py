"""
Open Responses Integration - Tool call interception for agentic loops
Enables qwed-finance to intercept and verify LLM tool calls before execution
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from enum import Enum
import json

from ..finance_verifier import FinanceVerifier
from ..compliance_guard import ComplianceGuard
from ..calendar_guard import CalendarGuard
from ..derivatives_guard import DerivativesGuard
from ..models.receipt import VerificationReceipt, ReceiptGenerator, VerificationEngine, AuditLog


class ToolCallStatus(Enum):
    """Status of a verified tool call"""
    APPROVED = "approved"      # Verified against LLM claim and passed
    REJECTED = "rejected"      # Verification failed or not possible
    MODIFIED = "modified"      # Args were corrected before approval
    COMPUTED = "computed"      # Result computed but NOT verified against LLM claim
    ERROR = "error"            # System error prevented verification


@dataclass
class VerifiedToolCall:
    """Result of a verified tool call"""
    status: ToolCallStatus
    tool_name: str
    original_args: Dict[str, Any]
    verified_args: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    receipt: Optional[VerificationReceipt] = None
    retry_message: Optional[str] = None


@dataclass
class ToolDefinition:
    """Definition of a financial tool that can be verified"""
    name: str
    description: str
    parameters: Dict[str, Any]
    verification_fn: Optional[Callable] = None


class OpenResponsesIntegration:
    """
    Integration layer for OpenAI Responses API / Open Responses.
    
    Intercepts tool calls from the agentic loop and:
    1. Verifies arguments using appropriate guards
    2. Returns results with verification receipts
    3. Returns structured errors for retry if rejected
    
    Compatible with:
    - OpenAI Responses API
    - qwed-open-responses
    - Any agentic loop using tool calls
    """
    
    def __init__(self):
        self.finance = FinanceVerifier()
        self.compliance = ComplianceGuard()
        self.calendar = CalendarGuard()
        self.derivatives = DerivativesGuard()
        self.audit_log = AuditLog()
        
        # Register verified financial tools
        self.tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register default financial tools with verification"""
        
        # NPV calculation
        self.register_tool(
            name="calculate_npv",
            description="Calculate Net Present Value of cash flows",
            parameters={
                "type": "object",
                "properties": {
                    "cashflows": {"type": "array", "items": {"type": "number"}},
                    "rate": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["cashflows", "rate"]
            },
            verification_fn=self._verify_npv
        )
        
        # Loan payment
        self.register_tool(
            name="calculate_loan_payment",
            description="Calculate monthly loan payment",
            parameters={
                "type": "object",
                "properties": {
                    "principal": {"type": "number", "minimum": 0},
                    "annual_rate": {"type": "number", "minimum": 0, "maximum": 1},
                    "months": {"type": "integer", "minimum": 1}
                },
                "required": ["principal", "annual_rate", "months"]
            },
            verification_fn=self._verify_loan_payment
        )
        
        # AML check
        self.register_tool(
            name="check_aml_compliance",
            description="Check if transaction requires AML flagging",
            parameters={
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "minimum": 0},
                    "country_code": {"type": "string", "pattern": "^[A-Z]{2}$"}
                },
                "required": ["amount", "country_code"]
            },
            verification_fn=self._verify_aml
        )
        
        # Options pricing
        self.register_tool(
            name="price_option",
            description="Calculate Black-Scholes option price",
            parameters={
                "type": "object",
                "properties": {
                    "spot_price": {"type": "number", "minimum": 0},
                    "strike_price": {"type": "number", "minimum": 0},
                    "time_to_expiry": {"type": "number", "minimum": 0},
                    "risk_free_rate": {"type": "number"},
                    "volatility": {"type": "number", "minimum": 0},
                    "option_type": {"type": "string", "enum": ["call", "put"]}
                },
                "required": ["spot_price", "strike_price", "time_to_expiry", 
                           "risk_free_rate", "volatility", "option_type"]
            },
            verification_fn=self._verify_option_price
        )
    
    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        verification_fn: Optional[Callable] = None
    ):
        """Register a tool with optional verification function"""
        self.tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            verification_fn=verification_fn
        )
    
    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible tools schema for the model"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            }
            for tool in self.tools.values()
        ]
    
    def handle_tool_call(
        self,
        tool_name: str,
        arguments: Union[str, Dict[str, Any]]
    ) -> VerifiedToolCall:
        """
        Handle a tool call from the LLM with verification.
        
        Args:
            tool_name: Name of the tool being called
            arguments: Tool arguments (JSON string or dict)
            
        Returns:
            VerifiedToolCall with result or error
        """
        # Parse arguments
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError as e:
                return VerifiedToolCall(
                    status=ToolCallStatus.ERROR,
                    tool_name=tool_name,
                    original_args={},
                    error=f"Invalid JSON arguments: {e}",
                    retry_message="Please provide valid JSON arguments."
                )
        else:
            args = arguments
        
        # Check if tool exists
        if tool_name not in self.tools:
            return VerifiedToolCall(
                status=ToolCallStatus.ERROR,
                tool_name=tool_name,
                original_args=args,
                error=f"Unknown tool: {tool_name}",
                retry_message=f"Available tools: {list(self.tools.keys())}"
            )
        
        tool = self.tools[tool_name]
        
        # If tool has verification function, use it
        if tool.verification_fn:
            try:
                return tool.verification_fn(args)
            except Exception as e:
                return VerifiedToolCall(
                    status=ToolCallStatus.ERROR,
                    tool_name=tool_name,
                    original_args=args,
                    error=f"Verification function failed: {e}",
                    retry_message="Please retry with valid arguments or investigate tool verifier errors.",
                )
        
        # Fail-closed: reject tools without a verification function.
        # QWED philosophy: "Verification decides IF." — no verification = no approval.
        receipt = ReceiptGenerator.create_receipt(
            guard_name=f"OpenResponses.{tool_name}",
            engine=VerificationEngine.DECIMAL,
            llm_output=str(args),
            verified=False,
            computed_value="rejected_missing_verification_fn",
            violations=[f"No verification function registered for tool '{tool_name}'"],
        )
        self.audit_log.log(receipt)

        return VerifiedToolCall(
            status=ToolCallStatus.REJECTED,
            tool_name=tool_name,
            original_args=args,
            receipt=receipt,
            error=(
                f"No verification function registered for tool '{tool_name}'. "
                "All tools must have a verification_fn to be approved."
            ),
            retry_message=(
                "Register a verification function using register_tool() "
                "with a verification_fn parameter."
            )
        )
    
    # ==================== Verification Functions ====================
    
    def _verify_npv(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Compute NPV — returns COMPUTED status (not verified against LLM claim)."""
        cashflows = args.get("cashflows", [])
        rate = args.get("rate", 0)
        
        # Compute NPV using Decimal for exact arithmetic
        from decimal import Decimal, ROUND_HALF_UP
        npv = Decimal('0')
        for t, cf in enumerate(cashflows):
            npv += Decimal(str(cf)) / (Decimal(str(1 + rate)) ** t)
        
        computed_npv = str(npv.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        result = f"${computed_npv}"
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.calculate_npv",
            engine=VerificationEngine.SYMPY,
            llm_output=str(args),
            verified=False,  # Computed, not verified against LLM claim
            computed_value=result,
            formula="NPV = Σ(CFt / (1+r)^t)"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.COMPUTED,
            tool_name="calculate_npv",
            original_args=args,
            verified_args=args,
            result={"npv": result, "verified": False, "computed": True, "verified_against_llm": False},
            receipt=receipt
        )
    
    def _verify_loan_payment(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Compute loan payment — returns COMPUTED status (not verified against LLM claim)."""
        principal = args.get("principal", 0)
        annual_rate = args.get("annual_rate", 0)
        months = args.get("months", 1)
        
        # Compute payment using Decimal for exact arithmetic
        from decimal import Decimal, ROUND_HALF_UP
        P = Decimal(str(principal))
        monthly_rate = Decimal(str(annual_rate)) / 12
        n = months
        
        if monthly_rate == 0:
            payment = P / n
        else:
            one_plus_r = 1 + monthly_rate
            one_plus_r_n = one_plus_r ** n
            payment = P * (monthly_rate * one_plus_r_n) / (one_plus_r_n - 1)
        
        computed_payment = str(payment.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        result = f"${computed_payment}"
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.calculate_loan_payment",
            engine=VerificationEngine.SYMPY,
            llm_output=str(args),
            verified=False,  # Computed, not verified against LLM claim
            computed_value=result,
            formula="PMT = P * [r(1+r)^n] / [(1+r)^n - 1]"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.COMPUTED,
            tool_name="calculate_loan_payment",
            original_args=args,
            verified_args=args,
            result={"monthly_payment": result, "verified": False, "computed": True, "verified_against_llm": False},
            receipt=receipt
        )
    
    def _verify_aml(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Compute AML check — delegates to ComplianceGuard for consistent rules."""
        amount = args.get("amount", 0)
        country_code = args.get("country_code", "US")
        
        # Delegate to ComplianceGuard for consistent high-risk country list
        # (S-06 fix: no more duplicated subset of countries)
        is_high_risk = country_code.upper() in self.compliance.high_risk_countries
        threshold = self.compliance.aml_thresholds.get("USA", 10000)
        needs_flagging = amount >= threshold or is_high_risk
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.check_aml_compliance",
            engine=VerificationEngine.Z3,
            llm_output=str(args),
            verified=False,  # Computed, not verified against LLM claim
            computed_value=str(needs_flagging),
            formula="Flag if: amount >= threshold OR country in HIGH_RISK"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.COMPUTED,
            tool_name="check_aml_compliance",
            original_args=args,
            verified_args=args,
            result={
                "needs_flagging": needs_flagging,
                "reason": "Amount exceeds threshold" if amount >= threshold else
                         "High-risk jurisdiction" if is_high_risk else "Clear",
                "verified": False,
                "computed": True,
                "verified_against_llm": False
            },
            receipt=receipt
        )
    
    def _verify_option_price(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Compute Black-Scholes option price — delegates to DerivativesGuard.
        
        Single source of truth: uses the same mpmath-based implementation
        as DerivativesGuard to ensure deterministic consistency across paths.
        """
        from ..derivatives_guard import DerivativesGuard, OptionType
        from decimal import Decimal
        
        S = args.get("spot_price", 100)
        K = args.get("strike_price", 100)
        T = args.get("time_to_expiry", 1)
        r = args.get("risk_free_rate", 0.05)
        sigma = args.get("volatility", 0.2)
        opt_type = OptionType.CALL if args.get("option_type") == "call" else OptionType.PUT
        
        # Fail-closed: reject non-positive inputs that would cause math errors
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return VerifiedToolCall(
                status=ToolCallStatus.REJECTED,
                tool_name="price_option",
                original_args=args,
                error="spot_price, strike_price, time_to_expiry, and volatility must be > 0",
                retry_message="Provide strictly positive inputs for Black-Scholes pricing.",
            )
        
        # Delegate to DerivativesGuard — single source of truth (mpmath)
        guard = DerivativesGuard()
        bs_result = guard.verify_black_scholes(
            spot_price=S,
            strike_price=K,
            time_to_expiry=T,
            risk_free_rate=r,
            volatility=sigma,
            option_type=opt_type,
            llm_price="$0.00"  # Placeholder — we only need computed_price
        )
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.price_option",
            engine=VerificationEngine.SYMPY,
            llm_output=str(args),
            verified=False,  # Computed, not verified against LLM claim
            computed_value=bs_result.computed_price,
            formula="Black-Scholes: C = S·N(d₁) - K·e^(-rT)·N(d₂)"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.COMPUTED,
            tool_name="price_option",
            original_args=args,
            verified_args=args,
            result={
                "price": bs_result.computed_price,
                "delta": bs_result.greeks["delta"] if bs_result.greeks else None,
                "verified": False,
                "computed": True,
                "verified_against_llm": False
            },
            receipt=receipt
        )
    
    @staticmethod
    def _extract_receipt_meta(
        receipt: Optional[VerificationReceipt],
    ) -> Dict[str, Any]:
        """Extract common metadata from a receipt (or safe defaults)."""
        if receipt is None:
            return {"engine": "unknown", "receipt_id": None, "timestamp": None, "input_hash": None}
        return {
            "engine": receipt.engine_used.value,
            "receipt_id": receipt.receipt_id,
            "input_hash": receipt.input_hash,
            "timestamp": receipt.timestamp,
        }

    def _format_success(
        self, call_id: str, result: VerifiedToolCall, verification: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Format a non-error tool result item."""
        return {
            "type": "tool_result",
            "id": call_id,
            "tool_use_id": result.tool_name,
            "content": {
                "mime_type": "application/json",
                "text": json.dumps({
                    "result": result.result,
                    "verification": verification,
                }),
            },
            "is_error": False,
        }

    def _format_error(
        self, call_id: str, result: VerifiedToolCall,
    ) -> Dict[str, Any]:
        """Format an error tool result item."""
        return {
            "type": "tool_result",
            "id": call_id,
            "tool_use_id": result.tool_name,
            "content": {
                "mime_type": "application/json",
                "text": json.dumps({
                    "error": result.error,
                    "retry_message": result.retry_message,
                    "violations": result.receipt.violations if result.receipt else [],
                }),
            },
            "is_error": True,
        }

    def format_for_responses_api(
        self, 
        result: VerifiedToolCall,
        tool_call_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format result as Open Responses Item for streaming compatibility.
        
        Returns a ToolResultItem that agents can stream properly.
        """
        import uuid
        
        call_id = tool_call_id or f"call_{uuid.uuid4().hex[:12]}"
        meta = self._extract_receipt_meta(result.receipt)
        
        if result.status == ToolCallStatus.APPROVED:
            return self._format_success(call_id, result, {
                "status": "verified",
                "verified": True,
                **meta,
            })

        if result.status == ToolCallStatus.COMPUTED:
            # COMPUTED: result is available but was NOT verified against an LLM claim.
            # Downstream consumers must NOT treat this as "verified".
            return self._format_success(call_id, result, {
                "status": "computed_only",
                "verified": False,
                "note": "Result was computed deterministically but NOT verified against an LLM claim.",
                **meta,
            })

        return self._format_error(call_id, result)
    
    def format_as_item(
        self,
        result: VerifiedToolCall,
        tool_call_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format as a semantic Item for Open Responses streaming.
        
        This is the atomic unit of context in the agentic loop.
        """
        return self.format_for_responses_api(result, tool_call_id)
    
    def get_verification_item(self, receipt: VerificationReceipt) -> Dict[str, Any]:
        """
        Create a standalone verification Item from a receipt.
        
        Useful for audit logging in the conversation context.
        """
        return {
            "type": "verification_receipt",
            "id": receipt.receipt_id,
            "content": {
                "mime_type": "application/json",
                "text": receipt.to_json()
            },
            "metadata": {
                "guard": receipt.guard_name,
                "engine": receipt.engine_used.value,
                "verified": receipt.verified,
                "timestamp": receipt.timestamp
            }
        }

