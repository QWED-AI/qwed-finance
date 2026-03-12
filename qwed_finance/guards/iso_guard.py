import json
import jsonschema
from typing import Dict, Any, List, Optional
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
                "CreDtTm": {"type": "string", "format": "date-time"},
                "NbOfTxs": {"type": "integer", "minimum": 1},
                "TtlIntrBkSttlmAmt": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number", "minimum": 0.01},
                        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"}
                    },
                    "required": ["amount", "currency"]
                }
            },
            "required": ["MsgId", "CreDtTm", "NbOfTxs"]
        }

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
            return ISOResult(verified=True, msg_type=msg_type)
        except jsonschema.ValidationError as e:
            return ISOResult(
                verified=False,
                msg_type=msg_type,
                error=f"Schema Violation: {e.message}",
                path=[str(p) for p in e.path]
            )

