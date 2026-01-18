"""
QWED-Finance: Deterministic verification for banking and financial AI

Five Guards for enterprise-grade verification:
- ComplianceGuard: KYC/AML regulatory logic (Z3)
- CalendarGuard: Day count conventions (SymPy)
- DerivativesGuard: Options pricing & margin (Black-Scholes)
- MessageGuard: ISO 20022 / SWIFT validation (XML Schema)
- QueryGuard: SQL safety & table access (SQLGlot AST)
"""

from .finance_verifier import FinanceVerifier, VerificationResult
from .compliance_guard import ComplianceGuard, ComplianceResult, RiskLevel, Jurisdiction
from .calendar_guard import CalendarGuard, CalendarResult, DayCountConvention
from .derivatives_guard import DerivativesGuard, DerivativesResult, OptionType
from .message_guard import MessageGuard, MessageResult, MessageType, SwiftMtType
from .query_guard import QueryGuard, QueryResult, QueryRisk
from .schemas import LoanSchema, InvestmentSchema, AmortizationSchema

__version__ = "0.3.0"
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
    
    # Schemas
    "LoanSchema",
    "InvestmentSchema", 
    "AmortizationSchema",
]
