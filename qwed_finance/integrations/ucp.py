"""
UCP Integration - Payment token verification for e-commerce flows
Ensures payment messages are verified before checkout proceeds
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum

from ..compliance_guard import ComplianceGuard
from ..message_guard import MessageGuard, MessageType
from ..query_guard import QueryGuard
from ..cross_guard import CrossGuard
from ..models.receipt import VerificationReceipt, ReceiptGenerator, VerificationEngine, AuditLog


class UCPAction(Enum):
    """UCP transaction actions"""
    INITIATE_CHECKOUT = "initiate_checkout"
    PROCESS_PAYMENT = "process_payment"
    CONFIRM_ORDER = "confirm_order"
    REFUND = "refund"
    CANCEL = "cancel"


class PaymentStatus(Enum):
    """Payment verification status"""
    APPROVED = "approved"
    BLOCKED = "blocked"
    PENDING_REVIEW = "pending_review"
    ERROR = "error"


@dataclass
class PaymentVerificationResult:
    """Result of payment token verification"""
    status: PaymentStatus
    action: UCPAction
    can_proceed: bool
    violations: List[str]
    receipts: List[VerificationReceipt]
    error: Optional[str] = None


class UCPIntegration:
    """
    Universal Commerce Protocol integration for qwed-finance.
    
    Intercepts UCP payment flows and verifies:
    1. Payment message structure (ISO 20022 if applicable)
    2. Compliance rules (AML/KYC)
    3. Business logic (amount limits, currency validation)
    
    Compatible with:
    - qwed-ucp middleware
    - Stripe/Plaid payment flows
    - ISO 20022 bank transfers
    """
    
    def __init__(
        self,
        max_transaction_amount: float = 1000000,
        allowed_currencies: List[str] = None,
        require_kyc: bool = True
    ):
        """
        Initialize UCP integration.
        
        Args:
            max_transaction_amount: Maximum allowed transaction
            allowed_currencies: List of allowed currency codes
            require_kyc: Whether to require KYC for transactions
        """
        self.max_amount = max_transaction_amount
        self.allowed_currencies = allowed_currencies or ["USD", "EUR", "GBP"]
        self.require_kyc = require_kyc
        
        self.compliance = ComplianceGuard()
        self.message = MessageGuard()
        self.cross_guard = CrossGuard()
        self.audit_log = AuditLog()
    
    def verify_payment_token(
        self,
        token_data: Dict[str, Any],
        action: UCPAction = UCPAction.PROCESS_PAYMENT
    ) -> PaymentVerificationResult:
        """
        Verify a UCP payment token before processing.
        
        Args:
            token_data: Payment token data containing:
                - amount: Transaction amount
                - currency: Currency code
                - customer_id: Customer identifier
                - customer_country: Customer country code
                - kyc_verified: Whether KYC is complete
                - payment_method: Payment method type
            action: UCP action being performed
            
        Returns:
            PaymentVerificationResult
        """
        violations = []
        receipts = []
        
        amount = token_data.get("amount", 0)
        currency = token_data.get("currency", "USD")
        country = token_data.get("customer_country", "US")
        kyc_verified = token_data.get("kyc_verified", False)
        
        # ===== Check 1: Amount limits =====
        if amount > self.max_amount:
            violations.append(f"Amount ${amount} exceeds max ${self.max_amount}")
        
        if amount <= 0:
            violations.append("Invalid amount: must be positive")
        
        receipt1 = ReceiptGenerator.create_receipt(
            guard_name="UCP.verify_amount",
            engine=VerificationEngine.DECIMAL,
            llm_output=str(amount),
            verified=(amount > 0 and amount <= self.max_amount),
            computed_value=f"Max: ${self.max_amount}"
        )
        receipts.append(receipt1)
        self.audit_log.log(receipt1)
        
        # ===== Check 2: Currency validation =====
        if currency not in self.allowed_currencies:
            violations.append(f"Currency {currency} not allowed. Allowed: {self.allowed_currencies}")
        
        # ===== Check 3: AML check =====
        aml_result = self.compliance.verify_aml_flag(
            amount=amount,
            country_code=country,
            llm_flagged=False,  # We're the verifier, not the LLM
            jurisdiction="USA"
        )
        
        needs_aml_flag = not aml_result.compliant
        if needs_aml_flag:
            violations.append(f"AML flag required: {aml_result.proof}")
        
        receipt2 = ReceiptGenerator.create_receipt(
            guard_name="UCP.verify_aml",
            engine=VerificationEngine.Z3,
            llm_output=str(token_data),
            verified=not needs_aml_flag,
            violations=[aml_result.rule_violated] if aml_result.rule_violated else []
        )
        receipts.append(receipt2)
        self.audit_log.log(receipt2)
        
        # ===== Check 4: KYC requirement =====
        if self.require_kyc and not kyc_verified:
            violations.append("KYC verification required but not complete")
        
        # ===== Determine status =====
        if len(violations) == 0:
            status = PaymentStatus.APPROVED
            can_proceed = True
        elif any("AML" in v for v in violations):
            status = PaymentStatus.PENDING_REVIEW
            can_proceed = False
        else:
            status = PaymentStatus.BLOCKED
            can_proceed = False
        
        return PaymentVerificationResult(
            status=status,
            action=action,
            can_proceed=can_proceed,
            violations=violations,
            receipts=receipts
        )
    
    def verify_iso20022_payment(
        self,
        xml_message: str,
        sanctions_list: List[str] = None
    ) -> PaymentVerificationResult:
        """
        Verify an ISO 20022 payment message with sanctions screening.
        
        Uses Cross-Guard to combine:
        1. XML structure validation
        2. Sanctions screening on entities
        3. Business rule validation
        
        Args:
            xml_message: ISO 20022 XML (pacs.008, pain.001, etc.)
            sanctions_list: Optional list of sanctioned entities
            
        Returns:
            PaymentVerificationResult
        """
        violations = []
        receipts = []
        
        # Validate XML structure
        msg_result = self.message.verify_iso20022_xml(xml_message, MessageType.PACS_008)
        
        receipt1 = ReceiptGenerator.create_receipt(
            guard_name="UCP.verify_iso20022_structure",
            engine=VerificationEngine.XML_SCHEMA,
            llm_output=xml_message[:100],
            verified=msg_result.valid,
            violations=msg_result.errors
        )
        receipts.append(receipt1)
        self.audit_log.log(receipt1)
        
        if not msg_result.valid:
            violations.extend(msg_result.errors)
        
        # Sanctions screening if list provided
        if sanctions_list:
            # Extract entities from XML
            import re
            entities = []
            
            # Look for name elements
            name_patterns = [r'<Nm>([^<]+)</Nm>', r'<DbtrNm>([^<]+)</DbtrNm>', 
                           r'<CdtrNm>([^<]+)</CdtrNm>']
            for pattern in name_patterns:
                matches = re.findall(pattern, xml_message)
                entities.extend(matches)
            
            # Check each entity
            for entity in entities:
                for sanctioned in sanctions_list:
                    if sanctioned.lower() in entity.lower():
                        violations.append(f"SANCTIONS HIT: {entity} matches {sanctioned}")
                        
                        receipt2 = ReceiptGenerator.create_receipt(
                            guard_name="UCP.sanctions_screening",
                            engine=VerificationEngine.REGEX,
                            llm_output=entity,
                            verified=False,
                            violations=[f"Entity matches sanctioned: {sanctioned}"]
                        )
                        receipts.append(receipt2)
                        self.audit_log.log(receipt2)
        
        # Determine status
        if any("SANCTIONS" in v for v in violations):
            status = PaymentStatus.BLOCKED
            can_proceed = False
        elif len(violations) == 0:
            status = PaymentStatus.APPROVED
            can_proceed = True
        else:
            status = PaymentStatus.PENDING_REVIEW
            can_proceed = False
        
        return PaymentVerificationResult(
            status=status,
            action=UCPAction.PROCESS_PAYMENT,
            can_proceed=can_proceed,
            violations=violations,
            receipts=receipts
        )
    
    def create_ucp_middleware(self):
        """
        Create middleware function compatible with qwed-ucp.
        
        Returns a function that can be used as UCP middleware.
        """
        def middleware(request: Dict[str, Any]) -> Dict[str, Any]:
            """UCP middleware function"""
            action = request.get("action", "")
            payload = request.get("payload", {})
            
            # Map UCP action
            if action == "checkout":
                ucp_action = UCPAction.INITIATE_CHECKOUT
            elif action == "payment":
                ucp_action = UCPAction.PROCESS_PAYMENT
            elif action == "confirm":
                ucp_action = UCPAction.CONFIRM_ORDER
            else:
                ucp_action = UCPAction.PROCESS_PAYMENT
            
            # Verify
            result = self.verify_payment_token(payload, ucp_action)
            
            return {
                "allowed": result.can_proceed,
                "status": result.status.value,
                "violations": result.violations,
                "receipt_ids": [r.receipt_id for r in result.receipts]
            }
        
        return middleware
    
    def get_audit_summary(self) -> Dict[str, Any]:
        """Get summary of all payment verifications"""
        return self.audit_log.summary()
    
    @staticmethod
    def get_capability_definition() -> Dict[str, Any]:
        """
        Get UCP Capability Definition for dynamic discovery.
        
        This allows platforms to discover and register this verification
        service in their .well-known/ucp.json configuration.
        
        Returns:
            Capability definition for UCP registry
        """
        return {
            "id": "qwed-finance-verification",
            "type": "extension",
            "version": "1.0.0",
            "name": "QWED Finance Verification Guard",
            "description": "Deterministic verification for payment tokens, ISO 20022 messages, and loan calculations using symbolic solvers.",
            "provider": {
                "name": "QWED-AI",
                "url": "https://qwedai.com",
                "contact": "support@qwedai.com"
            },
            "supported_operations": [
                {
                    "name": "verify_payment_token",
                    "description": "Verify payment token with AML/KYC checks",
                    "input": {
                        "amount": "number",
                        "currency": "string",
                        "customer_country": "string",
                        "kyc_verified": "boolean"
                    },
                    "output": {
                        "can_proceed": "boolean",
                        "status": "string",
                        "violations": "array",
                        "receipt_ids": "array"
                    }
                },
                {
                    "name": "verify_iso20022_payment",
                    "description": "Verify ISO 20022 XML with sanctions screening",
                    "input": {
                        "xml_message": "string",
                        "sanctions_list": "array (optional)"
                    },
                    "output": {
                        "can_proceed": "boolean",
                        "status": "string",
                        "violations": "array"
                    }
                },
                {
                    "name": "verify_loan_terms",
                    "description": "Verify loan calculation accuracy",
                    "input": {
                        "principal": "number",
                        "annual_rate": "number",
                        "months": "integer"
                    },
                    "output": {
                        "verified": "boolean",
                        "computed_payment": "string"
                    }
                }
            ],
            "verification_engines": [
                {"name": "Z3", "type": "SMT Solver", "use_case": "Compliance logic"},
                {"name": "SymPy", "type": "Symbolic Math", "use_case": "Financial calculations"},
                {"name": "SQLGlot", "type": "SQL AST", "use_case": "Query safety"},
                {"name": "XML Schema", "type": "Structure", "use_case": "Message validation"}
            ],
            "audit_trail": {
                "enabled": True,
                "format": "VerificationReceipt",
                "includes": ["input_hash", "timestamp", "engine_signature", "proof_steps"]
            },
            "compliance": [
                "BSA/FinCEN (AML/CTR)",
                "KYC Requirements",
                "OFAC Sanctions",
                "ISO 20022"
            ]
        }
    
    def get_ucp_json_entry(self) -> Dict[str, Any]:
        """
        Get entry for .well-known/ucp.json registration.
        
        Returns:
            Entry to add to a business's UCP configuration
        """
        return {
            "capabilities": {
                "qwed-finance": {
                    "enabled": True,
                    "endpoint": "/api/qwed/verify",
                    "version": "1.0.0",
                    "operations": [
                        "verify_payment_token",
                        "verify_iso20022_payment",
                        "verify_loan_terms"
                    ]
                }
            }
        }

