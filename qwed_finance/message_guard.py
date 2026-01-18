"""
Message Guard - ISO 20022 and SWIFT message validation
Ensures LLM-generated banking messages are structurally correct
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum
import re


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
                etree.fromstring(xml_string.encode())
                return True
            except:
                return False
        else:
            # Fallback: basic bracket matching
            return xml_string.count("<") == xml_string.count(">")
    
    def _validate_pacs008(self, xml: str) -> List[str]:
        """Validate pacs.008 Customer Credit Transfer"""
        errors = []
        
        # Required elements for pacs.008
        required = [
            "GrpHdr",           # Group Header
            "MsgId",            # Message ID
            "CreDtTm",          # Creation DateTime
            "NbOfTxs",          # Number of Transactions
            "CdtTrfTxInf",      # Credit Transfer Info
            "IntrBkSttlmAmt",   # Interbank Settlement Amount
            "DbtrAgt",          # Debtor Agent
            "CdtrAgt",          # Creditor Agent
        ]
        
        for element in required:
            if f"<{element}" not in xml and f"<{element}>" not in xml:
                errors.append(f"Missing required element: {element}")
        
        # Validate amount format
        if "Ccy=" in xml:
            # Check currency code is 3 uppercase letters
            ccy_match = re.search(r'Ccy="([A-Z]{3})"', xml)
            if not ccy_match:
                errors.append("Invalid currency code format (must be 3 uppercase letters)")
        
        return errors
    
    def _validate_camt053(self, xml: str) -> List[str]:
        """Validate camt.053 Bank Statement"""
        errors = []
        
        required = [
            "GrpHdr",
            "Stmt",             # Statement
            "Acct",             # Account
            "Bal",              # Balance
        ]
        
        for element in required:
            if f"<{element}" not in xml:
                errors.append(f"Missing required element: {element}")
        
        return errors
    
    def _validate_pain001(self, xml: str) -> List[str]:
        """Validate pain.001 Customer Payment Initiation"""
        errors = []
        
        required = [
            "GrpHdr",
            "MsgId",
            "CreDtTm",
            "PmtInf",           # Payment Information
            "PmtMtd",           # Payment Method
        ]
        
        for element in required:
            if f"<{element}" not in xml:
                errors.append(f"Missing required element: {element}")
        
        return errors
    
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
        
        # Parse fields from MT message
        fields = self._parse_mt_fields(mt_string)
        
        # Get required fields for this message type
        if mt_type == SwiftMtType.MT103:
            required = self.mt103_required_fields
        elif mt_type == SwiftMtType.MT202:
            required = self.mt202_required_fields
        else:
            required = {"20": "Transaction Reference"}  # Minimal
        
        # Check required fields
        for field_tag, field_name in required.items():
            if field_tag not in fields:
                errors.append(f"Missing required field {field_tag}: {field_name}")
        
        # Validate field formats
        if "32A" in fields:
            # Format: YYMMDDCCY######.## (Date + Currency + Amount)
            if not self._validate_32a_field(fields["32A"]):
                errors.append("Field 32A has invalid format (expected: YYMMDDCCY + Amount)")
        
        if "20" in fields:
            # Transaction reference: max 16 characters
            if len(fields["20"]) > 16:
                errors.append("Field 20 exceeds maximum length of 16 characters")
        
        return MessageResult(
            valid=len(errors) == 0,
            message_type=mt_type.value,
            errors=errors,
            warnings=warnings,
            field_count=len(fields)
        )
    
    def _parse_mt_fields(self, mt_string: str) -> Dict[str, str]:
        """Parse SWIFT MT message into field dictionary"""
        fields = {}
        
        # SWIFT MT format: :20:value or :32A:YYMMDDCCY######
        pattern = r':(\d{2}[A-Z]?):([^\r\n:]+)'
        matches = re.findall(pattern, mt_string)
        
        for tag, value in matches:
            fields[tag] = value.strip()
        
        return fields
    
    def _validate_32a_field(self, value: str) -> bool:
        """Validate Field 32A: Value Date/Currency/Amount"""
        # Format: YYMMDDCCY######.## (e.g., 260118USD1000,00)
        pattern = r'^\d{6}[A-Z]{3}[\d,\.]+$'
        return bool(re.match(pattern, value.replace(" ", "")))
    
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
