"""
QWED-Finance: Deterministic verification for banking and financial AI

Three Guards for enterprise-grade verification:
- ComplianceGuard: KYC/AML regulatory logic (Z3)
- CalendarGuard: Day count conventions (SymPy)
- DerivativesGuard: Options pricing & margin (Black-Scholes)
"""

from .finance_verifier import FinanceVerifier, VerificationResult
from .compliance_guard import ComplianceGuard, ComplianceResult, RiskLevel, Jurisdiction
from .calendar_guard import CalendarGuard, CalendarResult, DayCountConvention
from .derivatives_guard import DerivativesGuard, DerivativesResult, OptionType
from .schemas import LoanSchema, InvestmentSchema, AmortizationSchema

__version__ = "0.2.0"
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
    
    # Schemas
    "LoanSchema",
    "InvestmentSchema", 
    "AmortizationSchema",
]
