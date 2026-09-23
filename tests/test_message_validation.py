"""Regression tests for message validation fail-closed behavior (#61-64).

Bracket counting, substring element checks, presence-only MT validation,
and open ISO schemas must reject hostile or malformed input.
"""

import pytest

from qwed_finance.guards.iso_guard import ISOGuard
from qwed_finance.message_guard import MessageGuard, MessageType, SwiftMtType


def _guard() -> MessageGuard:
    return MessageGuard()


# --- #61: well-formedness + unimplemented types ---------------------------


@pytest.mark.parametrize("bad", ["", "<>" * 4, "a < b", "{20:REF}"])
def test_non_xml_never_validates(bad):
    for msg_type in (
        MessageType.PACS_008,
        MessageType.CAMT_053,
        MessageType.PAIN_001,
    ):
        result = _guard().verify_iso20022_xml(bad, msg_type)
        assert result.valid is False


@pytest.mark.parametrize(
    "msg_type", [MessageType.PACS_002, MessageType.CAMT_054]
)
def test_unimplemented_types_fail_closed(msg_type):
    result = _guard().verify_iso20022_xml("<ok/>", msg_type)
    assert result.valid is False
    assert any("Unsupported message type" in e for e in result.errors)


# --- #62: tree-based element checks ---------------------------------------

_FULL_PACS = (
    "<Document>"
    "<GrpHdr><MsgId>A</MsgId><CreDtTm>2026-01-01</CreDtTm><NbOfTxs>1</NbOfTxs></GrpHdr>"
    "<CdtTrfTxInf><IntrBkSttlmAmt Ccy=\"USD\">100</IntrBkSttlmAmt>"
    "<DbtrAgt>X</DbtrAgt><CdtrAgt>Y</CdtrAgt></CdtTrfTxInf>"
    "</Document>"
)


def test_comment_carried_elements_do_not_satisfy():
    xml = (
        "<!-- <GrpHdr><MsgId>A</MsgId><CreDtTm>2026-01-01</CreDtTm>"
        "<NbOfTxs>1</NbOfTxs></GrpHdr><CdtTrfTxInf>"
        "<IntrBkSttlmAmt Ccy=\"USD\">100</IntrBkSttlmAmt>"
        "<DbtrAgt>X</DbtrAgt><CdtrAgt>Y</CdtrAgt></CdtTrfTxInf> -->"
        "<Document></Document>"
    )
    result = _guard().verify_iso20022_xml(xml, MessageType.PACS_008)
    assert result.valid is False
    assert any("GrpHdr" in e for e in result.errors)


def test_full_pacs008_validates():
    assert _guard().verify_iso20022_xml(_FULL_PACS, MessageType.PACS_008).valid is True


def test_bad_ccy_format_rejected():
    xml = _FULL_PACS.replace('Ccy="USD"', 'Ccy="usd"')
    result = _guard().verify_iso20022_xml(xml, MessageType.PACS_008)
    assert result.valid is False


# --- #63: MT grammar, duplicates, framing, MT940 --------------------------


def _mt103_frame(*fields: str) -> str:
    return "{1:F01X}{2:I103Y}{4:\n" + "\n".join(fields) + "\n-}"


_GOOD_MT103 = _mt103_frame(
    ":20:REF1",
    ":23B:CRED",
    ":32A:260516USD1000,00",
    ":50K:/1\nA",
    ":59:/2\nB",
    ":71A:OUR",
)


def test_good_mt103_validates():
    assert _guard().verify_swift_mt(_GOOD_MT103, SwiftMtType.MT103).valid is True


def test_impossible_32a_date_rejected():
    body = _mt103_frame(":20:R", ":32A:260231USD1,00")
    result = _guard().verify_swift_mt(body, SwiftMtType.MT103)
    assert result.valid is False
    assert any("32A" in e for e in result.errors)


@pytest.mark.parametrize(
    "amount", ["1000.00", "1000,000", "10000000000000000,00", "-5,00"]
)
def test_non_grammar_32a_amounts_rejected(amount):
    body = _mt103_frame(":20:R", f":32A:260516USD{amount}")
    result = _guard().verify_swift_mt(body, SwiftMtType.MT103)
    assert result.valid is False
    assert any("32A" in e for e in result.errors)


def test_duplicate_tags_rejected():
    body = _mt103_frame(":20:A", ":20:B")
    result = _guard().verify_swift_mt(body, SwiftMtType.MT103)
    assert result.valid is False
    assert any("uplicate" in e for e in result.errors)


def test_unframed_blob_rejected():
    result = _guard().verify_swift_mt(":20:REF1", SwiftMtType.MT103)
    assert result.valid is False
    assert any("block-4" in e for e in result.errors)


def test_mt940_minimum_set():
    body = "{4:\n:20:R\n:25:ACC\n:60F:C123\n-}"
    assert _guard().verify_swift_mt(body, SwiftMtType.MT940).valid is True
    bare = "{4:\n:20:R\n-}"
    result = _guard().verify_swift_mt(bare, SwiftMtType.MT940)
    assert result.valid is False


# --- #64: ISO JSON schema --------------------------------------------------


def _iso_msg(**overrides):
    message = {
        "MsgId": "M1",
        "CreDtTm": "2026-01-01T00:00:00Z",
        "NbOfTxs": 1,
        "TtlIntrBkSttlmAmt": {"amount": 100.0, "currency": "USD"},
    }
    message.update(overrides)
    return message


def test_iso_valid_message_passes():
    assert ISOGuard().verify_payment_message(_iso_msg()).verified is True


@pytest.mark.parametrize(
    "credtm", ["yesterday", "2026-13-45", "2026-01-01", "not-a-date"]
)
def test_iso_garbage_timestamps_rejected(credtm):
    result = ISOGuard().verify_payment_message(_iso_msg(CreDtTm=credtm))
    assert result.verified is False


def test_iso_missing_amount_block_rejected():
    message = _iso_msg()
    del message["TtlIntrBkSttlmAmt"]
    assert ISOGuard().verify_payment_message(message).verified is False


def test_iso_rider_fields_rejected():
    message = _iso_msg()
    message["injected"] = {"tool": "x"}
    assert ISOGuard().verify_payment_message(message).verified is False
