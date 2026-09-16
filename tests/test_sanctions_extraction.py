"""Regression tests for SWIFT sanctions extraction (#74, #75).

Seeded corpus: decoy tags in free text, multi-line names, non-whitelist
party fields (52D/56D/57D), structured 59F, and a clean control.
"""

from qwed_finance.cross_guard import CrossGuard


def _mt(*fields: str) -> str:
    body = "\n".join(
        [":20:REF123", ":23B:CRED", ":32A:260516USD1000,00", *fields]
    )
    return (
        "{1:F01BANKUS33AXXX0000000000}"
        "{2:I103BANKGB2LXXXXN}"
        "{4:\n" + body + "\n-}"
    )


CLEAN = _mt(":50K:/111\nALICE", ":59:/222\nBOB", ":71A:OUR")


def test_clean_message_passes_and_exposes_screened():
    result = CrossGuard().verify_swift_with_sanctions(CLEAN, ["BANNED ENTITY LTD"])
    assert result.passed is True
    assert "BANNED ENTITY LTD" not in " ".join(result.screened_entities)
    assert any("ALICE" in entity for entity in result.screened_entities)
    assert "-}" not in result.screened_entities


def test_multiline_beneficiary_name_screened():
    message = _mt(
        ":50K:/12345678\nJOHN SMITH",
        ":59:/98765432\nACME CORP\nBANNED ENTITY LTD",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(message, ["BANNED ENTITY LTD"])
    assert result.passed is False
    assert result.guard_results["ComplianceGuard.sanctions"] is False
    assert any("SANCTIONS HIT" in violation for violation in result.violations)


def test_decoy_tag_in_free_text_does_not_blind_real_line():
    message = _mt(
        ":59:/98765432\nREAL BENEFICIARY",
        ":70:REM INFO :59: DECOY NAME",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(message, ["REAL BENEFICIARY"])
    assert result.passed is False
    assert any("DECOY NAME" in entity for entity in result.screened_entities)


def test_non_whitelist_institution_fields_screened():
    message = _mt(
        ":50K:/111\nALICE",
        ":59:/222\nBOB",
        ":52D:BANNED BANK PLC",
        ":56D:BANNED INTERMEDIARY",
        ":57D:BANNED ACCOUNTS WITH",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(
        message, ["BANNED BANK PLC", "BANNED INTERMEDIARY", "BANNED ACCOUNTS WITH"]
    )
    assert result.passed is False
    assert len([v for v in result.violations if "SANCTIONS HIT" in v]) == 3


def test_structured_59f_name_screened():
    message = _mt(
        ":50K:/111\nALICE",
        ":59F:/98765432\n1/BANNED ENTITY LTD\n2/MAIN STREET",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(message, ["BANNED ENTITY LTD"])
    assert result.passed is False


def test_free_text_70_72_lines_screened():
    message = _mt(
        ":50K:/111\nALICE",
        ":59:/222\nBOB",
        ":70:/INS/BANNED BANK PLC",
        ":72:/INS/SECOND CHANCE BANK",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(
        message, ["BANNED BANK PLC", "SECOND CHANCE BANK"]
    )
    assert result.passed is False
    assert any("SECOND CHANCE BANK" in entity for entity in result.screened_entities)


def test_extractor_rejects_non_string_input():
    assert CrossGuard()._extract_entities_from_mt(None) == []
    assert CrossGuard()._extract_entities_from_mt(12345) == []


def test_extractor_dedupes_and_drops_trailer():
    entities = CrossGuard()._extract_entities_from_mt(
        ":59:/222\nBOB\nBOB\n-}"
    )
    assert entities == ["/222", "BOB"]


def test_trailer_with_block5_suffix_dropped():
    entities = CrossGuard()._extract_entities_from_mt(
        ":59:/222\nBOB\n-}{5:{CHK:ABCDEF123456}}"
    )
    assert entities == ["/222", "BOB"]


def test_50a_value_screened():
    message = _mt(
        ":50A:/111\nBANNED ORDERING BANK",
        ":59:/222\nBOB",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(
        message, ["BANNED ORDERING BANK"]
    )
    assert result.passed is False
    assert result.guard_results["ComplianceGuard.sanctions"] is False


def test_address_fragment_does_not_false_positive():
    message = _mt(
        ":50K:/111\nALICE",
        ":59:/222\nBOB\nLONDON",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(
        message, ["BANK OF LONDON PLC"]
    )
    assert result.passed is True


def test_split_structured_name_reconstructed():
    message = _mt(
        ":50K:/111\nALICE",
        ":59F:/98765432\n1/BANNED ENTITY\n1/LTD",
        ":71A:OUR",
    )
    result = CrossGuard().verify_swift_with_sanctions(
        message, ["BANNED ENTITY LTD"]
    )
    assert result.passed is False
