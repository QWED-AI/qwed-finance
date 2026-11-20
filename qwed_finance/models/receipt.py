"""
Verification Receipt - tamper-evident evidence records for audit trails.

Integrity is checked with VerificationReceipt.get_signature: HMAC-SHA256
over the full canonical receipt, keyed by the verifier instance. A
ReceiptSigner wires that primitive into the runtime flow (#90): receipts
are signed as they enter an AuditLog, and exports carry the signatures.
This is tamper evidence for holders of the signing key only — it carries
no issuer identity and is not third-party-verifiable attestation; the
regulator-facing attestation format is tracked in #37.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
from enum import Enum
import hashlib
import hmac
import json
import math
import uuid

from .signing import (
    EXPORT_ALG,
    EXPORT_SCHEMA,
    ReceiptSignatureError,
    ReceiptSigner,
)

# The fields get_signature signs — everything to_dict() exports. Receipts
# carry exactly these content fields in an export, plus their signature and
# signature_key_id. FIELD_MUTATIONS in tests/test_receipt_signature.py pins
# this list to to_dict().
RECEIPT_CONTENT_FIELDS = (
    "receipt_id",
    "timestamp",
    "input_hash",
    "input_preview",
    "guard_name",
    "engine_used",
    "status",
    "verified",
    "computed_value",
    "llm_value",
    "difference",
    "proof_steps",
    "formula_used",
    "violations",
    "metadata",
)


def _reject_duplicate_keys(pairs: List[tuple]) -> Dict[str, Any]:
    """JSON object hook: a repeated member name refuses the whole parse.

    ``json.loads`` keeps only the last value of a repeated name, so a
    signed export whose text carries two ``verified`` or two ``receipts``
    members could verify here while a first-wins consumer reads
    different evidence from the same text. Receipts this package emits
    can never contain repeats (they serialise Python dicts); only a
    hand-crafted or tampered document can, and it must not verify.
    """
    parsed: Dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ReceiptSignatureError(
                f"duplicate JSON member name {key!r} — ambiguous evidence "
                "does not verify"
            )
        parsed[key] = value
    return parsed


class VerificationEngine(Enum):
    """QWED verification engines used"""

    SYMPY = "SymPy"  # Symbolic math
    Z3 = "Z3"  # SMT solver
    SQLGLOT = "SQLGlot"  # SQL AST
    XML_SCHEMA = "XMLSchema"  # XML validation
    DECIMAL = "Decimal"  # Exact arithmetic
    REGEX = "Regex"  # Pattern matching


class VerificationStatus(Enum):
    """Verification outcome"""

    VERIFIED = "verified"
    REJECTED = "rejected"
    INSUFFICIENT_DATA = "insufficient_data"
    ERROR = "error"


def _json_key_spelling(key: Any) -> str:
    """Spell a mapping key exactly as json.dumps exports string keys.

    json.dumps accepts only str, int, float, bool, and None keys and
    raises for anything else, so unsupported key types raise here too:
    str()-stringifying an arbitrary object would mint unstable keys like
    "<object at 0x7f...>" that no other process can reproduce (#89).
    """
    if isinstance(key, str):
        return key
    if key is True:
        return "true"
    if key is False:
        return "false"
    if key is None:
        return "null"
    if isinstance(key, float):
        if math.isnan(key):
            return "NaN"
        if math.isinf(key):
            return "Infinity" if key > 0 else "-Infinity"
        return str(key)
    if isinstance(key, int):
        return str(key)
    raise TypeError(
        f"keys must be str, int, float, bool or None, not {type(key).__name__}"
    )


def _normalize_metadata_keys(value: Any) -> Any:
    """Recursively rewrite mapping keys to their JSON spelling.

    Applies at every depth — metadata dicts nested inside dicts, lists,
    or tuples — so canonical signing (sort_keys) can never crash on key
    types that to_json() has always exported fine (#89 review).
    Spelling collisions (True and "true" in one mapping) raise rather
    than emitting duplicate JSON keys.
    """
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for item_key, item_value in value.items():
            str_key = _json_key_spelling(item_key)
            if str_key in normalized:
                raise TypeError(
                    f"metadata key collision after string normalization: {str_key!r}"
                )
            normalized[str_key] = _normalize_metadata_keys(item_value)
        return normalized
    if isinstance(value, tuple):
        return tuple(_normalize_metadata_keys(item) for item in value)
    if isinstance(value, list):
        return [_normalize_metadata_keys(item) for item in value]
    return value


@dataclass
class VerificationReceipt:
    """
    Evidence record of a verification run for audit trails.

    Every verification generates a receipt that can be:
    - Stored in audit logs
    - Used for dispute resolution
    - Checked for in-place tampering via get_signature (key holders)

    get_signature proves integrity to holders of the signing key; it does
    not establish issuer identity or third-party verifiability (see #37).
    """

    # Unique identifiers
    receipt_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Timestamps
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Input hashing
    input_hash: str = ""  # SHA-256 of LLM output
    input_preview: str = ""  # First 100 chars for human readability

    # Verification details
    guard_name: str = ""  # Which guard performed verification
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

    # Signature over the content fields above (ReceiptSigner, #90). These
    # are deliberately outside to_dict(): get_signature signs the content,
    # and a signature cannot sign itself. They travel with the receipt only
    # in exports (to_export_dict), where verification strips them before
    # recomputing.
    signature: Optional[str] = None
    signature_key_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert receipt to dictionary for JSON serialization.

        Metadata mapping keys — at every depth — are rewritten to the
        exact spelling json.dumps exports (int 2 -> "2", True -> "true",
        None -> "null"), so signing covers the exportable artifact and a
        never-signed receipt can never block audit export (#89 review).
        Spelling collisions (True and "true" in one mapping) are
        ambiguous and raise rather than emitting duplicate JSON keys.
        """
        metadata = _normalize_metadata_keys(self.metadata)
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
            "metadata": metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize receipt to JSON"""
        return json.dumps(self.to_dict(), indent=indent)

    def to_export_dict(self) -> Dict[str, Any]:
        """Content fields plus the signature fields, for audit exports.

        The inverse of signature verification: consumers verify by
        stripping ``signature`` and ``signature_key_id``, recomputing
        get_signature over what remains, and comparing. An unsigned
        receipt exports with both fields null — explicit, never implicit.
        """
        exported = self.to_dict()
        exported["signature"] = self.signature
        exported["signature_key_id"] = self.signature_key_id
        return exported

    def get_signature(self, key: bytes) -> str:
        """
        HMAC-SHA256 signature over the full canonical receipt.

        Signs every field returned by to_dict() (canonical JSON, sorted
        keys), so mutating any of them — computed_value, llm_value,
        difference, status, violations, proof_steps, formula_used,
        metadata — changes the signature (#44).

        The key must be held by the verifier instance that issues or
        checks receipts; there is intentionally no default key. The
        previous unkeyed SHA-256 over a 5-field subset let anyone who
        touched a receipt alter it — or mint one wholesale — without
        detection, which is weaker than no signature at all (#44).

        Fields that are not JSON-serializable raise TypeError, and
        metadata key collisions after string normalization raise TypeError
        at any depth (via to_dict, so to_json/export_json reject them
        identically). Non-finite floats raise ValueError: allow_nan=False
        keeps NaN/Infinity tokens out of the payload — standard-JSON
        verifiers could not reproduce a signature over them. A receipt
        that cannot produce a canonical artifact must not sign.

        Tamper evidence only: anyone without the key cannot forge or
        validate signatures, but this envelope carries no issuer
        identity — third-party-verifiable attestation is tracked in #37.
        """
        content = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return hmac.new(key, content.encode("utf-8"), hashlib.sha256).hexdigest()


class ReceiptGenerator:
    """
    Factory for generating verification receipts.
    Ensures consistent hashing and timestamping across all guards.
    """

    @staticmethod
    def hash_input(input_data: Any) -> str:
        """Generate SHA-256 hash of input data.

        surrogatepass: unpaired surrogates appear in malformed input
        exactly when validation is about to reject it — hashing must
        never raise instead of returning the rejected result, and must
        stay injective: backslashreplace collapses an unpaired
        surrogate and the literal "\ud800" text to one hash, letting
        two different documents share an audited receipt (#88).
        """
        if isinstance(input_data, str):
            content = input_data
        elif isinstance(input_data, (dict, list)):
            content = json.dumps(input_data, sort_keys=True)
        else:
            content = str(input_data)
        return hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()

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
        metadata: Optional[Dict[str, Any]] = None,
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
            input_preview=(
                input_str[:100] + "..." if len(input_str) > 100 else input_str
            ),
            guard_name=guard_name,
            engine_used=engine,
            status=(
                VerificationStatus.VERIFIED if verified else VerificationStatus.REJECTED
            ),
            verified=verified,
            computed_value=computed_value,
            llm_value=input_str if len(input_str) <= 50 else None,
            formula_used=formula,
            proof_steps=proof_steps or [],
            violations=violations or [],
            metadata=metadata or {},
        )


# Deepest container nesting accepted in metadata, proof_steps or violations,
# counting the field's own container. A fixed bound, not the interpreter's
# recursion limit: that limit depends on where on the stack a call runs, so
# a receipt the snapshot accepted could still overflow signing, verification
# or export, which run deeper. Audit metadata is shallow in practice.
MAX_NESTING_DEPTH = 32


def _children(item: Any) -> Optional[Any]:
    """An iterator over a list's items or a dict's values; None for scalars."""
    if isinstance(item, dict):
        return iter(item.values())
    if isinstance(item, list):
        return iter(item)
    return None


def _nesting_depth(value: Any) -> int:
    """Deepest list/dict nesting in plain JSON data, counted iteratively.

    Walks with a stack holding one iterator per open container, so memory
    grows with the nesting depth, not with the width of a list or dict: a
    list of millions of scalar tags costs one iterator, not one entry each.
    """
    root = _children(value)
    if root is None:
        return 0
    end = object()
    deepest = 1
    stack = [root]
    while stack:
        child = next(stack[-1], end)
        if child is end:
            stack.pop()
            continue
        nested = _children(child)
        if nested is not None:
            stack.append(nested)
            deepest = max(deepest, len(stack))
    return deepest


def _detached_snapshot(receipt: VerificationReceipt) -> VerificationReceipt:
    """Copy a receipt as plain JSON data, without running caller code.

    copy.deepcopy honours ``__deepcopy__`` on caller-supplied metadata, so
    a dict or list subclass can return itself and keep the "copy" aliased
    to the caller's object. Instead the content is read once through
    ``to_dict()`` and round-tripped through canonical JSON: the snapshot
    holds only built-in str, int, float, bool, None, list and dict, with
    nothing shared with the caller. The canonical encoding — and so the
    signature — is unchanged by the round trip.

    Content that cannot be canonically encoded raises here, so it never
    enters the log: TypeError for unserializable objects, colliding keys
    and an ``engine_used`` or ``status`` that is not an enum member;
    ValueError for NaN/Infinity and for nesting deeper than
    MAX_NESTING_DEPTH.
    """
    if not isinstance(receipt.engine_used, VerificationEngine):
        raise TypeError(
            f"engine_used must be a VerificationEngine, not "
            f"{type(receipt.engine_used).__name__}"
        )
    if not isinstance(receipt.status, VerificationStatus):
        raise TypeError(
            f"status must be a VerificationStatus, not "
            f"{type(receipt.status).__name__}"
        )
    try:
        content = json.loads(json.dumps(receipt.to_dict(), allow_nan=False))
    except RecursionError:
        raise ValueError(
            f"receipt content nests deeper than {MAX_NESTING_DEPTH} containers"
        ) from None
    for name in ("metadata", "proof_steps", "violations"):
        if _nesting_depth(content[name]) > MAX_NESTING_DEPTH:
            raise ValueError(f"{name} nests deeper than {MAX_NESTING_DEPTH} containers")
    content["engine_used"] = VerificationEngine(content["engine_used"])
    content["status"] = VerificationStatus(content["status"])
    return VerificationReceipt(
        **content,
        signature=receipt.signature,
        signature_key_id=receipt.signature_key_id,
    )


class AuditLog:
    """
    In-memory audit log for verification receipts.
    In production, this would connect to a database or SIEM.

    With a signer configured (constructor argument, or
    QWED_RECEIPT_SIGNING_KEY in the environment), every receipt is signed
    as it enters the log and exports carry the signatures plus an
    envelope signature over the whole export (#90). Without one, exports
    are explicitly unsigned. A configured signer also refuses to export
    receipts it cannot vouch for: tampered in place after logging, or
    appended unsigned — the export fails closed rather than shipping
    evidence that cannot be verified.
    """

    def __init__(self, signer: Optional[ReceiptSigner] = None):
        self.signer = signer if signer is not None else ReceiptSigner.from_env()
        self.receipts: List[VerificationReceipt] = []

    def log(self, receipt: VerificationReceipt) -> str:
        """Log a receipt and return its ID.

        Signs the receipt when a signer is configured, so every retained
        receipt carries its signature from the moment it enters the audit
        trail — the signature is minted at retention, not retrofitted at
        export. A receipt whose metadata cannot be canonically encoded
        (unserializable objects, NaN/Infinity) raises before it is
        appended: it must not enter the trail looking signed when it
        cannot be.

        An already-signed receipt is verified before it is re-signed:
        replacing a signature without checking it would mint a fresh
        attestation over possibly tampered content, so a receipt whose
        existing signature does not verify — edited after it was signed,
        or signed under a key outside this signer's rotation window — is
        refused. A half-signed receipt (a signature without a key id, or
        the reverse) is refused the same way.

        The log retains an independent snapshot of the signed receipt, so
        later changes to the caller's object — including a second log
        re-signing it under another key — never alter the evidence this
        log holds. The snapshot is taken once, before verification, as
        plain JSON data (no caller-defined copy hooks run, so nothing in it
        can stay aliased to the caller's object), and that one copy is
        verified, signed and retained, so the verified,
        signed and retained content are identical even if the caller's
        object changes concurrently. The new signature is then written
        back to the caller's receipt.
        """
        try:
            snapshot = _detached_snapshot(receipt)
        except (TypeError, ValueError) as error:
            carries_signature_state = (
                receipt.signature is not None or receipt.signature_key_id is not None
            )
            if self.signer is not None and carries_signature_state:
                raise ReceiptSignatureError(
                    f"signed receipt {receipt.receipt_id} cannot be re-verified: "
                    f"{error}"
                ) from error
            raise
        if self.signer is not None:
            if (snapshot.signature is None) != (snapshot.signature_key_id is None):
                raise ReceiptSignatureError(
                    f"receipt {snapshot.receipt_id} is half-signed — a "
                    "signature without a key id (or the reverse) cannot be "
                    "verified or re-signed"
                )
            if snapshot.signature is not None:
                self.signer.verify_receipt(snapshot)
            self.signer.sign_receipt(snapshot)
            receipt.signature = snapshot.signature
            receipt.signature_key_id = snapshot.signature_key_id
        self.receipts.append(snapshot)
        return snapshot.receipt_id

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
        """Export all receipts as a signed audit envelope.

        The export is an object, not a bare list: schema, algorithm, key
        id, signature and the receipts. With a signer configured the
        envelope signature covers everything else in the document — every
        receipt and its per-receipt signature — so tampering, truncation
        and reordering of the export all fail verification. Each receipt's
        own signature is verified before export; one that does not verify
        (edited in place after logging, or appended unsigned) stops the
        export.

        Without a signer the envelope is explicitly unsigned: ``alg``,
        ``signature_key_id`` and ``signature`` are null, and every receipt
        exports with null signature fields — a receipt signed elsewhere
        keeps its signature on the object, but an unsigned envelope is
        not tamper-evident as a whole, so carrying per-receipt signatures
        in it would suggest evidence the envelope cannot back. Unsigned
        is a state a consumer must opt into, never one it mistakes for
        signed.

        Each receipt is snapshotted (the same detached copy log() makes)
        before it is verified and serialised,
        so the exported content is exactly the content that was verified
        even if another thread mutates the retained receipt mid-export.
        """
        receipts = []
        if self.signer is not None:
            for receipt in self.receipts:
                try:
                    snapshot = _detached_snapshot(receipt)
                except (TypeError, ValueError) as error:
                    raise ReceiptSignatureError(
                        f"receipt {receipt.receipt_id} cannot be verified for "
                        f"export: {error}"
                    ) from error
                self.signer.verify_receipt(snapshot)
                receipts.append(snapshot.to_export_dict())
            document: Dict[str, Any] = {
                "schema": EXPORT_SCHEMA,
                "alg": EXPORT_ALG,
                "signature_key_id": self.signer.signing_kid,
                "signature": None,
                "receipts": receipts,
            }
            self.signer.sign_export_document(document)
        else:
            for receipt in self.receipts:
                snapshot = _detached_snapshot(receipt).to_export_dict()
                snapshot["signature"] = None
                snapshot["signature_key_id"] = None
                receipts.append(snapshot)
            document = {
                "schema": EXPORT_SCHEMA,
                "alg": None,
                "signature_key_id": None,
                "signature": None,
                "receipts": receipts,
            }
        return json.dumps(document, indent=2)

    def verify_export_json(self, export: str) -> None:
        """Verify an exported audit envelope; raise on any tampering.

        Requires a signer: key material is what verification means here.
        Every failure — invalid JSON, a duplicate member name, unsigned
        export, unknown key id, envelope or receipt signature mismatch,
        missing or injected fields — raises ReceiptSignatureError. A clean
        export returns None.

        Duplicate JSON member names are refused at every level of the
        parsed document: ``json.loads`` keeps only the last value for a
        repeated name, so a document that verifies here could still be
        read differently by a first-wins consumer — ambiguous evidence
        does not verify.
        """
        if self.signer is None:
            raise ReceiptSignatureError(
                "no signer configured — provide one (or set "
                "QWED_RECEIPT_SIGNING_KEY) to verify exports"
            )
        try:
            document = json.loads(export, object_pairs_hook=_reject_duplicate_keys)
        except ValueError as error:
            # JSONDecodeError, and the plain ValueError Python 3.11+ raises
            # for an integer literal past the digit limit.
            raise ReceiptSignatureError(f"export is not valid JSON: {error}") from error
        except RecursionError:
            raise ReceiptSignatureError(
                "export nests deeper than the parser's recursion limit"
            ) from None
        self.signer.verify_export_document(document)

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
            "by_guard": by_guard,
        }
