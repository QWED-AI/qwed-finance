"""
Verification Receipt - Cryptographic proof of verification for audit trails
Required for regulatory compliance (SEC, OCC, FinCEN)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
from enum import Enum
import hashlib
import json
import uuid


class VerificationEngine(Enum):
    """QWED verification engines used"""
    SYMPY = "SymPy"          # Symbolic math
    Z3 = "Z3"                # SMT solver
    SQLGLOT = "SQLGlot"      # SQL AST
    XML_SCHEMA = "XMLSchema" # XML validation
    DECIMAL = "Decimal"      # Exact arithmetic
    REGEX = "Regex"          # Pattern matching


class VerificationStatus(Enum):
    """Verification outcome"""
    VERIFIED = "verified"
    REJECTED = "rejected"
    INSUFFICIENT_DATA = "insufficient_data"
    ERROR = "error"


@dataclass
class VerificationReceipt:
    """
    Cryptographic proof of verification for audit trails.
    
    Every verification generates a receipt that can be:
    - Stored in audit logs
    - Submitted to regulators
    - Used for dispute resolution
    """
    
    # Unique identifiers
    receipt_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Timestamps
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Input hashing
    input_hash: str = ""          # SHA-256 of LLM output
    input_preview: str = ""       # First 100 chars for human readability
    
    # Verification details
    guard_name: str = ""          # Which guard performed verification
    engine_used: VerificationEngine = VerificationEngine.DECIMAL
    status: VerificationStatus = VerificationStatus.VERIFIED
    
    # Results
    verified: bool = True
    computed_value: Optional[str] = None
    llm_value: Optional[str] = None
    difference: Optional[str] = None
    
    # Proof chain
    proof_steps: List[str] = field(default_factory=list)
    formula_used: Optional[str] = None
    
    # Rule violations (if any)
    violations: List[str] = field(default_factory=list)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert receipt to dictionary for JSON serialization"""
        return {
            "receipt_id": self.receipt_id,
            "timestamp": self.timestamp,
            "input_hash": self.input_hash,
            "input_preview": self.input_preview,
            "guard_name": self.guard_name,
            "engine_used": self.engine_used.value,
            "status": self.status.value,
            "verified": self.verified,
            "computed_value": self.computed_value,
            "llm_value": self.llm_value,
            "difference": self.difference,
            "proof_steps": self.proof_steps,
            "formula_used": self.formula_used,
            "violations": self.violations,
            "metadata": self.metadata
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize receipt to JSON"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def get_signature(self) -> str:
        """
        Generate cryptographic signature of the receipt.
        Can be used to verify receipt hasn't been tampered with.
        """
        content = json.dumps({
            "receipt_id": self.receipt_id,
            "timestamp": self.timestamp,
            "input_hash": self.input_hash,
            "verified": self.verified,
            "engine_used": self.engine_used.value
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


class ReceiptGenerator:
    """
    Factory for generating verification receipts.
    Ensures consistent hashing and timestamping across all guards.
    """
    
    @staticmethod
    def hash_input(input_data: Any) -> str:
        """Generate SHA-256 hash of input data.

        backslashreplace: unpaired surrogates appear in malformed input
        exactly when validation is about to reject it — hashing must
        never raise instead of returning the rejected result (#88).
        """
        if isinstance(input_data, str):
            content = input_data
        elif isinstance(input_data, (dict, list)):
            content = json.dumps(input_data, sort_keys=True)
        else:
            content = str(input_data)
        return hashlib.sha256(
            content.encode("utf-8", "backslashreplace")
        ).hexdigest()
    
    @staticmethod
    def create_receipt(
        guard_name: str,
        engine: VerificationEngine,
        llm_output: Any,
        verified: bool,
        computed_value: Optional[str] = None,
        formula: Optional[str] = None,
        proof_steps: Optional[List[str]] = None,
        violations: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> VerificationReceipt:
        """
        Create a verification receipt with automatic hashing and timestamping.
        
        Args:
            guard_name: Name of the guard (e.g., "ComplianceGuard.verify_aml_flag")
            engine: Which QWED engine performed the verification
            llm_output: The LLM output that was verified
            verified: Whether verification passed
            computed_value: The deterministically computed value
            formula: Mathematical formula used
            proof_steps: Step-by-step proof derivation
            violations: List of rule violations (if any)
            metadata: Additional context
            
        Returns:
            VerificationReceipt ready for audit logging
        """
        input_str = str(llm_output)
        
        return VerificationReceipt(
            input_hash=ReceiptGenerator.hash_input(llm_output),
            input_preview=input_str[:100] + "..." if len(input_str) > 100 else input_str,
            guard_name=guard_name,
            engine_used=engine,
            status=VerificationStatus.VERIFIED if verified else VerificationStatus.REJECTED,
            verified=verified,
            computed_value=computed_value,
            llm_value=input_str if len(input_str) <= 50 else None,
            formula_used=formula,
            proof_steps=proof_steps or [],
            violations=violations or [],
            metadata=metadata or {}
        )


class AuditLog:
    """
    In-memory audit log for verification receipts.
    In production, this would connect to a database or SIEM.
    """
    
    def __init__(self):
        self.receipts: List[VerificationReceipt] = []
    
    def log(self, receipt: VerificationReceipt) -> str:
        """Log a receipt and return its ID"""
        self.receipts.append(receipt)
        return receipt.receipt_id
    
    def get_receipt(self, receipt_id: str) -> Optional[VerificationReceipt]:
        """Retrieve a receipt by ID"""
        for receipt in self.receipts:
            if receipt.receipt_id == receipt_id:
                return receipt
        return None
    
    def get_failures(self) -> List[VerificationReceipt]:
        """Get all failed verifications"""
        return [r for r in self.receipts if not r.verified]
    
    def get_by_guard(self, guard_name: str) -> List[VerificationReceipt]:
        """Get all receipts from a specific guard"""
        return [r for r in self.receipts if guard_name in r.guard_name]
    
    def export_json(self) -> str:
        """Export all receipts as JSON"""
        return json.dumps([r.to_dict() for r in self.receipts], indent=2)
    
    def summary(self) -> Dict[str, Any]:
        """Get summary statistics"""
        total = len(self.receipts)
        passed = sum(1 for r in self.receipts if r.verified)
        
        by_guard: Dict[str, int] = {}
        for r in self.receipts:
            guard = r.guard_name.split(".")[0]
            by_guard[guard] = by_guard.get(guard, 0) + 1
        
        return {
            "total_verifications": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": f"{(passed/total)*100:.1f}%" if total > 0 else "N/A",
            "by_guard": by_guard
        }
