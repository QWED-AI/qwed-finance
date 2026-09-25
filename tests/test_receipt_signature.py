"""Tamper-evident receipt signatures — HMAC over the full receipt (#44)."""

import hashlib
import json

import pytest

from qwed_finance.models.receipt import (
    VerificationEngine,
    VerificationReceipt,
    VerificationStatus,
)

VERIFIER_KEY = b"verifier-secret-key"
OTHER_KEY = b"different-key"

FIELD_MUTATIONS = {
    "receipt_id": "22222222-2222-2222-2222-222222222222",
    "timestamp": "2026-09-25T00:00:01+00:00",
    "input_hash": "b" * 64,
    "input_preview": "tampered preview",
    "guard_name": "OtherGuard.method",
    "engine_used": VerificationEngine.Z3,
    "status": VerificationStatus.REJECTED,
    "verified": False,
    "computed_value": "1.00",
    "llm_value": "1.00",
    "difference": "99.00",
    "proof_steps": ["forged-step"],
    "formula_used": "b=c",
    "violations": ["forged-violation"],
    "metadata": {"rule": "forged"},
}


def make_receipt() -> VerificationReceipt:
    return VerificationReceipt(
        receipt_id="11111111-1111-1111-1111-111111111111",
        timestamp="2026-09-25T00:00:00+00:00",
        input_hash="a" * 64,
        input_preview="legit preview",
        guard_name="ComplianceGuard.verify_aml_flag",
        engine_used=VerificationEngine.DECIMAL,
        status=VerificationStatus.VERIFIED,
        verified=True,
        computed_value="100.00",
        llm_value="100.00",
        difference="0.00",
        proof_steps=["step-1"],
        formula_used="a=b",
        violations=["none"],
        metadata={"rule": "r-1"},
    )


def test_mutations_cover_every_receipt_field():
    assert set(FIELD_MUTATIONS) == set(make_receipt().to_dict())


def test_every_field_mutation_changes_signature():
    for field_name, forged_value in FIELD_MUTATIONS.items():
        receipt = make_receipt()
        baseline = receipt.get_signature(VERIFIER_KEY)
        setattr(receipt, field_name, forged_value)
        assert receipt.get_signature(VERIFIER_KEY) != baseline, field_name


def test_issue_44_repro_in_place_tampering_undetected_before():
    """The exact #44 sequence: mutations used to leave the hash identical."""
    receipt = make_receipt()
    before = receipt.get_signature(VERIFIER_KEY)

    receipt.computed_value = "1.00"
    receipt.violations.append("fake")
    receipt.proof_steps.append("fake")
    receipt.status = VerificationStatus.REJECTED

    assert receipt.get_signature(VERIFIER_KEY) != before


def test_signature_is_keyed():
    receipt = make_receipt()
    assert receipt.get_signature(VERIFIER_KEY) != receipt.get_signature(OTHER_KEY)


def test_signature_deterministic_for_identical_receipts():
    assert make_receipt().get_signature(VERIFIER_KEY) == make_receipt().get_signature(
        VERIFIER_KEY
    )


def test_unkeyed_subset_hash_no_longer_matches():
    receipt = make_receipt()
    legacy_content = json.dumps(
        {
            "receipt_id": receipt.receipt_id,
            "timestamp": receipt.timestamp,
            "input_hash": receipt.input_hash,
            "verified": receipt.verified,
            "engine_used": receipt.engine_used.value,
        },
        sort_keys=True,
    )
    legacy = hashlib.sha256(legacy_content.encode()).hexdigest()
    assert receipt.get_signature(VERIFIER_KEY) != legacy


def test_surrogate_bearing_metadata_signs_without_raising():
    receipt = make_receipt()
    receipt.metadata = {"preview": "bad\ud800byte"}
    receipt.get_signature(VERIFIER_KEY)


def test_unserializable_metadata_raises_like_to_json():
    receipt = make_receipt()
    receipt.metadata = {"obj": object()}
    with pytest.raises(TypeError):
        receipt.to_json()
    with pytest.raises(TypeError):
        receipt.get_signature(VERIFIER_KEY)


def test_requires_key():
    receipt = make_receipt()
    with pytest.raises(TypeError):
        receipt.get_signature()
