import json
import jsonschema
from datetime import datetime
from typing import Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class ISOResult:
    """Result of ISO 20022 schema validation."""
    verified: bool
    standard: str = "ISO 20022"
    msg_type: str = ""
    error: str = ""
    path: List[str] = field(default_factory=list)
    verification_mode: str = "SCHEMA"


class ISOGuard:
    """
    Verifies that financial messages conform to ISO 20022 standards.
    Prevents 'Schema Violations' in banking interoperability.
    """
    def __init__(self):
        # Simplified schema for ISO 20022 pacs.008 (Customer Credit Transfer)
        # In production, this would load full XSD/JSON schemas.
        self.pacs_008_schema = {
            "type": "object",
            "properties": {
                "MsgId": {"type": "string", "pattern": "^[A-Za-z0-9]{1,35}$"},
                "CreDtTm": {
                    "type": "string",
                    # ASCII digits, full calendar ranges, mandatory seconds,
                    # \Z anchor (no trailing newline). Shape only: values
                    # still pass through datetime.fromisoformat below for
                    # real month/day validity (e.g. Feb 30).
                    "pattern": (
                        r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
                        r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
                        r"(\.\d+)?(Z|[+-](0[0-9]|1[0-9]|2[0-3]):?[0-5][0-9])?\Z"
                    ),
                },
                "NbOfTxs": {"type": "integer", "minimum": 1},
                "TtlIntrBkSttlmAmt": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number", "minimum": 0.01},
                        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"}
                    },
                    "required": ["amount", "currency"],
                    "additionalProperties": False
                }
            },
            "required": ["MsgId", "CreDtTm", "NbOfTxs", "TtlIntrBkSttlmAmt"],
            "additionalProperties": False
        }

    @staticmethod
    def _valid_credtm(value: str) -> bool:
        """True when value is a real calendar timestamp (ISO-8601)."""
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            datetime.fromisoformat(text)
            return True
        except ValueError:
            return False

    def verify_payment_message(self, message: Dict[str, Any], msg_type: str = "pacs.008") -> ISOResult:
        """
        Validates AI-generated payment instructions against ISO 20022 standards.
        """
        if msg_type != "pacs.008":
            return ISOResult(
                verified=False,
                msg_type=msg_type,
                error=f"Unsupported message type: {msg_type}"
            )

        try:
            jsonschema.validate(instance=message, schema=self.pacs_008_schema)
        except jsonschema.ValidationError as e:
            return ISOResult(
                verified=False,
                msg_type=msg_type,
                error=f"Schema Violation: {e.message}",
                path=[str(p) for p in e.path]
            )

        # Semantic timestamp check: the pattern enforces shape, but only
        # calendar parsing rejects impossible dates (e.g. Feb 30).
        cre_dt_tm = message.get("CreDtTm")
        if isinstance(cre_dt_tm, str) and not self._valid_credtm(cre_dt_tm):
            return ISOResult(
                verified=False,
                msg_type=msg_type,
                error="Schema Violation: 'CreDtTm' is not a valid ISO-8601 timestamp",
                path=["CreDtTm"],
            )
        return ISOResult(verified=True, msg_type=msg_type)

