"""Receipt signing — HMAC-SHA256 tamper evidence wired into the audit trail (#90).

`VerificationReceipt.get_signature` (#44) is the primitive: HMAC-SHA256 over
the full canonical receipt, key held by the verifier. Nothing in the runtime
flow called it, so exported artifacts travelled without a stored signature
to compare against. This module is that wiring: a `ReceiptSigner` resolves
key material from the environment (or is constructed directly), signs every
receipt as it enters an `AuditLog`, and attaches signatures to exports.

The envelope follows the shape of qwed-verification's Verification Context
v1.1 attestation (spec/v1.1/verification-context.md):

- every signature names a key id (`kid`) so keys can rotate without
  invalidating evidence signed under retired keys, as long as the retired
  key stays in the verification window;
- the signature covers the artifact minus the signature field, so the
  signature can never sign itself;
- verification fails closed on every mismatch: unknown `kid`, wrong
  algorithm, unsigned artifact, tampered byte — refuse, never pass.

It stays HMAC on purpose. This is tamper evidence for holders of the
signing key, not third-party attestation: any HMAC verifier can also mint
signatures, and the envelope carries no issuer identity. The
regulator-facing ES256 attestation envelope is tracked in #37 and can wrap
this format without conflicting with it.

Key material is hex-encoded and must decode to at least 32 bytes (256
bits) — a passphrase pasted as raw bytes must not silently become a key.
"""

import hashlib
import hmac
import json
import os
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "EXPORT_ALG",
    "EXPORT_SCHEMA",
    "MIN_KEY_BYTES",
    "ReceiptSignatureError",
    "ReceiptSigner",
    "SigningKeyError",
    "parse_key_material",
]

EXPORT_SCHEMA = "qwed-finance/audit-log/v1"
EXPORT_ALG = "HMAC-SHA256"
MIN_KEY_BYTES = 32

_SIGNING_KEY_ENV = "QWED_RECEIPT_SIGNING_KEY"
_VERIFICATION_KEYS_ENV = "QWED_RECEIPT_VERIFICATION_KEYS"

# Fields a receipt carries in an export beyond its signed content.
_RECEIPT_SIGNATURE_FIELDS = ("signature", "signature_key_id")


class SigningKeyError(ValueError):
    """Signing key material or configuration is unusable.

    Raised at construction time so a misconfigured deployment fails loudly
    before it can emit unsigned receipts it believes are signed.
    """


class ReceiptSignatureError(Exception):
    """A signature did not verify, or an artifact is unsigned when it must be signed.

    Verification is fail-closed: any tampered field, unknown key id, missing
    signature or malformed artifact raises this rather than passing.
    """


def parse_key_material(material: str, *, source: str) -> bytes:
    """Hex-decode signing key material, refusing weak or malformed keys.

    Surrounding whitespace is stripped (shell ``$(cat keyfile)`` often
    carries a trailing newline); an empty value or a value that is not
    valid hex raises, and so does anything shorter than ``MIN_KEY_BYTES``
    (256 bits) once decoded. Failing closed here beats silently signing
    with a guessable key.

    ``bytes.fromhex`` ignores whitespace between hex pairs, so such
    material still decodes deterministically.
    """
    if not isinstance(material, str):
        raise SigningKeyError(
            f"{source} must be a hex string, not {type(material).__name__}"
        )
    stripped = material.strip()
    if not stripped:
        raise SigningKeyError(f"{source} is empty — unset it to disable signing")
    try:
        key = bytes.fromhex(stripped)
    except ValueError:
        raise SigningKeyError(
            f"{source} is not valid hex — encode the raw key bytes as hex"
        ) from None
    if len(key) < MIN_KEY_BYTES:
        raise SigningKeyError(
            f"{source} decodes to {len(key)} bytes; at least {MIN_KEY_BYTES} "
            f"({MIN_KEY_BYTES * 8} bits) are required"
        )
    return key


def _key_id(key: bytes) -> str:
    """Derive a key id from the key material itself.

    A hash-derived id cannot lie the way a hand-assigned one can: two
    deployments holding the same key agree on the id, and two different
    keys cannot share one without a SHA-256 collision. Sixteen hex chars
    (64 bits) are enough to name keys unambiguously.
    """
    return "hmac-sha256:" + hashlib.sha256(key).hexdigest()[:16]


def _validated_key_bytes(key: Any, what: str) -> bytes:
    """Validate one piece of key material: bytes, and at least 256 bits.

    A string is refused with the passphrase rationale — key material
    pasted as text is forgeable by anyone who guesses the text — and a
    short key is refused because a guessable key signs nothing.
    """
    if isinstance(key, str):
        raise SigningKeyError(
            f"{what} must be bytes — hex-decode the material first "
            "(a passphrase used directly as a key is forgeable by anyone "
            "who guesses the passphrase)"
        )
    if not isinstance(key, (bytes, bytearray)):
        raise SigningKeyError(f"{what} must be bytes, not {type(key).__name__}")
    key = bytes(key)
    if len(key) < MIN_KEY_BYTES:
        raise SigningKeyError(
            f"{what} is {len(key)} bytes; at least {MIN_KEY_BYTES} "
            f"({MIN_KEY_BYTES * 8} bits) are required"
        )
    return key


def _verification_key_map(keys: List[bytes]) -> Dict[str, bytes]:
    """Map key id to key, refusing two different keys under one id.

    Two different keys cannot share a kid without a SHA-256 collision;
    refusing keeps key lookup unambiguous, so an id always names exactly
    the key material that earned it.
    """
    verification: Dict[str, bytes] = {}
    for key in keys:
        kid = _key_id(key)
        existing = verification.get(kid)
        if existing is not None and existing != key:
            raise SigningKeyError(
                f"two different verification keys share key id {kid!r} "
                "— key ids must be unique"
            )
        verification[kid] = key
    return verification


def _canonical_json(value: Any) -> str:
    """Canonical JSON encoding used for every signature in this module.

    Same rules as ``VerificationReceipt.get_signature``: sorted keys, tight
    separators, and ``allow_nan=False`` so a payload that cannot be
    reproduced by a standard-JSON verifier can never be signed — or
    re-verified.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _receipt_content_fields() -> frozenset:
    """The signed content fields of a receipt, from the receipt model.

    Imported lazily: receipt.py imports this module at load time, so a
    module-level import back would be circular. At call time both modules
    are fully initialised.
    """
    from .receipt import RECEIPT_CONTENT_FIELDS

    return RECEIPT_CONTENT_FIELDS


class ReceiptSigner:
    """Holds receipt signing keys; signs receipts and export envelopes.

    One key is active for signing (``signing_key``); a set of keys is
    accepted for verification (``signing_key`` plus anything in
    ``verification_keys``), which is the rotation window: retire a key by
    removing it from the environment once no live evidence still names it.

    The signer never logs or exposes key material — ``repr`` shows only
    the active key id and the size of the verification set.
    """

    def __init__(
        self,
        signing_key: bytes,
        verification_keys: Optional[Iterable[bytes]] = None,
    ) -> None:
        signing_key = _validated_key_bytes(signing_key, "signing_key")

        extra: List[bytes] = []
        if verification_keys is not None:
            extra = [
                _validated_key_bytes(key, f"verification_keys[{index - 1}]")
                for index, key in enumerate(verification_keys, start=1)
            ]

        self._signing_key = signing_key
        self.signing_kid = _key_id(signing_key)
        self._verification_keys = _verification_key_map([signing_key, *extra])

    @classmethod
    def from_env(cls) -> Optional["ReceiptSigner"]:
        """Build a signer from the environment, or None when unconfigured.

        ``QWED_RECEIPT_SIGNING_KEY`` — hex-encoded active signing key, at
        least 32 bytes decoded. Unset disables signing (exports are then
        explicitly unsigned); set-but-malformed raises, because a
        deployment that believes it is signing must not discover at audit
        time that it was not.

        ``QWED_RECEIPT_VERIFICATION_KEYS`` — optional comma-separated hex
        keys additionally accepted for verification, for rotation: keep the
        retired key here while evidence signed under it must still verify.
        Empty entries (a stray or trailing comma) raise rather than being
        skipped: an ambiguous key list must not decide silently which
        evidence verifies.

        Setting verification keys without a signing key raises: an HMAC
        verifier can always mint signatures, so there is no verify-only
        deployment to configure here.
        """
        signing_raw = os.environ.get(_SIGNING_KEY_ENV)
        verification_raw = os.environ.get(_VERIFICATION_KEYS_ENV)

        if signing_raw is None:
            if verification_raw is not None:
                raise SigningKeyError(
                    f"{_VERIFICATION_KEYS_ENV} is set without "
                    f"{_SIGNING_KEY_ENV}; set the signing key too — an HMAC "
                    "verifier is also a signer"
                )
            return None

        signing_key = parse_key_material(signing_raw, source=_SIGNING_KEY_ENV)

        verification_keys: Optional[List[bytes]] = None
        if verification_raw is not None:
            entries = verification_raw.split(",")
            if not any(entry.strip() for entry in entries):
                raise SigningKeyError(
                    f"{_VERIFICATION_KEYS_ENV} contains no keys — unset it "
                    "or list at least one hex key"
                )
            verification_keys = [
                parse_key_material(
                    entry, source=f"{_VERIFICATION_KEYS_ENV} entry {index}"
                )
                for index, entry in enumerate(entries, start=1)
            ]

        return cls(signing_key, verification_keys)

    def __repr__(self) -> str:
        return (
            f"ReceiptSigner(signing_kid={self.signing_kid!r}, "
            f"verification_keys={len(self._verification_keys)})"
        )

    # -- signing ---------------------------------------------------------

    def sign_receipt(self, receipt: Any) -> None:
        """Sign a receipt in place, using the active key.

        Computes ``get_signature`` over the receipt's canonical content —
        the same #44 primitive, no second scheme — and records the
        signature and its key id on the receipt. Unserializable or
        non-finite metadata raises, so a receipt that cannot produce a
        canonical artifact never enters the audit trail looking signed.
        """
        signature = receipt.get_signature(self._signing_key)
        receipt.signature = signature
        receipt.signature_key_id = self.signing_kid

    def sign_export_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Sign an export envelope in place, over everything but the signature.

        The message is the domain tag ``qwed-finance/audit-log/v1`` followed
        by the canonical JSON of the document minus its ``signature``
        field, so the signature covers the schema, algorithm, key id and
        every receipt — including each receipt's own signature — and a
        signature minted for any other purpose can never be replayed here.
        """
        content = {k: v for k, v in document.items() if k != "signature"}
        document["signature"] = self._export_mac(content)
        return document

    # -- verification ----------------------------------------------------

    def _lookup_key(self, kid: Any, *, what: str) -> bytes:
        """Resolve a key id to its key material, refusing anything else.

        A non-string key id (a list or object from parsed JSON) must not
        crash the dict lookup with a TypeError — it is a malformed
        artifact and refuses like every other one. An unlisted string key
        id is a rotation window that has closed, or a foreign issuer.
        """
        if not isinstance(kid, str):
            raise ReceiptSignatureError(
                f"{what} names a key id that is not a string "
                f"({type(kid).__name__}) — it cannot be verified"
            )
        key = self._verification_keys.get(kid)
        if key is None:
            raise ReceiptSignatureError(
                f"{what} names key id {kid!r}, which is not in the "
                "verification set — the rotation window may have closed"
            )
        return key

    def verify_receipt(self, receipt: Any) -> None:
        """Verify a signed receipt in memory; raise ``ReceiptSignatureError`` otherwise.

        Fail-closed: unsigned, tampered, or signed under an unknown key id
        (a rotation window that has closed) all refuse. A receipt whose
        content cannot even be canonically encoded (colliding metadata
        keys, unserializable values) also refuses — a verification error,
        never a raw TypeError from the normalisation step.
        """
        receipt_id = getattr(receipt, "receipt_id", "<unknown>")
        signature = getattr(receipt, "signature", None)
        kid = getattr(receipt, "signature_key_id", None)
        if signature is None or kid is None:
            raise ReceiptSignatureError(
                f"receipt {receipt_id} is unsigned — only signed receipts "
                "may be treated as audit evidence"
            )
        key = self._lookup_key(kid, what=f"receipt {receipt_id}")
        try:
            content = receipt.to_dict()
        except (TypeError, ValueError) as error:
            raise ReceiptSignatureError(
                f"receipt {receipt_id} cannot be canonically encoded for "
                f"verification: {error}"
            ) from error
        self._verify_mac(
            key,
            content,
            signature,
            what=f"receipt {receipt_id}",
        )

    def verify_export_document(self, document: Any) -> None:
        """Verify a parsed export envelope; raise ``ReceiptSignatureError`` otherwise.

        Checks, in order: the document is an object with the expected
        schema and algorithm; it is signed and its key id is known; the
        envelope signature covers the document minus that signature; and
        every receipt inside is itself present, well-formed and signed with
        a verifiable signature. Any failure raises — there is no mode in
        which a tampered export verifies.
        """
        if not isinstance(document, dict):
            raise ReceiptSignatureError(
                f"export must be a JSON object, not {type(document).__name__}"
            )
        schema = document.get("schema")
        if schema != EXPORT_SCHEMA:
            raise ReceiptSignatureError(
                f"export schema {schema!r} is not {EXPORT_SCHEMA!r}"
            )
        alg = document.get("alg")
        if alg != EXPORT_ALG:
            if alg is None and document.get("signature") is None:
                raise ReceiptSignatureError(
                    "export is unsigned — it carries no signature to verify"
                )
            raise ReceiptSignatureError(
                f"export algorithm {alg!r} is not {EXPORT_ALG!r}"
            )

        signature = document.get("signature")
        kid = document.get("signature_key_id")
        if signature is None:
            raise ReceiptSignatureError(
                "export is unsigned — it carries no signature to verify"
            )
        if kid is None:
            raise ReceiptSignatureError(
                "export signature names no key id — it cannot be verified"
            )
        if not isinstance(signature, str):
            raise ReceiptSignatureError(
                f"export signature must be a hex string, not "
                f"{type(signature).__name__}"
            )
        key = self._lookup_key(kid, what="export")

        content = {k: v for k, v in document.items() if k != "signature"}
        self._verify_mac(key, content, signature, what="export", domain=EXPORT_SCHEMA)

        receipts = document.get("receipts")
        if not isinstance(receipts, list):
            raise ReceiptSignatureError(
                f"export receipts must be a list, not {type(receipts).__name__}"
            )
        for index, payload in enumerate(receipts):
            self.verify_receipt_payload(payload, index=index)

    def verify_receipt_payload(self, payload: Any, index: int = 0) -> None:
        """Verify one receipt as parsed from an export; raise on any deviation.

        The receipt must carry exactly the signed content fields plus the
        two signature fields — no more (an injected field would change what
        was signed), no fewer (a removed field would hide evidence) — and
        its signature must verify under the key its key id names.
        """
        where = f"receipts[{index}]"
        if not isinstance(payload, dict):
            raise ReceiptSignatureError(
                f"{where} must be a JSON object, not {type(payload).__name__}"
            )

        content_fields = _receipt_content_fields()
        expected_keys = set(content_fields) | set(_RECEIPT_SIGNATURE_FIELDS)
        actual_keys = set(payload)
        if actual_keys != expected_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            details = []
            if missing:
                details.append(f"missing {missing}")
            if extra:
                details.append(f"unexpected {extra}")
            raise ReceiptSignatureError(
                f"{where} fields do not match a receipt ({'; '.join(details)})"
            )

        signature = payload["signature"]
        kid = payload["signature_key_id"]
        if signature is None:
            raise ReceiptSignatureError(
                f"{where} is unsigned — only signed receipts may appear in "
                "a signed export"
            )
        if kid is None:
            raise ReceiptSignatureError(
                f"{where} signature names no key id — it cannot be verified"
            )
        if not isinstance(signature, str):
            raise ReceiptSignatureError(
                f"{where} signature must be a hex string, not "
                f"{type(signature).__name__}"
            )
        key = self._lookup_key(kid, what=where)

        content = {
            k: v for k, v in payload.items() if k not in _RECEIPT_SIGNATURE_FIELDS
        }
        receipt_id = payload.get("receipt_id", "<unknown>")
        self._verify_mac(key, content, signature, what=f"receipt {receipt_id}")

    # -- primitives --------------------------------------------------------

    def _export_mac(self, content: Dict[str, Any]) -> str:
        """HMAC-SHA256 over the domain tag plus canonical export content."""
        message = (EXPORT_SCHEMA + "\n" + _canonical_json(content)).encode("utf-8")
        return hmac.new(self._signing_key, message, hashlib.sha256).hexdigest()

    def _verify_mac(
        self,
        key: bytes,
        content: Any,
        signature: str,
        *,
        what: str,
        domain: Optional[str] = None,
    ) -> None:
        """Recompute a MAC over content and compare in constant time.

        ``domain`` prefixes the message exactly as the signing side did
        (the export envelope signs its schema tag before the content), so
        a MAC minted for one purpose can never verify as the other.

        ``json.dumps`` failures (unserializable values, NaN/Infinity with
        ``allow_nan=False``) become verification failures: an artifact
        whose canonical form cannot be reproduced cannot be verified, and
        must not pass because it failed to recompute.
        """
        try:
            canonical = _canonical_json(content)
        except (TypeError, ValueError) as error:
            raise ReceiptSignatureError(
                f"{what} cannot be canonically encoded for verification: {error}"
            ) from error
        if domain is not None:
            canonical = domain + "\n" + canonical
        expected = hmac.new(
            key,
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        try:
            matches = hmac.compare_digest(expected, signature)
        except TypeError:
            # compare_digest only accepts ASCII strings; anything else is
            # not a hex signature and must refuse, not crash the caller.
            raise ReceiptSignatureError(
                f"{what} signature is not a hex string"
            ) from None
        if not matches:
            raise ReceiptSignatureError(
                f"signature mismatch on {what} — the artifact was tampered "
                "with or was signed under different key material"
            )
