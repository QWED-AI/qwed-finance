"""
Financial Schemas for QWED-Finance
JSON Schema definitions for banking data validation
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class LoanSchema:
    """Schema for loan verification"""
    principal: float
    annual_rate: float
    term_months: int
    loan_type: str = "fixed"  # "fixed", "variable", "interest_only"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "principal": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Loan principal amount"
                },
                "annual_rate": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Annual interest rate as decimal"
                },
                "term_months": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Loan term in months"
                },
                "loan_type": {
                    "type": "string",
                    "enum": ["fixed", "variable", "interest_only"]
                }
            },
            "required": ["principal", "annual_rate", "term_months"]
        }


@dataclass
class InvestmentSchema:
    """Schema for investment verification"""
    principal: float
    expected_return: float
    time_horizon_years: int
    risk_level: str = "moderate"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "principal": {
                    "type": "number",
                    "minimum": 0
                },
                "expected_return": {
                    "type": "number",
                    "description": "Expected annual return as decimal"
                },
                "time_horizon_years": {
                    "type": "integer",
                    "minimum": 1
                },
                "risk_level": {
                    "type": "string",
                    "enum": ["conservative", "moderate", "aggressive"]
                }
            },
            "required": ["principal", "expected_return", "time_horizon_years"]
        }


@dataclass
class AmortizationSchema:
    """Schema for amortization schedule verification"""
    period: int
    payment: float
    principal_payment: float
    interest_payment: float
    remaining_balance: float
    
    @classmethod
    def schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "period": {"type": "integer", "minimum": 1},
                "payment": {"type": "number", "minimum": 0},
                "principal_payment": {"type": "number", "minimum": 0},
                "interest_payment": {"type": "number", "minimum": 0},
                "remaining_balance": {"type": "number", "minimum": 0}
            },
            "required": ["period", "payment", "principal_payment", 
                        "interest_payment", "remaining_balance"]
        }


# ISO 20022 Message Schemas (simplified)
ISO20022_PAYMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "message_id": {"type": "string"},
        "creation_datetime": {"type": "string", "format": "date-time"},
        "payment_information": {
            "type": "object",
            "properties": {
                "debtor": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "account": {"type": "string"}
                    }
                },
                "creditor": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "account": {"type": "string"}
                    }
                },
                "amount": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number", "minimum": 0},
                        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"}
                    }
                }
            }
        }
    },
    "required": ["message_id", "creation_datetime", "payment_information"]
}
