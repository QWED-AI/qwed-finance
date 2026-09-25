"""
UCP Integration - Payment token verification for e-commerce flows
Ensures payment messages are verified before checkout proceeds
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum
import re

from ..compliance_guard import (
    ComplianceGuard,
    has_mixed_scripts,
    normalize_for_screening,
    sanctions_match,
    validate_amount,
)
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

        # Fail closed on unevaluable amounts before any comparison: str/None
        # payloads crash `>`/`<=` with TypeError, escaping the verifier
        # instead of verdicting (#45 residual).
        try:
            amount = validate_amount(token_data.get("amount"), "amount")
        except ValueError as exc:
            violations.append(f"Invalid amount: {exc}")
            receipt0 = ReceiptGenerator.create_receipt(
                guard_name="UCP.verify_amount",
                engine=VerificationEngine.DECIMAL,
                llm_output=str(token_data.get("amount")),
                verified=False,
                violations=[f"Invalid amount: {exc}"],
            )
            receipts.append(receipt0)
            self.audit_log.log(receipt0)
            return PaymentVerificationResult(
                status=PaymentStatus.BLOCKED,
                action=action,
                can_proceed=False,
                violations=violations,
                receipts=receipts,
            )
        currency = token_data.get("currency", "USD")
        # No default: a missing customer_country must fail closed through
        # verify_aml_flag (which rejects None as unevaluable) instead of
        # clearing as low-risk "US".
        country = token_data.get("customer_country")
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
        sanctions_list: List[str] = None,
        kyc_verified: bool = False,
    ) -> PaymentVerificationResult:
        """
        Verify an ISO 20022 payment message with sanctions screening.
        
        Uses Cross-Guard to combine:
        1. XML structure validation
        2. Sanctions screening on entities
        3. Business rule validation (max_amount, allowed_currencies)
        
        Args:
            xml_message: ISO 20022 XML (pacs.008, pain.001, etc.)
            sanctions_list: Optional list of sanctioned entities
            kyc_verified: Explicit KYC context for this payment; without
                it, require_kyc=True can never auto-approve (a pacs.008
                carries no KYC evidence of its own, #67)
            
        Returns:
            PaymentVerificationResult
        """
        violations = []
        receipts = []
        
        # Validate XML structure
        msg_result = self.message.verify_iso20022_xml(xml_message, MessageType.PACS_008)
        
        # Hash the whole document: a truncated preview left anything past
        # the cutoff outside the receipt's input hash (#65).
        receipt1 = ReceiptGenerator.create_receipt(
            guard_name="UCP.verify_iso20022_structure",
            engine=VerificationEngine.XML_SCHEMA,
            llm_output=xml_message,
            verified=msg_result.valid,
            violations=msg_result.errors
        )
        receipts.append(receipt1)
        self.audit_log.log(receipt1)
        
        if not msg_result.valid:
            violations.extend(msg_result.errors)
        
        # Sanctions screening: an absent list means unscreened, which must
        # never read as approved (#77).
        if not sanctions_list:
            self._fail_sanctions(
                violations,
                receipts,
                "SANCTIONS UNSCREENED: no sanctions list provided for screening",
            )
        elif not self._xml_safe_for_screening(xml_message):
            self._fail_sanctions(
                violations,
                receipts,
                "SANCTIONS UNSCREENED: document refused for screening "
                "(DOCTYPE declarations and oversized documents are rejected)",
            )
        else:
            # Extract entities from the parsed document (local names catch
            # namespaced/aliased elements; AdrLine covers address-only
            # parties). Raw byte regexes miss char refs, prefixes,
            # comments, and attributes (#77).
            entities = self._extract_xml_entities(xml_message)
            if not entities:
                self._fail_sanctions(
                    violations,
                    receipts,
                    "SANCTIONS UNSCREENED: no screenable entities extracted "
                    "from the document",
                )

            # Check each entity with the shared matcher (bidirectional for
            # names, matching CrossGuard semantics)
            for entity, is_name in entities:
                if has_mixed_scripts(entity):
                    self._fail_sanctions(
                        violations,
                        receipts,
                        f"SANCTIONS REVIEW: '{entity}' mixes scripts and cannot be screened",
                    )
                    continue
                for sanctioned in sanctions_list:
                    if sanctions_match(
                        entity, sanctioned, allow_reverse=is_name
                    ):
                        violations.append(
                            f"SANCTIONS HIT: {entity} matches {sanctioned}"
                        )

                        receipt2 = ReceiptGenerator.create_receipt(
                            guard_name="UCP.sanctions_screening",
                            engine=VerificationEngine.REGEX,
                            llm_output=entity,
                            verified=False,
                            violations=[f"Entity matches sanctioned: {sanctioned}"]
                        )
                        receipts.append(receipt2)
                        self.audit_log.log(receipt2)
                        break

        # Business limits (#67): max_amount/allowed_currencies were
        # stored on init but this method never consulted them — an honest
        # over-limit or disallowed-currency pacs.008 approved with zero
        # violations. Wire the CrossGuard engine and keep its receipts.
        rules = self.cross_guard.check_business_rules(xml_message, {
            "max_amount": self.max_amount,
            "allowed_currencies": self.allowed_currencies,
        })
        violations.extend(rules.violations)
        for rules_receipt in rules.receipts:
            receipts.append(rules_receipt)
            self.audit_log.log(rules_receipt)
        
        # KYC (#67): a pacs.008 carries no KYC evidence, so with
        # require_kyc on, an ISO payment can never auto-approve unless
        # the caller supplies explicit context.
        if self.require_kyc and not kyc_verified:
            violations.append(
                "KYC verification required: ISO 20022 message carries no "
                "KYC evidence"
            )
        
        # Determine status: hits and unscreened outcomes block; a
        # deterministic config breach (over-limit, disallowed currency)
        # blocks outright rather than queueing for review; everything
        # else — including SANCTIONS REVIEW, structural errors, and
        # missing KYC context — routes to manual review, never approval.
        if any(
            v.startswith(("SANCTIONS HIT", "SANCTIONS UNSCREENED"))
            for v in violations
        ):
            status = PaymentStatus.BLOCKED
            can_proceed = False
        elif rules.policy_breach:
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
    
    #: Refuse DTD-bearing or oversized documents for screening: Expat
    #: expands internal entities, so a small request can materialize a
    #: large string that lands in violations and receipts.
    _MAX_SCREEN_XML_BYTES = 1_000_000
    _DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)

    @classmethod
    def _xml_safe_for_screening(cls, xml_message: Any) -> bool:
        """Refuse documents unsafe to expand for screening."""
        return (
            isinstance(xml_message, str)
            and not cls._DOCTYPE_RE.search(xml_message)
            and len(xml_message.encode("utf-8")) <= cls._MAX_SCREEN_XML_BYTES
        )

    def _fail_sanctions(
        self, violations: list, receipts: list, message: str
    ) -> None:
        """Record a sanctions failure in violations, receipts, and audit log.

        One call keeps all three evidence surfaces in agreement — a
        failure invisible in any one of them is an audit gap.
        """
        violations.append(message)
        receipt = ReceiptGenerator.create_receipt(
            guard_name="UCP.sanctions_screening",
            engine=VerificationEngine.REGEX,
            llm_output=message,
            verified=False,
            violations=[message],
        )
        receipts.append(receipt)
        self.audit_log.log(receipt)

    #: Element local names that identify the party (bidirectional match).
    _XML_NAME_TAGS = frozenset({"Nm", "DbtrNm", "CdtrNm"})

    @staticmethod
    def _element_candidates(element, name_tags: frozenset):
        """(text, is_name) candidates for one element: both join orders.

        Nodes may split mid-word ("BA"+"NK") or at word boundaries
        ("BANNED"+"ENTITY LTD"); screening both forms keeps either split
        verifiable. Attribute values on screened elements are screened
        too — an attribute-only sanctioned name must not evade — but
        always forward-only: metadata such as xml:lang="en" must never
        condemn via reverse coincidence.
        """
        tag = element.tag
        if "}" in tag:
            tag = tag.rsplit("}", 1)[1]
        if tag in name_tags:
            flag = True
        elif tag == "AdrLine":
            flag = False
        else:
            return
        raw = "".join(element.itertext())
        spaced = " ".join(element.itertext())
        candidates = [raw] if raw == spaced else [raw, spaced]
        for text in candidates:
            text = text.strip()
            if text:
                yield text, flag
        for value in element.attrib.values():
            if isinstance(value, str) and value.strip():
                yield value.strip(), False

    @staticmethod
    def _extract_xml_entities(xml_message: str) -> List[tuple]:
        """Extract (text, is_name) pairs from the parsed XML document.

        Local-name matching catches namespaced/aliased elements, char
        references, comments, and attributes that raw byte regexes miss;
        AdrLine covers address-only parties. Name elements (Nm and friends)
        match bidirectionally; address lines match forward-only (#77).
        """
        import xml.etree.ElementTree as ET

        entities: List[tuple] = []
        seen = set()
        try:
            root = ET.fromstring(xml_message)
        except ET.ParseError:
            return entities
        for element in root.iter():
            for text, flag in UCPIntegration._element_candidates(
                element, UCPIntegration._XML_NAME_TAGS
            ):
                # Candidates that normalize identically are one screened
                # value, not two: duplicate violations/receipts for a
                # single party inflate the audit trail into phantom
                # multi-hits. Normalization collapses the spacing
                # difference for whole-word splits.
                key = (normalize_for_screening(text), flag)
                if key in seen:
                    continue
                seen.add(key)
                entities.append((text, flag))
        return entities

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

