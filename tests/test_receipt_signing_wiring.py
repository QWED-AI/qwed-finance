"""Receipt signing wired into the audit trail (#90).

The #44 primitive (get_signature) existed; nothing called it. These tests
pin the wiring: keys resolve from the environment and fail closed when
malformed, receipts are signed at retention, exports carry the signatures
plus an envelope signature over the whole document, and every tampered
variant of a signed export — mutated field, removed field, injected field,
truncated, reordered, spliced, cross-protocol signature — refuses to
verify.

Key ids support rotation: retired keys stay in the verification window
while evidence signed under them must still verify, and close afterwards.
"""

import hashlib
import json
import sys

import pytest

from qwed_finance import (
    AuditLog,
    ReceiptGenerator,
    ReceiptSignatureError,
    ReceiptSigner,
    SigningKeyError,
    VerificationEngine,
    parse_key_material,
)
from qwed_finance.models.receipt import RECEIPT_CONTENT_FIELDS

KEY_A = bytes(range(32))
KEY_B = bytes(range(32, 64))
KEY_A_HEX = KEY_A.hex()
KEY_B_HEX = KEY_B.hex()

SIGNING_ENV = "QWED_RECEIPT_SIGNING_KEY"
VERIFICATION_ENV = "QWED_RECEIPT_VERIFICATION_KEYS"


def make_signer(key: bytes = KEY_A, verification_keys=None) -> ReceiptSigner:
    return ReceiptSigner(key, verification_keys)


def make_log(signer=None, count: int = 2) -> AuditLog:
    log = AuditLog(signer=signer)
    for index in range(count):
        log.log(
            ReceiptGenerator.create_receipt(
                guard_name=f"TestGuard.verify_{index}",
                engine=VerificationEngine.DECIMAL,
                llm_output=f"100.0{index}",
                verified=index % 2 == 0,
                computed_value=f"100.0{index}",
                violations=[] if index % 2 == 0 else ["mismatch"],
                metadata={"rule": f"r-{index}", "index": index},
            )
        )
    return log


def signed_export(key: bytes = KEY_A, count: int = 2) -> str:
    return make_log(make_signer(key), count).export_json()


@pytest.fixture(autouse=True)
def clean_signing_env(monkeypatch):
    """No ambient signing configuration leaks into any test."""
    monkeypatch.delenv(SIGNING_ENV, raising=False)
    monkeypatch.delenv(VERIFICATION_ENV, raising=False)


# -- key material ---------------------------------------------------------


def test_parse_key_material_accepts_32_byte_hex():
    assert parse_key_material(KEY_A_HEX, source="test") == KEY_A


def test_parse_key_material_strips_surrounding_whitespace():
    assert parse_key_material(f"  {KEY_A_HEX}\n", source="test") == KEY_A


@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_parse_key_material_rejects_empty(bad):
    with pytest.raises(SigningKeyError):
        parse_key_material(bad, source="test")


def test_parse_key_material_rejects_non_hex():
    with pytest.raises(SigningKeyError):
        parse_key_material("not hex at all!", source="test")


def test_parse_key_material_rejects_odd_length_hex():
    with pytest.raises(SigningKeyError):
        parse_key_material(KEY_A_HEX + "a", source="test")


def test_parse_key_material_rejects_short_key():
    """Valid hex that decodes to 31 bytes: the length rule, not the type rule."""
    with pytest.raises(SigningKeyError):
        parse_key_material("61" * 31, source="test")


def test_parse_key_material_rejects_non_string():
    with pytest.raises(SigningKeyError):
        parse_key_material(KEY_A, source="test")  # raw bytes, not hex text


def test_signer_rejects_passphrase_string_as_key():
    """A passphrase pasted where key bytes belong must not become a key."""
    with pytest.raises(SigningKeyError):
        ReceiptSigner("correct-horse-battery-staple")


def test_signer_rejects_non_bytes_key():
    with pytest.raises(SigningKeyError):
        ReceiptSigner(42)
    with pytest.raises(SigningKeyError):
        ReceiptSigner(KEY_A, verification_keys=[42])


def test_two_keys_sharing_a_key_id_refuse(monkeypatch):
    """Key lookup stays unambiguous: two keys under one id cannot load."""
    from qwed_finance.models import signing

    monkeypatch.setattr(signing, "_key_id", lambda key: "hmac-sha256:fixed")
    with pytest.raises(SigningKeyError):
        signing.ReceiptSigner(KEY_A, verification_keys=[KEY_B])


def test_signer_rejects_short_key_bytes():
    with pytest.raises(SigningKeyError):
        ReceiptSigner(b"x" * 31)


def test_signer_rejects_string_verification_key():
    hex_text = KEY_B.hex()
    with pytest.raises(SigningKeyError):
        ReceiptSigner(KEY_A, verification_keys=[hex_text])


def test_signer_rejects_short_verification_key():
    with pytest.raises(SigningKeyError):
        ReceiptSigner(KEY_A, verification_keys=[b"x" * 31])


def test_signer_dedupes_repeated_verification_keys():
    signer = ReceiptSigner(KEY_A, verification_keys=[KEY_B, KEY_B])
    assert len(signer._verification_keys) == 2


def test_key_ids_are_derived_and_distinct():
    expected_a = "hmac-sha256:" + hashlib.sha256(KEY_A).hexdigest()[:16]
    assert make_signer(KEY_A).signing_kid == expected_a
    assert make_signer(KEY_A).signing_kid != make_signer(KEY_B).signing_kid


def test_repr_does_not_leak_key_material():
    representation = repr(make_signer())
    assert KEY_A_HEX not in representation
    assert str(KEY_A) not in representation
    assert "signing_kid" in representation


# -- environment ----------------------------------------------------------


def test_from_env_none_when_unset():
    assert ReceiptSigner.from_env() is None


def test_from_env_reads_signing_key(monkeypatch):
    monkeypatch.setenv(SIGNING_ENV, KEY_A_HEX)
    signer = ReceiptSigner.from_env()
    assert signer is not None
    assert signer.signing_kid == make_signer(KEY_A).signing_kid


def test_from_env_strips_whitespace(monkeypatch):
    monkeypatch.setenv(SIGNING_ENV, f"  {KEY_A_HEX} \n")
    assert ReceiptSigner.from_env().signing_kid == make_signer(KEY_A).signing_kid


def test_from_env_rejects_malformed_key(monkeypatch):
    """A deployment that believes it is signing must fail loudly, not sign nothing."""
    monkeypatch.setenv(SIGNING_ENV, "zzz")
    with pytest.raises(SigningKeyError):
        ReceiptSigner.from_env()


def test_from_env_rejects_empty_value(monkeypatch):
    monkeypatch.setenv(SIGNING_ENV, "")
    with pytest.raises(SigningKeyError):
        ReceiptSigner.from_env()


def test_from_env_rejects_short_value(monkeypatch):
    monkeypatch.setenv(SIGNING_ENV, "61" * 31)
    with pytest.raises(SigningKeyError):
        ReceiptSigner.from_env()


def test_from_env_rejects_verification_keys_without_signing_key(monkeypatch):
    monkeypatch.setenv(VERIFICATION_ENV, KEY_A_HEX)
    with pytest.raises(SigningKeyError):
        ReceiptSigner.from_env()


@pytest.mark.parametrize(
    "value", [",", f"{KEY_A_HEX},", f"{KEY_A_HEX},,{KEY_B_HEX}", f"  ,{KEY_A_HEX}"]
)
def test_from_env_rejects_empty_verification_entries(monkeypatch, value):
    monkeypatch.setenv(SIGNING_ENV, KEY_B_HEX)
    monkeypatch.setenv(VERIFICATION_ENV, value)
    with pytest.raises(SigningKeyError):
        ReceiptSigner.from_env()


def test_from_env_accepts_rotation_window(monkeypatch):
    monkeypatch.setenv(SIGNING_ENV, KEY_B_HEX)
    monkeypatch.setenv(VERIFICATION_ENV, f"{KEY_A_HEX},{KEY_B_HEX}")
    signer = ReceiptSigner.from_env()
    old_export = json.loads(signed_export(KEY_A))
    signer.verify_export_document(old_export)
    fresh = ReceiptSigner(KEY_B)
    with pytest.raises(ReceiptSignatureError):
        fresh.verify_export_document(old_export)


def test_audit_log_resolves_signer_from_env(monkeypatch):
    monkeypatch.setenv(SIGNING_ENV, KEY_A_HEX)
    log = AuditLog()
    log.log(
        ReceiptGenerator.create_receipt(
            "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
        )
    )
    assert log.receipts[0].signature is not None


def test_audit_log_env_is_read_at_construction_not_cached(monkeypatch):
    first = AuditLog()
    assert first.signer is None
    monkeypatch.setenv(SIGNING_ENV, KEY_A_HEX)
    second = AuditLog()
    assert second.signer is not None


def test_bad_env_breaks_audit_log_construction_loudly(monkeypatch):
    monkeypatch.setenv(SIGNING_ENV, "not-hex")
    with pytest.raises(SigningKeyError):
        AuditLog()


# -- signing at retention ----------------------------------------------------


def test_log_signs_receipt_with_active_key():
    log = make_log(make_signer())
    for receipt in log.receipts:
        assert receipt.signature is not None
        assert receipt.signature_key_id == log.signer.signing_kid


def test_log_uses_the_issue_44_primitive():
    signer = make_signer()
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    AuditLog(signer=signer).log(receipt)
    assert receipt.signature == receipt.get_signature(KEY_A)


def test_log_without_signer_leaves_receipt_unsigned():
    log = make_log()
    for receipt in log.receipts:
        assert receipt.signature is None
        assert receipt.signature_key_id is None


def test_log_fails_closed_on_unserializable_metadata():
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = {"obj": object()}
    with pytest.raises(TypeError):
        log.log(receipt)
    assert log.receipts == []


def test_log_fails_closed_on_nan_metadata():
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = {"score": float("nan")}
    with pytest.raises(ValueError):
        log.log(receipt)
    assert log.receipts == []


def test_to_dict_excludes_signature_fields():
    """The signed payload is exactly the content — a signature cannot sign itself."""
    log = make_log(make_signer(), count=1)
    exported = log.receipts[0].to_dict()
    assert "signature" not in exported
    assert "signature_key_id" not in exported
    assert set(RECEIPT_CONTENT_FIELDS) == set(exported)


def test_to_export_dict_includes_signature_fields():
    log = make_log(make_signer(), count=1)
    exported = log.receipts[0].to_export_dict()
    assert exported["signature"] == log.receipts[0].signature
    assert exported["signature_key_id"] == log.receipts[0].signature_key_id


# -- export envelope ---------------------------------------------------------


def test_signed_export_shape():
    signer = make_signer()
    document = json.loads(make_log(signer).export_json())
    assert document["schema"] == "qwed-finance/audit-log/v1"
    assert document["alg"] == "HMAC-SHA256"
    assert document["signature_key_id"] == signer.signing_kid
    assert isinstance(document["signature"], str)
    for receipt in document["receipts"]:
        assert receipt["signature"] is not None
        assert receipt["signature_key_id"] == signer.signing_kid


def test_signed_export_round_trip_verifies():
    export = signed_export()
    AuditLog(signer=make_signer()).verify_export_json(export)


def test_export_is_an_object_not_a_bare_list():
    """The export is an envelope — a bare list could not carry a signature."""
    assert isinstance(json.loads(signed_export()), dict)


def test_empty_log_signed_export_verifies():
    log = AuditLog(signer=make_signer())
    log.verify_export_json(log.export_json())


def test_unsigned_export_is_explicit():
    document = json.loads(make_log().export_json())
    assert document["schema"] == "qwed-finance/audit-log/v1"
    assert document["alg"] is None
    assert document["signature"] is None
    assert document["signature_key_id"] is None
    for receipt in document["receipts"]:
        assert receipt["signature"] is None
        assert receipt["signature_key_id"] is None


def test_verify_export_requires_signer():
    log = AuditLog()
    export = signed_export()
    with pytest.raises(ReceiptSignatureError):
        log.verify_export_json(export)


def test_verify_export_rejects_unsigned_export():
    log = AuditLog(signer=make_signer())
    export = make_log().export_json()
    with pytest.raises(ReceiptSignatureError, match="unsigned"):
        log.verify_export_json(export)


def test_export_fails_closed_on_in_place_tampering_after_log():
    log = make_log(make_signer())
    log.receipts[0].computed_value = "1.00"
    with pytest.raises(ReceiptSignatureError):
        log.export_json()


def test_export_fails_closed_on_unsigned_appended_receipt():
    log = make_log(make_signer(), count=1)
    log.receipts.append(
        ReceiptGenerator.create_receipt(
            "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
        )
    )
    with pytest.raises(ReceiptSignatureError):
        log.export_json()


def test_export_fails_closed_on_foreign_signed_receipt():
    log = make_log(make_signer(KEY_A), count=1)
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    make_signer(KEY_B).sign_receipt(receipt)
    log.receipts[0] = receipt
    with pytest.raises(ReceiptSignatureError):
        log.export_json()


# -- tampering: envelope fields ----------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        lambda doc: doc.update(schema="qwed-finance/audit-log/v2"),
        lambda doc: doc.update(schema="QWED-FINANCE/AUDIT-LOG/V1"),
        # Cyrillic look-alike for the "o" in "log".
        lambda doc: doc.update(schema="qwed-finance/audit-lоg/v1"),
        lambda doc: doc.pop("schema"),
        lambda doc: doc.update(alg="hmac-sha256"),
        lambda doc: doc.update(alg="HS256"),
        lambda doc: doc.pop("alg"),
        lambda doc: doc.update(signature_key_id="hmac-sha256:deadbeefdeadbeef"),
        lambda doc: doc.update(signature_key_id=doc["signature_key_id"].upper()),
        lambda doc: doc.pop("signature_key_id"),
        lambda doc: doc.update(signature=None),
        lambda doc: doc.pop("signature"),
        lambda doc: doc.update(signature="0" * 64),
        lambda doc: doc.update(signature=doc["signature"][:-1]),
        lambda doc: doc.update(signature=doc["signature"] + "0"),
        lambda doc: doc.update(signature=" " + doc["signature"]),
        lambda doc: doc.update(signature=12345),
        lambda doc: doc.update(extra="injected"),
        lambda doc: doc.pop("receipts"),
        lambda doc: doc.update(receipts={"not": "a list"}),
        lambda doc: doc.update(receipts="not-a-list"),
    ],
    ids=[
        "schema-bumped",
        "schema-case",
        "schema-unicode-lookalike",
        "schema-missing",
        "alg-case",
        "alg-swapped",
        "alg-missing",
        "kid-unknown",
        "kid-case",
        "kid-missing",
        "signature-null",
        "signature-missing",
        "signature-zeroed",
        "signature-truncated",
        "signature-extended",
        "signature-leading-space",
        "signature-not-a-string",
        "extra-field-injected",
        "receipts-missing",
        "receipts-dict",
        "receipts-string",
    ],
)
def test_tampered_envelope_field_refuses_to_verify(mutation):
    signer = make_signer()
    document = json.loads(signed_export())
    mutation(document)
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


# -- tampering: receipt content ----------------------------------------------


CONTENT_MUTATIONS = {
    "receipt_id": lambda r: r.update(receipt_id="22222222-2222-2222-2222-222222222222"),
    "timestamp": lambda r: r.update(timestamp="2026-11-20T00:00:01+00:00"),
    "input_hash": lambda r: r.update(input_hash="b" * 64),
    "input_preview": lambda r: r.update(input_preview="forged preview"),
    "guard_name": lambda r: r.update(guard_name="OtherGuard.method"),
    "engine_used": lambda r: r.update(engine_used="Z3"),
    "status": lambda r: r.update(status="rejected"),
    "verified": lambda r: r.update(verified=not r["verified"]),
    "computed_value": lambda r: r.update(computed_value="1.00"),
    "llm_value": lambda r: r.update(llm_value="1.00"),
    "difference": lambda r: r.update(difference="99.00"),
    "proof_steps": lambda r: r.update(proof_steps=["forged-step"]),
    "formula_used": lambda r: r.update(formula_used="b=c"),
    "violations": lambda r: r.update(violations=["forged-violation"]),
    "metadata": lambda r: r.update(metadata={"rule": "forged"}),
}


def test_content_mutations_cover_every_receipt_field():
    assert set(CONTENT_MUTATIONS) == set(RECEIPT_CONTENT_FIELDS)


@pytest.mark.parametrize("field", sorted(CONTENT_MUTATIONS))
def test_tampered_receipt_content_refuses_to_verify(field):
    signer = make_signer()
    document = json.loads(signed_export())
    CONTENT_MUTATIONS[field](document["receipts"][0])
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(signature="ВАЛИДНЫЙ"),
        lambda r: r.update(signature="\ud800" + r["signature"]),
        lambda r: r.pop("computed_value"),
        lambda r: r.pop("signature"),
        lambda r: r.pop("signature_key_id"),
        lambda r: r.update(signature=None),
        lambda r: r.update(signature_key_id=None),
        lambda r: r.update(signature=12345),
        lambda r: r.update(extra="injected"),
        lambda r: r.update(receipt_id=None),
    ],
    ids=[
        "signature-non-ascii",
        "signature-lone-surrogate",
        "field-removed",
        "signature-removed",
        "kid-removed",
        "signature-null",
        "kid-null",
        "signature-not-string",
        "field-injected",
        "receipt-id-null",
    ],
)
def test_malformed_receipt_shape_refuses_to_verify(mutation):
    signer = make_signer()
    document = json.loads(signed_export())
    mutation(document["receipts"][0])
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_receipt_not_a_dict_refuses_to_verify():
    document = json.loads(signed_export())
    document["receipts"][0] = ["not", "a", "dict"]
    signer = make_signer()
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_swapped_receipt_signatures_refuse_to_verify():
    """Two genuine signatures, exchanged between receipts, must not verify."""
    signer = make_signer()
    document = json.loads(signed_export(count=2))
    first, second = document["receipts"]
    first["signature"], second["signature"] = second["signature"], first["signature"]
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_export_document_not_a_dict_refuses():
    signer = make_signer()
    for hostile in ([], "string", 42, None, True):
        with pytest.raises(ReceiptSignatureError):
            signer.verify_export_document(hostile)


def test_nan_injected_into_parsed_export_refuses_to_verify():
    """json.loads accepts the NaN token; verification must not."""
    signer = make_signer()
    document = json.loads(signed_export())
    document["receipts"][0]["metadata"] = {"score": float("nan")}
    text = json.dumps(document, indent=2)  # allow_nan default emits the NaN token
    parsed = json.loads(text)
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(parsed)


def test_verify_export_rejects_invalid_json():
    """Malformed text is a verification failure, not a JSONDecodeError."""
    log = AuditLog(signer=make_signer())
    with pytest.raises(ReceiptSignatureError, match="not valid JSON"):
        log.verify_export_json("{not json at all")


@pytest.mark.parametrize(
    "inject",
    [
        # A repeated envelope member: json.loads would keep the last one.
        lambda text: text.replace('"receipts":', '"receipts": [], "receipts":', 1),
        # A repeated member inside one receipt.
        lambda text: text.replace(
            '"computed_value":', '"computed_value": "9.99", "computed_value":', 1
        ),
        # A repeated member inside receipt metadata.
        lambda text: text.replace('"index":', '"index": 99, "index":', 1),
    ],
    ids=["envelope-level", "receipt-level", "metadata-level"],
)
def test_verify_export_rejects_duplicate_member_names(inject):
    """Ambiguous evidence does not verify, whichever parser reads it."""
    log = AuditLog(signer=make_signer())
    hostile = inject(signed_export())
    with pytest.raises(ReceiptSignatureError, match="duplicate JSON member"):
        log.verify_export_json(hostile)


def test_non_string_key_id_refuses_to_verify():
    """A list or object key id must refuse, not crash the dict lookup."""
    signer = make_signer()

    envelope_hostile = json.loads(signed_export())
    envelope_hostile["signature_key_id"] = ["not", "a", "kid"]
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(envelope_hostile)

    receipt_hostile = json.loads(signed_export())
    receipt_hostile["receipts"][0]["signature_key_id"] = {"k": "id"}
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(receipt_hostile)


def test_colliding_metadata_keys_fail_closed_at_export():
    """A retained receipt mutated to unencodable metadata refuses as a
    verification error, not a raw TypeError from normalisation."""
    log = AuditLog(signer=make_signer())
    log.log(
        ReceiptGenerator.create_receipt(
            "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
        )
    )
    log.receipts[0].metadata = {1: "a", "1": "b"}
    with pytest.raises(ReceiptSignatureError):
        log.export_json()


def test_tampered_receipt_fails_even_with_fresh_envelope_signature():
    """The receipt-level check binds: a fresh envelope signature over a
    receipt whose own signature no longer matches must still refuse."""
    signer = make_signer()
    document = json.loads(signed_export())
    document["receipts"][0]["timestamp"] = "2026-11-20T00:00:01+00:00"
    signer.sign_export_document(document)
    with pytest.raises(ReceiptSignatureError, match="receipt"):
        signer.verify_export_document(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(signature=None),
        lambda r: r.update(signature_key_id=None),
        lambda r: r.update(signature=12345),
        lambda r: r.update(signature="ВАЛИДНЫЙ"),
        lambda r: r.update(signature_key_id=["not", "a", "kid"]),
        lambda r: r.update(signature_key_id={"k": "id"}),
        lambda r: r.pop("computed_value"),
        lambda r: r.update(extra="injected"),
    ],
    ids=[
        "signature-null",
        "kid-null",
        "signature-not-string",
        "signature-non-ascii",
        "kid-list",
        "kid-object",
        "field-removed",
        "field-injected",
    ],
)
def test_hostile_receipt_refuses_even_with_fresh_envelope_signature(mutation):
    """A fresh envelope signature lets verification reach the receipt-level
    checks; every hostile receipt shape must still refuse there."""
    signer = make_signer()
    document = json.loads(signed_export())
    mutation(document["receipts"][0])
    signer.sign_export_document(document)
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda doc: doc.update(receipts={"not": "a list"}),
        lambda doc: doc.update(receipts="not-a-list"),
        lambda doc: doc.update(receipts=[["not", "a", "dict"]]),
        lambda doc: doc.update(receipts=[42]),
    ],
    ids=["receipts-dict", "receipts-string", "receipt-list-of-lists", "receipt-int"],
)
def test_hostile_structure_refuses_even_with_fresh_envelope_signature(mutation):
    """A fresh envelope signature lets verification reach the structural
    checks; hostile shapes must refuse there, not at the MAC compare."""
    signer = make_signer()
    document = json.loads(signed_export())
    mutation(document)
    signer.sign_export_document(document)
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


# -- tampering: the export as a whole ----------------------------------------


def test_truncated_export_refuses_to_verify():
    signer = make_signer()
    document = json.loads(signed_export(count=3))
    del document["receipts"][1:]
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_reordered_receipts_refuse_to_verify():
    signer = make_signer()
    document = json.loads(signed_export(count=3))
    document["receipts"].reverse()
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_duplicated_receipt_refuses_to_verify():
    signer = make_signer()
    document = json.loads(signed_export(count=1))
    document["receipts"].append(document["receipts"][0])
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_spliced_genuine_receipt_refuses_to_verify():
    """A genuine, correctly-signed receipt from another export must not splice in.

    Per-receipt verification alone cannot catch this — the receipt really
    was signed by this key. The envelope signature covers the receipts as
    a set, so the splice fails.
    """
    signer = make_signer()
    export_a = json.loads(make_log(signer, count=1).export_json())
    export_b = json.loads(make_log(signer, count=1).export_json())

    spliced = export_b["receipts"][0]
    # It is genuine on its own:
    signer.verify_receipt_payload(spliced)
    # But it does not belong to export A:
    export_a["receipts"].append(spliced)
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(export_a)


def test_cross_protocol_signature_refuses_to_verify():
    """An envelope signature cannot be replayed as a receipt signature."""
    signer = make_signer()
    document = json.loads(signed_export())
    document["receipts"][0]["signature"] = document["signature"]
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_unicode_metadata_round_trips_and_tampers():
    """Look-alike and zero-width characters sign, round-trip and detect edits."""
    signer = make_signer()
    log = AuditLog(signer=signer)
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = {
        "name": "ВАСИЛИЙ",  # Cyrillic look-alikes
        "zwsp": "a\u200bb",  # zero-width space inside a value
        "bank": "🏦",
    }
    log.log(receipt)
    export = log.export_json()
    log.verify_export_json(export)

    document = json.loads(export)
    document["receipts"][0]["metadata"]["zwsp"] = "a b"  # strip the zero-width
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


# -- rotation ------------------------------------------------------------------


def test_old_key_evidence_verifies_during_rotation_window():
    old_export = signed_export(KEY_A)
    rotated = make_signer(KEY_B, verification_keys=[KEY_A])
    rotated.verify_export_document(json.loads(old_export))


def test_old_key_evidence_refuses_after_window_closes():
    signer = make_signer(KEY_B)
    old_export = json.loads(signed_export(KEY_A))
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(old_export)


def test_new_receipts_are_signed_with_the_new_key():
    rotated = make_signer(KEY_B, verification_keys=[KEY_A])
    log = make_log(rotated, count=1)
    assert log.receipts[0].signature_key_id == rotated.signing_kid
    log.verify_export_json(log.export_json())


def test_relogging_resigns_with_the_active_key():
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    old_log = AuditLog(signer=make_signer(KEY_A))
    old_log.log(receipt)
    rotated = make_signer(KEY_B, verification_keys=[KEY_A])
    new_log = AuditLog(signer=rotated)
    new_log.log(receipt)
    assert receipt.signature_key_id == rotated.signing_kid
    new_log.verify_export_json(new_log.export_json())


def test_relogging_a_tampered_receipt_refuses():
    """Re-signing without checking would launder edited content; it refuses."""
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    log.log(receipt)
    receipt.computed_value = "999.00"
    with pytest.raises(ReceiptSignatureError):
        log.log(receipt)
    assert len(log.receipts) == 1


def test_relogging_under_a_foreign_key_refuses():
    """A signer outside the receipt's rotation window cannot re-attest it."""
    log = AuditLog(signer=make_signer(KEY_A))
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    log.log(receipt)
    stranger = AuditLog(signer=make_signer(KEY_B))
    with pytest.raises(ReceiptSignatureError):
        stranger.log(receipt)
    assert len(stranger.receipts) == 0


def test_half_signed_receipt_refuses():
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.signature = "ab" * 32
    with pytest.raises(ReceiptSignatureError, match="half-signed"):
        log.log(receipt)
    receipt.signature = None
    receipt.signature_key_id = "hmac-sha256:0000000000000000"
    with pytest.raises(ReceiptSignatureError, match="half-signed"):
        log.log(receipt)
    assert log.receipts == []


def test_first_log_keeps_its_evidence_after_relogging_elsewhere():
    """Each log retains its own snapshot: re-signing under key B never
    changes what the log that first retained it under key A holds."""
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    first = AuditLog(signer=make_signer(KEY_A))
    first.log(receipt)

    rotated = make_signer(KEY_B, verification_keys=[KEY_A])
    second = AuditLog(signer=rotated)
    second.log(receipt)

    first.verify_export_json(first.export_json())
    second.verify_export_json(second.export_json())
    assert receipt.signature_key_id == rotated.signing_kid


def test_caller_mutation_after_log_does_not_change_retained_evidence():
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify",
        VerificationEngine.DECIMAL,
        "1.00",
        True,
        computed_value="1.00",
    )
    log.log(receipt)
    receipt.computed_value = "999.00"

    export = log.export_json()
    document = json.loads(export)
    assert document["receipts"][0]["computed_value"] == "1.00"
    log.verify_export_json(export)


def test_unsigned_export_strips_receipt_signatures():
    """An unsigned envelope carries no per-receipt signatures either — a
    receipt signed elsewhere must not look like signed evidence inside it."""
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    make_signer(KEY_A).sign_receipt(receipt)
    log = AuditLog()
    log.log(receipt)

    document = json.loads(log.export_json())
    assert document["alg"] is None
    assert document["signature"] is None
    assert document["receipts"][0]["signature"] is None
    assert document["receipts"][0]["signature_key_id"] is None
    # The receipt object itself keeps what it carries; only the unsigned
    # export declines to present it.
    assert receipt.signature is not None


# -- golden values ----------------------------------------------------------------


def test_known_answer_envelope_mac():
    """Pins the envelope MAC: domain tag, canonical JSON, HMAC-SHA256."""
    signer = make_signer()
    receipt = ReceiptGenerator.create_receipt(
        guard_name="GoldenGuard.verify",
        engine=VerificationEngine.DECIMAL,
        llm_output="42.00",
        verified=True,
        computed_value="42.00",
    )
    receipt.receipt_id = "11111111-1111-1111-1111-111111111111"
    receipt.timestamp = "2026-11-20T00:00:00+00:00"
    log = AuditLog(signer=signer)
    log.log(receipt)
    document = json.loads(log.export_json())
    assert (
        document["signature"]
        == "3f6142af825da4190da125cf44762f484642b9300360833e15e29f87508dd5b7"
    )


# -- integrations pick up signing through the environment ------------------------


def test_ucp_integration_signs_receipts_when_env_set(monkeypatch):
    from qwed_finance import UCPIntegration

    monkeypatch.setenv(SIGNING_ENV, KEY_A_HEX)
    integration = UCPIntegration()
    result = integration.verify_payment_token(
        {
            "amount": 100.0,
            "currency": "USD",
            "customer_id": "cust-1",
            "customer_country": "US",
            "kyc_verified": True,
            "payment_method": "card",
        }
    )
    assert integration.audit_log.receipts
    for receipt in integration.audit_log.receipts:
        assert receipt.signature is not None
        assert receipt.signature_key_id == integration.audit_log.signer.signing_kid
    integration.audit_log.verify_export_json(integration.audit_log.export_json())
    assert result is not None


def test_concurrent_mutation_during_log_cannot_reach_retained_evidence(monkeypatch):
    """log() verifies, signs and retains one private snapshot: a change to the
    caller's object between verification and signing is never signed."""
    signer = make_signer()
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify",
        VerificationEngine.DECIMAL,
        "1.00",
        True,
        computed_value="1.00",
    )
    signer.sign_receipt(receipt)
    log = AuditLog(signer=signer)

    real_verify = signer.verify_receipt

    def verify_then_race(target):
        real_verify(target)
        receipt.computed_value = "999.00"  # another thread edits the original

    monkeypatch.setattr(signer, "verify_receipt", verify_then_race)
    log.log(receipt)
    monkeypatch.setattr(signer, "verify_receipt", real_verify)

    export = log.export_json()
    assert json.loads(export)["receipts"][0]["computed_value"] == "1.00"
    log.verify_export_json(export)
    # The caller's edited object no longer matches the signature it was given.
    with pytest.raises(ReceiptSignatureError):
        signer.verify_receipt(receipt)


def test_non_enum_engine_fails_closed_at_export():
    """A retained receipt whose enum field became a plain string refuses as
    a verification error, not a raw AttributeError from serialisation."""
    log = make_log(make_signer(), count=1)
    log.receipts[0].engine_used = "Decimal"
    with pytest.raises(ReceiptSignatureError):
        log.export_json()


def test_non_enum_status_fails_closed_at_export():
    log = make_log(make_signer(), count=1)
    log.receipts[0].status = "verified"
    with pytest.raises(ReceiptSignatureError):
        log.export_json()


class _AliasingDict(dict):
    """Metadata that defeats copy.deepcopy by returning itself."""

    def __deepcopy__(self, memo):
        return self


def test_deepcopy_hook_cannot_alias_retained_evidence(monkeypatch):
    """The retained snapshot is built without caller-defined copy hooks, so
    a metadata object that returns itself from __deepcopy__ cannot carry a
    post-verification edit into what log() signs and retains."""
    signer = make_signer()
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = _AliasingDict(rule="genuine")
    signer.sign_receipt(receipt)
    log = AuditLog(signer=signer)

    real_verify = signer.verify_receipt

    def verify_then_race(target):
        real_verify(target)
        receipt.metadata["rule"] = "forged"

    monkeypatch.setattr(signer, "verify_receipt", verify_then_race)
    log.log(receipt)
    monkeypatch.setattr(signer, "verify_receipt", real_verify)

    retained = log.receipts[0]
    assert type(retained.metadata) is dict
    assert retained.metadata == {"rule": "genuine"}
    export = log.export_json()
    assert json.loads(export)["receipts"][0]["metadata"] == {"rule": "genuine"}
    log.verify_export_json(export)


def _deeply_nested(depth: int):
    value = []
    for _ in range(depth):
        value = [value]
    return value


def test_deeply_nested_json_text_refuses_to_verify():
    """Nesting past the recursion limit is a verification failure, not a
    RecursionError escaping the documented contract."""
    log = AuditLog(signer=make_signer())
    depth = 100_000
    hostile = "[" * depth + "]" * depth
    with pytest.raises(ReceiptSignatureError):
        log.verify_export_json(hostile)


def test_deeply_nested_parsed_export_refuses_to_verify():
    signer = make_signer()
    document = json.loads(signed_export())
    document["receipts"][0]["metadata"] = {"deep": _deeply_nested(100_000)}
    with pytest.raises(ReceiptSignatureError):
        signer.verify_export_document(document)


def test_oversized_integer_literal_refuses_to_verify():
    """Python's integer-digit limit (3.10.7+) raises a plain ValueError, which
    is not a JSONDecodeError; it must still surface as a verification failure."""
    log = AuditLog(signer=make_signer())
    hostile = '{"schema": ' + "1" * 5000 + "}"
    with pytest.raises(ReceiptSignatureError):
        log.verify_export_json(hostile)


def test_relogging_a_signed_receipt_with_a_non_enum_field_refuses():
    """Re-verifying existing evidence fails as ReceiptSignatureError, like
    verify_receipt, never as a raw AttributeError."""
    signer = make_signer()
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    signer.sign_receipt(receipt)
    receipt.engine_used = "Decimal"
    log = AuditLog(signer=signer)
    with pytest.raises(ReceiptSignatureError):
        log.log(receipt)
    assert log.receipts == []


def test_logging_fresh_content_with_a_non_enum_field_is_a_type_error():
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.status = "verified"
    log = AuditLog(signer=make_signer())
    with pytest.raises(TypeError):
        log.log(receipt)
    assert log.receipts == []


def _metadata_at_depth(depth, container):
    """Metadata whose nesting, counting the metadata dict, is exactly depth."""
    value = [] if container == "list" else {}
    for _ in range(depth - 2):
        value = [value] if container == "list" else {"k": value}
    return {"deep": value}


@pytest.mark.parametrize("container", ["list", "dict"])
def test_nesting_at_the_bound_logs_and_exports(container):
    """At exactly MAX_NESTING_DEPTH a receipt is retained, signed, exported
    and verified: every later step works on bounded data."""
    from qwed_finance.models.receipt import MAX_NESTING_DEPTH, _nesting_depth

    metadata = _metadata_at_depth(MAX_NESTING_DEPTH, container)
    assert _nesting_depth(metadata) == MAX_NESTING_DEPTH
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = metadata
    log.log(receipt)
    log.verify_export_json(log.export_json())


@pytest.mark.parametrize("container", ["list", "dict"])
def test_nesting_one_past_the_bound_is_refused_at_log(container):
    from qwed_finance.models.receipt import MAX_NESTING_DEPTH

    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = _metadata_at_depth(MAX_NESTING_DEPTH + 1, container)
    with pytest.raises(ValueError, match="nests deeper"):
        log.log(receipt)
    assert log.receipts == []


def test_nesting_past_the_bound_in_proof_steps_is_refused():
    from qwed_finance.models.receipt import MAX_NESTING_DEPTH

    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    # The "deep" value nests MAX_NESTING_DEPTH lists; the proof_steps list
    # around it makes one more.
    receipt.proof_steps = [_metadata_at_depth(MAX_NESTING_DEPTH + 1, "list")["deep"]]
    with pytest.raises(ValueError, match="proof_steps nests deeper"):
        log.log(receipt)


def test_retained_receipt_mutated_past_the_bound_refuses_export():
    """A retained receipt edited past the bound after logging refuses the
    signed export as a verification error."""
    from qwed_finance.models.receipt import MAX_NESTING_DEPTH

    log = make_log(make_signer(), count=1)
    log.receipts[0].metadata = _metadata_at_depth(MAX_NESTING_DEPTH + 1, "dict")
    with pytest.raises(ReceiptSignatureError):
        log.export_json()


def test_nesting_past_the_limit_is_refused_at_log():
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = {"deep": _deeply_nested(100_000)}
    with pytest.raises(ValueError):
        log.log(receipt)
    assert log.receipts == []


def test_verify_receipt_directly_refuses_a_non_enum_field():
    """verify_receipt is public: called on a receipt whose enum field became
    a string, it refuses as ReceiptSignatureError, not AttributeError."""
    signer = make_signer()
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    signer.sign_receipt(receipt)
    receipt.engine_used = "Decimal"
    with pytest.raises(ReceiptSignatureError):
        signer.verify_receipt(receipt)


@pytest.mark.parametrize(
    "value, expected",
    [
        (42, 0),
        ("text", 0),
        ([], 1),
        ({}, 1),
        ([1, "a", None, 2.5], 1),
        ({"a": [1, {"b": []}], "c": 3}, 4),
        ([[], [[[]]], []], 4),
    ],
)
def test_nesting_depth_counts_containers_only(value, expected):
    from qwed_finance.models.receipt import _nesting_depth

    assert _nesting_depth(value) == expected


def test_nesting_depth_memory_does_not_grow_with_width():
    """One iterator per open container: a list of a million scalars costs
    one iterator, not one stack entry per element.

    The test measures only when it owns tracemalloc outright. If the runner
    is already tracing (PYTHONTRACEMALLOC), measuring would mean resetting
    the runner's peak or stopping its tracing, so the test skips instead and
    leaves the runner's traces and peak untouched.
    """
    import tracemalloc

    from qwed_finance.models.receipt import _nesting_depth

    if tracemalloc.is_tracing():
        pytest.skip("the runner owns tracemalloc; measuring would reset its peak")

    wide = [{"tags": list(range(1_000_000))}]
    tracemalloc.start()
    try:
        depth = _nesting_depth(wide)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert depth == 3
    assert peak < 64 * 1024


def test_wide_shallow_metadata_logs_and_exports():
    log = AuditLog(signer=make_signer())
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = {"tags": [f"t{i}" for i in range(50_000)]}
    log.log(receipt)
    log.verify_export_json(log.export_json())


@pytest.mark.parametrize(
    "signature, kid",
    [("ab" * 32, None), (None, "hmac-sha256:0000000000000000")],
    ids=["signature-only", "key-id-only"],
)
def test_half_signed_receipt_with_bad_content_is_a_signature_error(signature, kid):
    """Any signature state puts a receipt on the evidence path: even with
    content that cannot be encoded, a half-signed receipt refuses as
    ReceiptSignatureError, never as a raw TypeError."""
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.signature = signature
    receipt.signature_key_id = kid
    receipt.engine_used = "Decimal"
    log = AuditLog(signer=make_signer())
    with pytest.raises(ReceiptSignatureError):
        log.log(receipt)
    assert log.receipts == []


@pytest.mark.skipif(
    not hasattr(sys, "set_int_max_str_digits"),
    reason="interpreter has no integer-digit limit to lift",
)
def test_oversized_integer_literal_refuses_without_a_digit_limit():
    """On Python 3.10.0-3.10.6 there is no digit limit: the literal parses,
    and a tampered export must still be refused by the schema and signature
    checks."""
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        log = make_log(make_signer(), count=1)
        export = log.export_json()
        big = "1" * 5000
        hostile = [
            '{"schema": ' + big + "}",
            export.replace('"index": 0', '"index": ' + big, 1),
        ]
        assert all(text != export for text in hostile)
        for text in hostile:
            with pytest.raises(ReceiptSignatureError):
                log.verify_export_json(text)
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.skipif(
    not hasattr(sys, "set_int_max_str_digits"),
    reason="interpreter has no integer-digit limit to lift",
)
def test_genuine_export_with_a_long_integer_verifies_without_a_digit_limit():
    """Without a digit limit a long integer is ordinary content: an export
    that really was signed with one verifies. Only tampering is refused."""
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        log = AuditLog(signer=make_signer())
        receipt = ReceiptGenerator.create_receipt(
            "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
        )
        receipt.metadata = {"n": int("1" * 5000)}
        log.log(receipt)
        log.verify_export_json(log.export_json())
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_unsigned_log_refuses_non_finite_metadata(value):
    """Behaviour change: the old export emitted NaN/Infinity tokens, which
    are not JSON. A log without a signer now refuses them when logged."""
    log = AuditLog()
    receipt = ReceiptGenerator.create_receipt(
        "TestGuard.verify", VerificationEngine.DECIMAL, "1.00", True
    )
    receipt.metadata = {"score": value}
    with pytest.raises(ValueError):
        log.log(receipt)
    assert log.receipts == []
