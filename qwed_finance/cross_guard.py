"""
Cross-Guard Integration - Connect guards for comprehensive verification
Enables multi-layer verification (e.g., scan SWIFT message for sanctioned entities)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .compliance_guard import (
    ComplianceGuard,
    has_mixed_scripts,
    sanctions_match,
)
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

        # An absent sanctions list means unscreened: fail closed instead
        # of skipping the loop and approving (UCP parity).
        if not sanctions_list:
            violations.append(
                "SANCTIONS UNSCREENED: no sanctions list provided for screening"
            )
            guard_results["ComplianceGuard.sanctions"] = False

            unscreened_receipt = ReceiptGenerator.create_receipt(
                guard_name="ComplianceGuard.sanctions_check",
                engine=VerificationEngine.REGEX,
                llm_output=mt_string,
                verified=False,
                violations=["No sanctions list provided; payment cannot be screened"],
                metadata={"sanctions_list_size": 0}
            )
            receipts.append(unscreened_receipt)
            self.audit_log.log(unscreened_receipt)

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
        name_set = set(self._extract_name_entities(mt_string))

        # Step 3: Check each entity against sanctions list
        for entity in entities:
            if has_mixed_scripts(entity):
                # Unscreenable by substring logic: fail safe to review,
                # never clear (#76 residual).
                violations.append(
                    f"SANCTIONS REVIEW: '{entity}' mixes scripts and cannot be screened"
                )
                guard_results["ComplianceGuard.sanctions"] = False

                review_receipt = ReceiptGenerator.create_receipt(
                    guard_name="ComplianceGuard.sanctions_check",
                    engine=VerificationEngine.REGEX,
                    llm_output=entity,
                    verified=False,
                    violations=[f"SANCTIONS REVIEW: '{entity}' requires manual script review"],
                    metadata={"sanctions_list_size": len(sanctions_list)}
                )
                receipts.append(review_receipt)
                self.audit_log.log(review_receipt)
                continue
            is_sanctioned = self._check_sanctions(
                entity, sanctions_list, allow_reverse=(entity in name_set)
            )
            
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
        "50A", "50K", "50F", "50H",
        "51A",
        "52A", "52D",
        "53A", "54A", "55A",
        "56A", "56C", "56D",
        "57A", "57B", "57C", "57D",
        "58A", "58D",
        "59", "59A", "59F",
        "70", "72",
    })

    # One MT field block: `:TAG:` header plus all continuation lines up to
    # the next `:TAG:` header or end of message. Greedy tempered dot (not
    # a reluctant quantifier) with no top-level anchor alternation, so the
    # pattern is unambiguous to readers and static analysis alike.
    _FIELD_BLOCK_RE = re.compile(
        r"^:(?P<tag>\d{2}[A-Z]?):(?P<value>(?:(?!\r?\n:\d{2}[A-Z]?:)[\s\S])*)",
        re.MULTILINE,
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

        for tag, value in self._iter_party_blocks(mt_string):
            for text in self._content_lines(value):
                if text not in entities:
                    entities.append(text)
            # Structured blocks: also screen the stripped name components
            # and their joined form (see _extract_name_entities).
            for name in self._structured_names(tag, value):
                if name not in entities:
                    entities.append(name)

        return entities

    @staticmethod
    def _content_lines(value: str):
        """Yield stripped content lines, skipping blanks and trailers."""
        for line in value.splitlines():
            text = line.strip()
            # Skip block-4 trailers ("-}" or "-}{5:...}" framing):
            # message framing, not an entity.
            if not text or text.startswith("-}"):
                continue
            yield text

    # Party tags that identify (rather than describe) the party: their
    # name lines match bidirectionally. Narrative/free-text carriers
    # (70/72) match forward-only — a fragment there must never bless or
    # condemn via substring coincidence.
    _NAME_FIELD_TAGS = frozenset({
        "50A", "50K", "50F", "50H",
        "51A",
        "52A", "52D",
        "53A", "54A", "55A",
        "56A", "56C", "56D",
        "57A", "57B", "57C", "57D",
        "58A", "58D",
        "59", "59A", "59F",
    })

    def _iter_party_blocks(self, mt_string: str):
        """Yield (tag, value) for every party-tagged field block."""
        if not isinstance(mt_string, str):
            return
        for block in self._FIELD_BLOCK_RE.finditer(mt_string):
            tag = block.group("tag").upper()
            if tag in self._PARTY_FIELD_TAGS:
                yield tag, block.group("value")

    @staticmethod
    def _structured_names(tag: str, value: str) -> List[str]:
        """Stripped ``1/`` name components plus their joined form."""
        if tag not in ("50F", "59F"):
            return []
        parts = []
        for line in value.splitlines():
            match = re.match(r"^1/(.+)$", line.strip())
            if match and match.group(1).strip():
                parts.append(match.group(1).strip())
        if not parts:
            return []
        return parts + ([" ".join(parts)] if len(parts) > 1 else [])

    @staticmethod
    def _first_name_line(value: str) -> Optional[str]:
        """First content line that names (rather than accounts for) the party."""
        for text in CrossGuard._content_lines(value):
            if text.startswith("/"):
                continue
            return text
        return None

    def _extract_name_entities(self, mt_string: str) -> List[str]:
        """Entity strings that identify the party (not describe it).

        Structured ``1/`` name components (stripped, plus their joined
        form) and the first non-account content line of other party
        blocks. Only these match bidirectionally; every other screened
        line matches forward-only.
        """
        names: List[str] = []
        for tag, value in self._iter_party_blocks(mt_string):
            if tag in ("50F", "59F"):
                candidates = self._structured_names(tag, value)
            elif tag in ("70", "72"):
                continue
            else:
                first = self._first_name_line(value)
                candidates = [first] if first is not None else []
            for name in candidates:
                if name not in names:
                    names.append(name)
        return names
    
    def _check_sanctions(
        self,
        entity: str,
        sanctions_list: List[str],
        allow_reverse: bool = True,
    ) -> bool:
        """Check if entity matches any sanctioned name (fuzzy match).

        Shared normalized matcher (see compliance_guard.sanctions_match):
        NFKC/ignorable/punctuation folding on both sides, forward
        containment always, reverse and token-set equality only for
        name-provenance entities. Mixed-script names fail safe to manual
        review at the call site. Full name/address disambiguation and
        alias data are tracked in #76/#77/#78.
        """
        for sanctioned in sanctions_list:
            if sanctions_match(entity, sanctioned, allow_reverse=allow_reverse):
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
