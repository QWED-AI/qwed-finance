"""
QWED-Finance: Deterministic verification for banking and financial AI

v1.0.0 - Production Ready

Five Guards + Audit Trail + Integrations:
- ComplianceGuard: KYC/AML regulatory logic (Z3)
- CalendarGuard: Day count conventions (SymPy)
- DerivativesGuard: Options pricing & margin (Black-Scholes)
- MessageGuard: ISO 20022 / SWIFT validation (XML Schema)
- QueryGuard: SQL safety & table access (SQLGlot AST)
- CrossGuard: Multi-layer verification integration
- VerificationReceipt: Cryptographic audit trail
- OpenResponsesIntegration: Agentic tool call verification
- UCPIntegration: Payment token verification
"""

from .finance_verifier import FinanceVerifier, VerificationResult
from .compliance_guard import ComplianceGuard, ComplianceResult, RiskLevel, Jurisdiction
from .calendar_guard import CalendarGuard, CalendarResult, DayCountConvention
from .derivatives_guard import DerivativesGuard, DerivativesResult, OptionType
from .message_guard import MessageGuard, MessageResult, MessageType, SwiftMtType
from .query_guard import QueryGuard, QueryResult, QueryRisk
from .cross_guard import CrossGuard, CrossGuardResult
from .models.receipt import (
    VerificationReceipt, 
    VerificationEngine, 
    VerificationStatus,
    ReceiptGenerator,
    AuditLog
)
from .integrations import (
    OpenResponsesIntegration,
    VerifiedToolCall,
    ToolCallStatus,
    UCPIntegration,
    PaymentVerificationResult,
    PaymentStatus,
    UCPAction
)
from .schemas import LoanSchema, InvestmentSchema, AmortizationSchema

__version__ = "1.0.0"
__all__ = [
    # Core Verifier
    "FinanceVerifier",
    "VerificationResult",
    
    # Compliance Guard
    "ComplianceGuard",
    "ComplianceResult",
    "RiskLevel",
    "Jurisdiction",
    
    # Calendar Guard
    "CalendarGuard",
    "CalendarResult",
    "DayCountConvention",
    
    # Derivatives Guard
    "DerivativesGuard",
    "DerivativesResult",
    "OptionType",
    
    # Message Guard
    "MessageGuard",
    "MessageResult",
    "MessageType",
    "SwiftMtType",
    
    # Query Guard
    "QueryGuard",
    "QueryResult",
    "QueryRisk",
    
    # Cross Guard
    "CrossGuard",
    "CrossGuardResult",
    
    # Audit Trail
    "VerificationReceipt",
    "VerificationEngine",
    "VerificationStatus",
    "ReceiptGenerator",
    "AuditLog",
    
    # Open Responses Integration
    "OpenResponsesIntegration",
    "VerifiedToolCall",
    "ToolCallStatus",
    
    # UCP Integration
    "UCPIntegration",
    "PaymentVerificationResult",
    "PaymentStatus",
    "UCPAction",
    
    # Schemas
    "LoanSchema",
    "InvestmentSchema", 
    "AmortizationSchema",
]
