"""
Cross-Guard Integration - Connect guards for comprehensive verification
Enables multi-layer verification (e.g., scan SWIFT message for sanctioned entities)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .compliance_guard import ComplianceGuard
from .message_guard import MessageGuard, MessageType
from .query_guard import QueryGuard
from .models.receipt import VerificationReceipt, ReceiptGenerator, VerificationEngine, AuditLog
import re


@dataclass
class CrossGuardResult:
    """Result from cross-guard verification"""
    passed: bool
    guard_results: Dict[str, bool]
    violations: List[str]
    receipts: List[VerificationReceipt]
    screened_entities: List[str] = field(default_factory=list)
    

class CrossGuard:
    """
    Integrates multiple guards for comprehensive verification.
    
    Use Cases:
    - Scan SWIFT message content for sanctioned entities
    - Verify ISO 20022 message AND check compliance rules on values
    - Run SQL safety check AND verify query results against business rules
    """
    
    def __init__(self):
        self.compliance = ComplianceGuard()
        self.message = MessageGuard()
        self.query = QueryGuard()
        self.audit_log = AuditLog()
    
    # ==================== SWIFT + Sanctions ====================
    
    def verify_swift_with_sanctions(
        self,
        mt_string: str,
        sanctions_list: List[str]
    ) -> CrossGuardResult:
        """
        Verify SWIFT MT message AND scan for sanctioned entities.
        
        This combines:
        1. MessageGuard - Validate MT format
        2. ComplianceGuard - Check names against sanctions list
        
        Args:
            mt_string: SWIFT MT message
            sanctions_list: List of sanctioned entity names
            
        Returns:
            CrossGuardResult with combined verification
        """
        violations = []
        guard_results = {}
        receipts = []
        
        # Step 1: Validate SWIFT format
        from .message_guard import SwiftMtType
        msg_result = self.message.verify_swift_mt(mt_string, SwiftMtType.MT103)
        guard_results["MessageGuard"] = msg_result.valid
        
        receipt1 = ReceiptGenerator.create_receipt(
            guard_name="MessageGuard.verify_swift_mt",
            engine=VerificationEngine.REGEX,
            llm_output=mt_string,
            verified=msg_result.valid,
            violations=msg_result.errors
        )
        receipts.append(receipt1)
        self.audit_log.log(receipt1)
        
        if not msg_result.valid:
            violations.extend(msg_result.errors)
        
        # Step 2: Extract entity names from MT message
        entities = self._extract_entities_from_mt(mt_string)
        
        # Step 3: Check each entity against sanctions list
        for entity in entities:
            is_sanctioned = self._check_sanctions(entity, sanctions_list)
            
            if is_sanctioned:
                violations.append(f"SANCTIONS HIT: '{entity}' found in sanctions list")
                guard_results["ComplianceGuard.sanctions"] = False
                
                receipt2 = ReceiptGenerator.create_receipt(
                    guard_name="ComplianceGuard.sanctions_check",
                    engine=VerificationEngine.REGEX,
                    llm_output=entity,
                    verified=False,
                    violations=[f"Entity '{entity}' is sanctioned"],
                    metadata={"sanctions_list_size": len(sanctions_list)}
                )
                receipts.append(receipt2)
                self.audit_log.log(receipt2)
        
        if "ComplianceGuard.sanctions" not in guard_results:
            guard_results["ComplianceGuard.sanctions"] = True
        
        passed = all(guard_results.values())

        return CrossGuardResult(
            passed=passed,
            guard_results=guard_results,
            violations=violations,
            receipts=receipts,
            screened_entities=entities
        )

    # Party/institution fields whose values name entities that must be
    # screened (MT103 party set incl. structured 50F/59F variants and
    # free-text 70/72 carriers). 58A is an MT202 field; when present in
    # an MT103 body it is still screened rather than trusted.
    _PARTY_FIELD_TAGS = frozenset({
        "50K", "50F", "50H",
        "51A",
        "52A", "52D",
        "56A", "56C", "56D",
        "57A", "57B", "57C", "57D",
        "58A", "58D",
        "59", "59A", "59F",
        "70", "72",
    })

    # One MT field block: `:TAG:` header plus all continuation lines up to
    # the next `:TAG:` header or end of message.
    _FIELD_BLOCK_RE = re.compile(
        r"^:([0-9]{2}[A-Z]?):(.*?)(?=^:[0-9]{2}[A-Z]?:|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    def _extract_entities_from_mt(self, mt_string: str) -> List[str]:
        """Extract every screenable entity line from party field blocks.

        Returns one entry per non-empty line of EVERY occurrence of every
        party tag (findall semantics over full multi-line values), so a
        decoy tag planted in free text cannot blind the real beneficiary
        line and names on continuation lines are never skipped. Entries
        are deduplicated preserving order.
        """
        entities: List[str] = []
        if not isinstance(mt_string, str):
            return entities

        for block in self._FIELD_BLOCK_RE.finditer(mt_string):
            if block.group(1).upper() not in self._PARTY_FIELD_TAGS:
                continue
            for line in block.group(2).splitlines():
                text = line.strip()
                # Skip the block-4 trailer: it is message framing, not an
                # entity, and would otherwise pollute the screened list.
                if not text or text == "-}":
                    continue
                if text not in entities:
                    entities.append(text)

        return entities
    
    def _check_sanctions(self, entity: str, sanctions_list: List[str]) -> bool:
        """Check if entity matches any sanctioned name (fuzzy match)"""
        entity_lower = entity.lower()
        for sanctioned in sanctions_list:
            if sanctioned.lower() in entity_lower or entity_lower in sanctioned.lower():
                return True
        return False
    
    # ==================== ISO 20022 + Business Rules ====================
    
    def verify_iso20022_with_rules(
        self,
        xml_string: str,
        business_rules: Dict[str, Any]
    ) -> CrossGuardResult:
        """
        Verify ISO 20022 XML AND check business rules on extracted values.
        
        Business rules example:
        {
            "max_amount": 1000000,
            "min_amount": 1,
            "allowed_currencies": ["USD", "EUR", "GBP"],
            "settlement_future_only": True
        }
        
        Args:
            xml_string: ISO 20022 XML message
            business_rules: Dictionary of business rule constraints
            
        Returns:
            CrossGuardResult
        """
        violations = []
        guard_results = {}
        receipts = []
        
        # Step 1: Validate XML structure
        msg_result = self.message.verify_iso20022_xml(xml_string, MessageType.PACS_008)
        guard_results["MessageGuard"] = msg_result.valid
        
        receipt1 = ReceiptGenerator.create_receipt(
            guard_name="MessageGuard.verify_iso20022_xml",
            engine=VerificationEngine.XML_SCHEMA,
            llm_output=xml_string[:200],
            verified=msg_result.valid,
            violations=msg_result.errors
        )
        receipts.append(receipt1)
        
        if not msg_result.valid:
            violations.extend(msg_result.errors)
        
        # Step 2: Extract values and check business rules
        amount = self._extract_xml_value(xml_string, "IntrBkSttlmAmt")
        currency = self._extract_xml_attribute(xml_string, "IntrBkSttlmAmt", "Ccy")
        
        # Check amount constraints
        if amount is not None:
            if "max_amount" in business_rules and amount > business_rules["max_amount"]:
                violations.append(f"Amount {amount} exceeds max {business_rules['max_amount']}")
                guard_results["BusinessRule.max_amount"] = False
            else:
                guard_results["BusinessRule.max_amount"] = True
            
            if "min_amount" in business_rules and amount < business_rules["min_amount"]:
                violations.append(f"Amount {amount} below min {business_rules['min_amount']}")
                guard_results["BusinessRule.min_amount"] = False
            else:
                guard_results["BusinessRule.min_amount"] = True
        
        # Check currency
        if currency and "allowed_currencies" in business_rules:
            if currency not in business_rules["allowed_currencies"]:
                violations.append(f"Currency {currency} not in allowed list")
                guard_results["BusinessRule.currency"] = False
            else:
                guard_results["BusinessRule.currency"] = True
        
        passed = all(guard_results.values())
        
        return CrossGuardResult(
            passed=passed,
            guard_results=guard_results,
            violations=violations,
            receipts=receipts
        )
    
    def _extract_xml_value(self, xml: str, element: str) -> Optional[float]:
        """Extract numeric value from XML element"""
        pattern = rf'<{element}[^>]*>([^<]+)</{element}>'
        match = re.search(pattern, xml)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                return None
        return None
    
    def _extract_xml_attribute(self, xml: str, element: str, attr: str) -> Optional[str]:
        """Extract attribute value from XML element"""
        pattern = rf'<{element}[^>]*{attr}="([^"]+)"'
        match = re.search(pattern, xml)
        return match.group(1) if match else None
    
    # ==================== SQL + Table Access + Compliance ====================
    
    def verify_query_with_pii_protection(
        self,
        sql_query: str,
        allowed_tables: List[str],
        pii_columns: List[str]
    ) -> CrossGuardResult:
        """
        Full SQL verification with table access AND PII protection.
        
        Args:
            sql_query: SQL query to verify
            allowed_tables: List of tables the AI can access
            pii_columns: List of PII columns that must be blocked
            
        Returns:
            CrossGuardResult
        """
        violations = []
        guard_results = {}
        receipts = []
        
        # Step 1: Read-only safety
        readonly_result = self.query.verify_readonly_safety(sql_query)
        guard_results["QueryGuard.readonly"] = readonly_result.safe
        
        receipt1 = ReceiptGenerator.create_receipt(
            guard_name="QueryGuard.verify_readonly_safety",
            engine=VerificationEngine.SQLGLOT,
            llm_output=sql_query,
            verified=readonly_result.safe,
            violations=readonly_result.violations
        )
        receipts.append(receipt1)
        
        if not readonly_result.safe:
            violations.extend(readonly_result.violations)
        
        # Step 2: Table access
        table_result = self.query.verify_table_access(sql_query, set(allowed_tables))
        guard_results["QueryGuard.table_access"] = table_result.safe
        
        if not table_result.safe:
            violations.extend([v for v in table_result.violations if "Unauthorized" in v])
        
        # Step 3: PII column protection
        column_result = self.query.verify_column_access(sql_query, set(pii_columns))
        guard_results["QueryGuard.pii_protection"] = column_result.safe
        
        if not column_result.safe:
            violations.extend([v for v in column_result.violations if "Restricted" in v])
        
        passed = all(guard_results.values())
        
        return CrossGuardResult(
            passed=passed,
            guard_results=guard_results,
            violations=violations,
            receipts=receipts
        )
