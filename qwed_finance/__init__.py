"""
QWED-Finance: Deterministic verification for banking and financial AI
"""

from .finance_verifier import FinanceVerifier
from .schemas import LoanSchema, InvestmentSchema, AmortizationSchema

__version__ = "0.1.0"
__all__ = [
    "FinanceVerifier",
    "LoanSchema",
    "InvestmentSchema", 
    "AmortizationSchema",
]
