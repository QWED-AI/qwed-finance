"""
Message Guard - ISO 20022 and SWIFT message validation
Ensures LLM-generated banking messages are structurally correct
"""

from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum
import re
import xml.etree.ElementTree as ET
from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException

# Shared fail-closed error for XML that does not parse under defusedxml
_PARSE_ERROR = "Message is not parseable XML"


class MessageType(Enum):
    """Standard ISO 20022 message types"""
    PACS_008 = "pacs.008"  # Customer Credit Transfer
    PACS_002 = "pacs.002"  # Payment Status Report
    CAMT_053 = "camt.053"  # Bank Statement
    CAMT_054 = "camt.054"  # Credit/Debit Notification
    PAIN_001 = "pain.001"  # Customer Payment Initiation
    

class SwiftMtType(Enum):
    """Legacy SWIFT MT message types"""
    MT103 = "MT103"  # Single Customer Credit Transfer
    MT202 = "MT202"  # General Financial Institution Transfer
    MT940 = "MT940"  # Customer Statement
    MT950 = "MT950"  # Statement Message


@dataclass
class MessageResult:
    """Result of a message validation"""
    valid: bool
    message_type: str
    errors: List[str]
    warnings: List[str]
    field_count: Optional[int] = None
    

class MessageGuard:
    """
    Deterministic validation for banking messages.
    Ensures LLM-generated messages conform to ISO 20022 and SWIFT standards.
    """

    # ISO wrapper elements, keyed by expected_parent: wrappers sit only
    # directly under Document (FIToFICstmrCdtTrf etc. are document-level
    # roots), so the wrapper hop is legal only when validating that
    # Document-level relation. Every other relation requires a direct
    # parent — a shared flat set would let FIToFICstmrCdtTrf sit between
    # GrpHdr and MsgId (wrong branch), and would miss the real pain.001
    # wrapper (CstmrCdtTrfInitn). Anything else blocks the parentage path.
    _WRAPPERS_BY_TYPE = {
        MessageType.PACS_008: {
            "Document": frozenset({"FIToFICstmrCdtTrf"})
        },
        MessageType.CAMT_053: {
            "Document": frozenset({"BkToCstmrStmt"})
        },
        MessageType.PAIN_001: {
            "Document": frozenset({"CstmrCdtTrfInitn"})
        },
    }

    def __init__(self):
        self._lxml_available = self._check_lxml()
        
        # Required fields for SWIFT MT messages
        self.mt103_required_fields = {
            "20": "Transaction Reference",
            "23B": "Bank Operation Code",
            "32A": "Value Date/Currency/Amount",
            "50K": "Ordering Customer",
            "59": "Beneficiary Customer",
            "71A": "Details of Charges"
        }
        
        self.mt202_required_fields = {
            "20": "Transaction Reference",
            "21": "Related Reference",
            "32A": "Value Date/Currency/Amount",
            "58A": "Beneficiary Institution"
        }

        self.mt940_required_fields = {
            "20": "Transaction Reference",
            "25": "Account Identification",
        }
    
    def _check_lxml(self) -> bool:
        """Check if lxml is available for XML validation"""
        try:
            from lxml import etree
            return True
        except ImportError:
            return False
    
    # ==================== ISO 20022 XML Validation ====================
    
    def verify_iso20022_xml(
        self,
        xml_string: str,
        msg_type: MessageType = MessageType.PACS_008
    ) -> MessageResult:
        """
        Verify ISO 20022 XML message structure.
        
        Args:
            xml_string: The XML message to validate
            msg_type: Expected message type
            
        Returns:
            MessageResult with validation status
        """
        errors = []
        warnings = []
        
        # Basic XML well-formedness check
        if not self._is_well_formed_xml(xml_string):
            return MessageResult(
                valid=False,
                message_type=msg_type.value,
                errors=["XML is not well-formed"],
                warnings=[]
            )
        
        # Check for required namespaces
        if "urn:iso:std:iso:20022" not in xml_string:
            warnings.append("Missing ISO 20022 namespace declaration")
        
        # Message-specific validation
        if msg_type == MessageType.PACS_008:
            errors.extend(self._validate_pacs008(xml_string))
        elif msg_type == MessageType.CAMT_053:
            errors.extend(self._validate_camt053(xml_string))
        elif msg_type == MessageType.PAIN_001:
            errors.extend(self._validate_pain001(xml_string))
        else:
            # Fail closed: message types without a validator branch must
            # never validate (PACS_002/CAMT_054 hit this today — even ""
            # would otherwise pass, see #61).
            errors.append(
                f"Unsupported message type for validation: {msg_type.value}"
            )
        
        return MessageResult(
            valid=len(errors) == 0,
            message_type=msg_type.value,
            errors=errors,
            warnings=warnings,
            field_count=xml_string.count("<")
        )
    
    def _is_well_formed_xml(self, xml_string: str) -> bool:
        """Check if XML is well-formed"""
        if self._lxml_available:
            try:
                from lxml import etree
                parser = etree.XMLParser(
                    resolve_entities=False,
                    load_dtd=False,
                    no_network=True,
                )
                etree.fromstring(xml_string.encode(), parser)
                return True
            except Exception:
                return False
        # Dependency-free fallback: real parse, not bracket counting.
        # Bracket-balanced non-XML ("<>" * n, "a < b") passed here (#61).
        return self._parse_xml(xml_string) is not None

    @staticmethod
    def _parse_xml(xml_string: str):
        """Parse untrusted XML with defusedxml, or None if unsafe/malformed.

        The string is encoded first: ElementTree rejects encoding
        declarations on str input, which made valid messages carrying
        `<?xml ... encoding=...?>` fail closed incorrectly. defusedxml
        refuses DTD entity payloads (CWE-776) alongside parse errors.
        """
        try:
            return DET.fromstring(xml_string.encode("utf-8"))
        except (ET.ParseError, DefusedXmlException, UnicodeEncodeError):
            # UnicodeEncodeError: unpaired surrogates raise in encode()
            # before parsing; without this the guard crashes instead of
            # failing closed.
            return None

    @staticmethod
    def _local_name(item) -> str:
        """Namespace-stripped local name of an element tag or attribute key."""
        tag = item if isinstance(item, str) else getattr(item, "tag", None)
        if not isinstance(tag, str):
            return ""
        return tag.rsplit("}", 1)[1] if "}" in tag else tag

    @staticmethod
    def _require_elements(
        root, required: Dict[str, str], wrappers: Dict[str, frozenset]
    ) -> List[str]:
        """Required elements must exist under their expected ancestors.

        Substring or global-name checks let elements in unrelated branches
        satisfy requirements without ISO parentage (#62, review fix).
        Every instance must be correctly parented (all, not any): with any
        one well-placed instance passing, a stray duplicate of the same
        element in the wrong branch went unreported.
        """
        errors = []
        parents = {child: parent for parent in root.iter() for child in parent}
        for child, expected_parent in required.items():
            instances = [
                e for e in root.iter() if MessageGuard._local_name(e) == child
            ]
            if not instances:
                errors.append(f"Missing required element: {child}")
                continue
            allowed = wrappers.get(expected_parent, frozenset())
            if not all(
                MessageGuard._has_ancestor(i, parents, expected_parent, allowed)
                for i in instances
            ):
                errors.append(
                    f"Element {child} must appear under {expected_parent}"
                )
        return errors

    @staticmethod
    def _has_ancestor(
        instance, parents: dict, expected_parent: str, allowed: frozenset
    ) -> bool:
        """True when expected_parent is the direct parent of instance, or
        the parent of exactly one allowed wrapper in between.

        allowed is empty except for Document-level hops, and at most one
        wrapper level is accepted: a walk up the whole tree let
        FIToFICstmrCdtTrf between GrpHdr and MsgId (wrapper in the wrong
        branch), merging two branches that ISO keeps separate.
        """
        cursor = parents.get(instance)
        if cursor is None:
            return False
        name = MessageGuard._local_name(cursor)
        if name == expected_parent:
            return True
        if name not in allowed:
            return False
        grandparent = parents.get(cursor)
        return (
            grandparent is not None
            and MessageGuard._local_name(grandparent) == expected_parent
        )

    def _validate_pacs008(self, xml: str) -> List[str]:
        """Validate pacs.008 Customer Credit Transfer"""
        required = {
            "GrpHdr": "Document",           # Group Header
            "MsgId": "GrpHdr",              # Message ID
            "CreDtTm": "GrpHdr",            # Creation DateTime
            "NbOfTxs": "GrpHdr",            # Number of Transactions
            "CdtTrfTxInf": "Document",      # Credit Transfer Info
        }
        transaction_required = (
            "IntrBkSttlmAmt",               # Interbank Settlement Amount
            "DbtrAgt",                      # Debtor Agent
            "CdtrAgt",                      # Creditor Agent
        )

        root = self._parse_xml(xml)
        if root is None:
            return [_PARSE_ERROR]

        errors = self._require_elements(
            root, required, self._WRAPPERS_BY_TYPE[MessageType.PACS_008]
        )
        errors.extend(
            self._transaction_child_errors(root, transaction_required)
        )
        errors.extend(self._currency_errors(root))
        return errors

    def _transaction_child_errors(self, root, transaction_required) -> List[str]:
        """Required children on every CdtTrfTxInf.

        A global any-instance check lets one complete transaction mask
        an empty sibling; each transaction is validated on its own.
        """
        errors = []
        transactions = [
            e for e in root.iter() if self._local_name(e) == "CdtTrfTxInf"
        ]
        for index, transaction in enumerate(transactions, start=1):
            present = {self._local_name(child) for child in transaction}
            for child in transaction_required:
                if child not in present:
                    errors.append(
                        f"Transaction {index}: missing required element {child}"
                    )
        return errors

    def _currency_errors(self, root) -> List[str]:
        """Settlement amounts must carry Ccy; codes must be 3 uppercase
        letters. An amount without Ccy is not a settlement amount —
        checking only present values let amountless messages pass."""
        errors = []
        for element in root.iter():
            if self._local_name(element) == "IntrBkSttlmAmt" and not any(
                self._local_name(key) == "Ccy" for key in element.attrib
            ):
                errors.append(
                    "Missing required attribute Ccy on IntrBkSttlmAmt"
                )
            for key, value in element.attrib.items():
                if self._local_name(key) == "Ccy" and not re.fullmatch(
                    r"[A-Z]{3}", value
                ):
                    errors.append(
                        "Invalid currency code format "
                        "(must be 3 uppercase letters)"
                    )
        return errors

    def _validate_camt053(self, xml: str) -> List[str]:
        """Validate camt.053 Bank Statement"""
        required = {
            "GrpHdr": "Document",  # Group Header
            "Stmt": "Document",    # Statement
            "Acct": "Stmt",        # Account
            "Bal": "Stmt",         # Balance
        }

        root = self._parse_xml(xml)
        if root is None:
            return [_PARSE_ERROR]

        return self._require_elements(
            root, required, self._WRAPPERS_BY_TYPE[MessageType.CAMT_053]
        )

    def _validate_pain001(self, xml: str) -> List[str]:
        """Validate pain.001 Customer Payment Initiation"""
        required = {
            "GrpHdr": "Document",   # Group Header
            "MsgId": "GrpHdr",      # Message ID
            "CreDtTm": "GrpHdr",    # Creation DateTime
            "PmtInf": "Document",   # Payment Information
            "PmtMtd": "PmtInf",     # Payment Method
        }

        root = self._parse_xml(xml)
        if root is None:
            return [_PARSE_ERROR]

        return self._require_elements(
            root, required, self._WRAPPERS_BY_TYPE[MessageType.PAIN_001]
        )

    # ==================== SWIFT MT Validation ====================
    
    def verify_swift_mt(
        self,
        mt_string: str,
        mt_type: SwiftMtType = SwiftMtType.MT103
    ) -> MessageResult:
        """
        Verify legacy SWIFT MT message format.
        
        Args:
            mt_string: The MT message to validate
            mt_type: Expected message type (MT103, MT202, etc.)
            
        Returns:
            MessageResult with validation status
        """
        errors = []
        warnings = []

        # MT messages travel framed in block 4 ({4: ... -}); an unframed
        # blob is not a message and must not validate (#63). Block 5 (and
        # any trailer) may follow the -} closer, so the match is not
        # anchored to end-of-string.
        block4 = re.search(r"\{4:\r?\n(.*?)\r?\n-\}", mt_string, re.DOTALL)
        if block4:
            body = block4.group(1)
        else:
            errors.append("Missing block-4 framing ({4: ... -})")
            body = ""

        # Fields are read from the block-4 body only: tags in headers,
        # trailers, or injected prefixes must never satisfy required-field
        # checks. Line-anchored first-match parsing keeps colons inside
        # values intact so length checks see the full value (#63).
        fields = self._parse_mt_fields(body)

        # Duplicate tags inside the body are ambiguous (#63).
        for tag in self._duplicate_mt_tags(body):
            errors.append(f"Duplicate field {tag}: ambiguous tag occurrence")

        errors.extend(self._collect_field_errors(mt_type, fields))

        return MessageResult(
            valid=len(errors) == 0,
            message_type=mt_type.value,
            errors=errors,
            warnings=warnings,
            field_count=len(fields)
        )

    def _collect_field_errors(
        self, mt_type: SwiftMtType, fields: Dict[str, str]
    ) -> List[str]:
        """Required-field, balance, and per-field format errors."""
        errors = []
        for field_tag, field_name in self._required_fields_for(mt_type).items():
            if field_tag not in fields:
                errors.append(
                    f"Missing required field {field_tag}: {field_name}"
                )

        # MT940 carries its opening balance in 60F (final) or 60M
        # (intermediate); the tag alone is not a balance — the value
        # must be populated.
        if (
            mt_type == SwiftMtType.MT940
            and not fields.get("60F")
            and not fields.get("60M")
        ):
            errors.append("Missing required field 60F/60M: Opening Balance")

        if "32A" in fields and not self._validate_32a_field(fields["32A"]):
            errors.append(
                "Field 32A has invalid format (expected: YYMMDDCCY + Amount)"
            )

        # Transaction reference: max 16 characters
        if "20" in fields and len(fields["20"]) > 16:
            errors.append("Field 20 exceeds maximum length of 16 characters")

        return errors

    def _required_fields_for(self, mt_type: SwiftMtType) -> Dict[str, str]:
        """Required-field set for the MT type; minimal set otherwise."""
        if mt_type == SwiftMtType.MT103:
            return self.mt103_required_fields
        if mt_type == SwiftMtType.MT202:
            return self.mt202_required_fields
        if mt_type == SwiftMtType.MT940:
            return self.mt940_required_fields
        return {"20": "Transaction Reference"}  # Minimal
    
    @staticmethod
    def _duplicate_mt_tags(mt_string: str) -> List[str]:
        """Line-anchored tags occurring more than once, in first-seen order."""
        seen = set()
        duplicates = []
        for match in re.finditer(r"^:(\d{2}[A-Z]?):", mt_string, re.MULTILINE):
            tag = match.group(1)
            if tag in seen and tag not in duplicates:
                duplicates.append(tag)
            seen.add(tag)
        return duplicates

    def _parse_mt_fields(self, mt_string: str) -> Dict[str, str]:
        """Parse SWIFT MT body into a field dictionary.

        Line-anchored tags only, first occurrence wins (consumers read
        first-match), and the value runs to end-of-line so embedded
        colons are not truncated.
        """
        fields = {}
        for tag, value in re.findall(
            r"^:(\d{2}[A-Z]?):(.*)$", mt_string, re.MULTILINE
        ):
            fields.setdefault(tag, value.strip())
        return fields

    def _validate_32a_field(self, value: str) -> bool:
        """Validate Field 32A: Value Date/Currency/Amount.

        Grammar: 6-digit calendar date (YYMMDD) + 3-letter currency +
        positive amount with a mandatory comma decimal separator, total
        at most 15 chars per SWIFT 15d (integer part up to 14 digits,
        e.g. 260118USD1000,00). Embedded whitespace is not part of the
        grammar, and an all-zero amount is not a settlement.
        """
        text = value.strip()
        if re.search(r"\s", text):
            return False
        match = re.fullmatch(
            r"([0-9]{6})([A-Z]{3})([0-9]{1,14},[0-9]{0,3})", text
        )
        if not match or len(match.group(3)) > 15:
            return False
        if not re.search(r"[1-9]", match.group(3)):
            return False
        try:
            datetime.strptime(match.group(1), "%y%m%d")
        except ValueError:
            return False
        return True
    
    # ==================== BIC/IBAN Validation ====================
    
    def verify_bic(self, bic: str, llm_says_valid: bool) -> MessageResult:
        """
        Verify BIC (Bank Identifier Code) format.
        
        BIC format: 4 letters (bank) + 2 letters (country) + 2 alphanumeric (location) + optional 3 (branch)
        """
        # BIC regex: 4 letters + 2 letters + 2 alphanum + optional 3 alphanum
        pattern = r'^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$'
        is_valid = bool(re.match(pattern, bic.upper()))
        
        verified = (llm_says_valid == is_valid)
        
        errors = []
        if not verified:
            errors.append(f"BIC '{bic}' is {'valid' if is_valid else 'invalid'}, but LLM said {'valid' if llm_says_valid else 'invalid'}")
        
        return MessageResult(
            valid=verified,
            message_type="BIC",
            errors=errors,
            warnings=[]
        )
    
    def verify_iban(self, iban: str, llm_says_valid: bool) -> MessageResult:
        """
        Verify IBAN (International Bank Account Number) format and checksum.
        
        IBAN: 2 letters (country) + 2 digits (check) + up to 30 alphanumeric (BBAN)
        """
        iban_clean = iban.replace(" ", "").upper()
        
        # Basic format check
        if not re.match(r'^[A-Z]{2}\d{2}[A-Z0-9]{1,30}$', iban_clean):
            is_valid = False
        else:
            # Checksum validation (MOD 97)
            is_valid = self._validate_iban_checksum(iban_clean)
        
        verified = (llm_says_valid == is_valid)
        
        errors = []
        if not verified:
            errors.append(f"IBAN '{iban}' is {'valid' if is_valid else 'invalid'}, but LLM said {'valid' if llm_says_valid else 'invalid'}")
        
        return MessageResult(
            valid=verified,
            message_type="IBAN",
            errors=errors,
            warnings=[]
        )
    
    def _validate_iban_checksum(self, iban: str) -> bool:
        """Validate IBAN using MOD 97 checksum"""
        # Rearrange: move first 4 chars to end
        rearranged = iban[4:] + iban[:4]
        
        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        numeric = ""
        for char in rearranged:
            if char.isalpha():
                numeric += str(ord(char) - ord('A') + 10)
            else:
                numeric += char
        
        # Check if mod 97 == 1
        return int(numeric) % 97 == 1
