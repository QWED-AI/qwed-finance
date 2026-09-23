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
    "amount",
    ["1000.00", "1000", "0", "0,00", "10000000000000000,00", "-5,00"],
)
def test_non_grammar_32a_amounts_rejected(amount):
    body = _mt103_frame(":20:R", f":32A:260516USD{amount}")
    result = _guard().verify_swift_mt(body, SwiftMtType.MT103)
    assert result.valid is False
    assert any("32A" in e for e in result.errors)


def test_32a_embedded_whitespace_rejected():
    body = _mt103_frame(":20:R", ":32A:260516USD1 0,00")
    result = _guard().verify_swift_mt(body, SwiftMtType.MT103)
    assert result.valid is False
    assert any("32A" in e for e in result.errors)


@pytest.mark.parametrize(
    "value", ["260516USD1٠٠٠,٠٠", "٢٦٠٥١٦USD1000,00"]
)
def test_32a_unicode_digits_rejected(value):
    # SWIFT X character set is ASCII-only; \d would accept Unicode
    # decimal digits in both the date and the amount.
    assert _guard()._validate_32a_field(value) is False


def test_32a_trailing_comma_amount_accepted():
    body = _mt103_frame(
        ":20:R",
        ":23B:CRED",
        ":32A:260516USD1000,",
        ":50K:/1\nA",
        ":59:/2\nB",
        ":71A:OUR",
    )
    assert _guard().verify_swift_mt(body, SwiftMtType.MT103).valid is True


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


def test_iso_valid_fractional_offset_timestamp_passes():
    message = _iso_msg(CreDtTm="2026-01-01T00:00:00.123+05:30")
    assert ISOGuard().verify_payment_message(message).verified is True


@pytest.mark.parametrize(
    "credtm",
    [
        # accepted by the pattern; calendar check must not depend on
        # Python-version fromisoformat quirks (3.10 rejects these forms)
        "2026-01-01T00:00:00+0530",
        "2026-01-01T00:00:00.1Z",
        "2026-01-01T00:00:00.123456+0000",
    ],
)
def test_iso_version_stable_timestamp_forms_pass(credtm):
    result = ISOGuard().verify_payment_message(_iso_msg(CreDtTm=credtm))
    assert result.verified is True


@pytest.mark.parametrize(
    "credtm",
    [
        "yesterday",
        "2026-13-45",
        "2026-01-01",
        "not-a-date",
        # shaped like ISO but out of range at the pattern level
        "2026-13-45T00:00:00Z",
        "2026-01-01T25:00:00Z",
        "2026-01-01T00:61:00Z",
        # shaped and in-range but impossible as a calendar date
        "2026-02-30T00:00:00Z",
        # non-ASCII digits must not pass
        "２０２６-01-01T00:00:00Z",
        # $ would accept a trailing newline; \Z must not
        "2026-01-01T00:00:00Z\n",
    ],
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


# --- Review fixes: hierarchy, framing scoping, parser hardening -----------


_FULL_CAMT = (
    "<Document>"
    "<GrpHdr><MsgId>S</MsgId><CreDtTm>2026-01-01</CreDtTm></GrpHdr>"
    "<Stmt><Acct>ACC</Acct><Bal>C123</Bal></Stmt>"
    "</Document>"
)

_FULL_PAIN = (
    "<Document>"
    "<GrpHdr><MsgId>P</MsgId><CreDtTm>2026-01-01</CreDtTm></GrpHdr>"
    "<PmtInf><PmtMtd>TRF</PmtMtd></PmtInf>"
    "</Document>"
)


def test_full_camt053_validates():
    result = _guard().verify_iso20022_xml(_FULL_CAMT, MessageType.CAMT_053)
    assert result.valid is True


def test_full_pain001_validates():
    result = _guard().verify_iso20022_xml(_FULL_PAIN, MessageType.PAIN_001)
    assert result.valid is True


def test_element_in_wrong_branch_rejected():
    # MsgId exists but sits outside GrpHdr: global-name presence is not
    # enough, the ISO parentage must hold.
    xml = (
        "<Document>"
        "<MsgId>A</MsgId>"
        "<GrpHdr><CreDtTm>2026-01-01</CreDtTm><NbOfTxs>1</NbOfTxs></GrpHdr>"
        "<CdtTrfTxInf><IntrBkSttlmAmt Ccy=\"USD\">100</IntrBkSttlmAmt>"
        "<DbtrAgt>X</DbtrAgt><CdtrAgt>Y</CdtrAgt></CdtTrfTxInf>"
        "</Document>"
    )
    result = _guard().verify_iso20022_xml(xml, MessageType.PACS_008)
    assert result.valid is False
    assert any("under GrpHdr" in e for e in result.errors)


def test_amount_without_ccy_rejected():
    xml = _FULL_PACS.replace(' Ccy="USD"', "")
    result = _guard().verify_iso20022_xml(xml, MessageType.PACS_008)
    assert result.valid is False
    assert any("Ccy" in e for e in result.errors)


def test_encoding_declaration_still_validates():
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + _FULL_PACS
    result = _guard().verify_iso20022_xml(xml, MessageType.PACS_008)
    assert result.valid is True


def test_dtd_entity_payload_rejected():
    xml = '<!DOCTYPE Document [<!ENTITY x "boom">]><Document>&x;</Document>'
    result = _guard().verify_iso20022_xml(xml, MessageType.PACS_008)
    assert result.valid is False


def test_block5_trailer_still_valid():
    framed = _GOOD_MT103 + "{5:{CHK:ABCDEF123456}}"
    assert _guard().verify_swift_mt(framed, SwiftMtType.MT103).valid is True


def test_fields_outside_block4_do_not_count():
    framed = _mt103_frame(
        ":23B:CRED",
        ":32A:260516USD1000,00",
        ":50K:/1\nA",
        ":59:/2\nB",
        ":71A:OUR",
    )
    injected = ":20:REF1" + framed
    result = _guard().verify_swift_mt(injected, SwiftMtType.MT103)
    assert result.valid is False
    assert any("Missing required field 20" in e for e in result.errors)


def test_colon_in_field20_value_counts_toward_length():
    body = _mt103_frame(
        ":20:ABCDEFGHIJKLMNO:P",
        ":23B:CRED",
        ":32A:260516USD1000,00",
        ":50K:/1\nA",
        ":59:/2\nB",
        ":71A:OUR",
    )
    result = _guard().verify_swift_mt(body, SwiftMtType.MT103)
    assert result.valid is False
    assert any("exceeds maximum length" in e for e in result.errors)


def test_value_embedded_tag_is_not_a_field_or_duplicate():
    guard = _guard()
    body = ":20:REF1\n:72:/INS/x:20:OVERRIDE"
    assert guard._parse_mt_fields(body)["20"] == "REF1"
    assert guard._duplicate_mt_tags(body) == []


def test_mt202_uses_its_own_required_set():
    result = _guard().verify_swift_mt("{4:\n:20:R\n-}", SwiftMtType.MT202)
    assert result.message_type == "MT202"
    assert any("Missing required field 21" in e for e in result.errors)


def test_enum_member_without_branch_falls_to_minimal_set():
    result = _guard().verify_swift_mt("{4:\n:20:R\n-}", SwiftMtType.MT950)
    assert result.valid is True


def test_local_name_of_non_string_tag_is_empty():
    assert MessageGuard._local_name(object()) == ""


def test_validators_fail_closed_on_unparseable_xml():
    guard = _guard()
    expected = ["Message is not parseable XML"]
    assert guard._validate_pacs008("<bad") == expected
    assert guard._validate_camt053("<bad") == expected
    assert guard._validate_pain001("<bad") == expected


def test_defusedxml_fallback_runs_when_lxml_unavailable():
    guard = _guard()
    guard._lxml_available = False
    assert guard._is_well_formed_xml("<Document/>") is True
    assert guard._is_well_formed_xml("a < b") is False


def test_iso_unsupported_msg_type_rejected():
    result = ISOGuard().verify_payment_message(_iso_msg(), "pacs.002")
    assert result.verified is False
    assert "Unsupported message type" in (result.error or "")
