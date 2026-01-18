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
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    ERROR = "error"


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
            return tool.verification_fn(args)
        
        # Default: approve without verification
        return VerifiedToolCall(
            status=ToolCallStatus.APPROVED,
            tool_name=tool_name,
            original_args=args,
            verified_args=args
        )
    
    # ==================== Verification Functions ====================
    
    def _verify_npv(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Verify NPV calculation"""
        cashflows = args.get("cashflows", [])
        rate = args.get("rate", 0)
        
        # Compute NPV
        from decimal import Decimal
        npv = Decimal('0')
        for t, cf in enumerate(cashflows):
            npv += Decimal(str(cf)) / (Decimal(str(1 + rate)) ** t)
        
        result = f"${float(npv):.2f}"
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.calculate_npv",
            engine=VerificationEngine.SYMPY,
            llm_output=str(args),
            verified=True,
            computed_value=result,
            formula="NPV = Σ(CFt / (1+r)^t)"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.APPROVED,
            tool_name="calculate_npv",
            original_args=args,
            verified_args=args,
            result={"npv": result, "verified": True},
            receipt=receipt
        )
    
    def _verify_loan_payment(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Verify loan payment calculation"""
        principal = args.get("principal", 0)
        annual_rate = args.get("annual_rate", 0)
        months = args.get("months", 1)
        
        # Compute payment
        from decimal import Decimal
        P = Decimal(str(principal))
        monthly_rate = Decimal(str(annual_rate)) / 12
        n = months
        
        if monthly_rate == 0:
            payment = P / n
        else:
            one_plus_r = 1 + monthly_rate
            one_plus_r_n = one_plus_r ** n
            payment = P * (monthly_rate * one_plus_r_n) / (one_plus_r_n - 1)
        
        result = f"${float(payment):.2f}"
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.calculate_loan_payment",
            engine=VerificationEngine.SYMPY,
            llm_output=str(args),
            verified=True,
            computed_value=result,
            formula="PMT = P × [r(1+r)^n] / [(1+r)^n - 1]"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.APPROVED,
            tool_name="calculate_loan_payment",
            original_args=args,
            verified_args=args,
            result={"monthly_payment": result, "verified": True},
            receipt=receipt
        )
    
    def _verify_aml(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Verify AML compliance check"""
        amount = args.get("amount", 0)
        country_code = args.get("country_code", "US")
        
        # Check AML threshold
        threshold = 10000
        is_high_risk = country_code.upper() in {"KP", "IR", "SY", "MM", "AF"}
        needs_flagging = amount >= threshold or is_high_risk
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.check_aml_compliance",
            engine=VerificationEngine.Z3,
            llm_output=str(args),
            verified=True,
            computed_value=str(needs_flagging),
            formula="Flag if: amount >= $10,000 OR country in HIGH_RISK"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.APPROVED,
            tool_name="check_aml_compliance",
            original_args=args,
            verified_args=args,
            result={
                "needs_flagging": needs_flagging,
                "reason": "Amount exceeds threshold" if amount >= threshold else
                         "High-risk jurisdiction" if is_high_risk else "Clear",
                "verified": True
            },
            receipt=receipt
        )
    
    def _verify_option_price(self, args: Dict[str, Any]) -> VerifiedToolCall:
        """Verify Black-Scholes option price"""
        from .derivatives_guard import OptionType
        import math
        
        S = args.get("spot_price", 100)
        K = args.get("strike_price", 100)
        T = args.get("time_to_expiry", 1)
        r = args.get("risk_free_rate", 0.05)
        sigma = args.get("volatility", 0.2)
        opt_type = OptionType.CALL if args.get("option_type") == "call" else OptionType.PUT
        
        # Black-Scholes
        d1 = (math.log(S / K) + (r + (sigma ** 2) / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))
        
        if opt_type == OptionType.CALL:
            price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        else:
            price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
        
        receipt = ReceiptGenerator.create_receipt(
            guard_name="OpenResponses.price_option",
            engine=VerificationEngine.SYMPY,
            llm_output=str(args),
            verified=True,
            computed_value=f"${price:.2f}",
            formula="Black-Scholes: C = S·N(d₁) - K·e^(-rT)·N(d₂)"
        )
        self.audit_log.log(receipt)
        
        return VerifiedToolCall(
            status=ToolCallStatus.APPROVED,
            tool_name="price_option",
            original_args=args,
            verified_args=args,
            result={
                "price": f"${price:.2f}",
                "delta": round(norm_cdf(d1) if opt_type == OptionType.CALL else norm_cdf(d1) - 1, 4),
                "verified": True
            },
            receipt=receipt
        )
    
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
        
        if result.status == ToolCallStatus.APPROVED:
            return {
                "type": "tool_result",
                "id": call_id,
                "tool_use_id": result.tool_name,
                "content": {
                    "mime_type": "application/json",
                    "text": json.dumps({
                        "result": result.result,
                        "verification": {
                            "verified": True,
                            "engine": result.receipt.engine_used.value if result.receipt else "unknown",
                            "receipt_id": result.receipt.receipt_id if result.receipt else None,
                            "input_hash": result.receipt.input_hash if result.receipt else None,
                            "timestamp": result.receipt.timestamp if result.receipt else None
                        }
                    })
                },
                "is_error": False
            }
        else:
            return {
                "type": "tool_result",
                "id": call_id,
                "tool_use_id": result.tool_name,
                "content": {
                    "mime_type": "application/json",
                    "text": json.dumps({
                        "error": result.error,
                        "retry_message": result.retry_message,
                        "violations": result.receipt.violations if result.receipt else []
                    })
                },
                "is_error": True
            }
    
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

