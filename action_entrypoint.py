#!/usr/bin/env python3
"""
QWED Finance Guard v2.0 - Action Entrypoint
Deterministic verification for banking calculations in CI/CD

Supports:
- verify: Single calculation verification
- scan-npv: Scan CSV for NPV/IRR calculations
- scan-bonds: Scan CSV for bond pricing (YTM, duration)
- scan-fx: Scan CSV for FX rate calculations
- scan-risk: Scan CSV for risk metrics (VaR, Sharpe)
"""

import sys
import os
import json
from pathlib import Path

# Add current directory to path for local imports
sys.path.insert(0, "/app")


def _safe_resolve(path: str, base: str | None = None) -> str:
    """Resolve a path safely, preventing directory traversal outside base."""
    if base is None:
        base = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
    base_resolved = Path(base).resolve()
    path_obj = Path(path)
    resolved = (base_resolved / path).resolve() if not path_obj.is_absolute() else path_obj.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise ValueError(f"Path traversal detected: {path} resolves outside {base}")
    return str(resolved)

# Lazy imports to avoid loading unnecessary dependencies
def get_finance_verifier():
    from qwed_finance import FinanceVerifier
    return FinanceVerifier()

def get_bond_guard():
    from qwed_finance import BondGuard
    return BondGuard()

def get_fx_guard():
    from qwed_finance import FXGuard
    return FXGuard()

def get_risk_guard():
    from qwed_finance import RiskGuard
    return RiskGuard()


def set_output(name: str, value: str):
    """Set GitHub Actions output"""
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{name}={value}\n")
    # print(f"::set-output name={name}::{value}") # Deprecated


def generate_sarif(findings: list, repo: str, version: str | None = None) -> dict:
    """Generate SARIF output for GitHub Security tab"""
    from qwed_finance import __version__
    ver = version or __version__
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "QWED Finance Guard",
                    "version": ver,
                    "informationUri": "https://github.com/QWED-AI/qwed-finance",
                    "rules": [
                        {
                            "id": "QWED-FIN-001",
                            "name": "FinancialCalculationError",
                            "shortDescription": {"text": "LLM financial calculation mismatch"},
                            "fullDescription": {"text": "The LLM output differs from the mathematically proven value."},
                            "defaultConfiguration": {"level": "error"}
                        },
                        {
                            "id": "QWED-FIN-002",
                            "name": "RowNotVerified",
                            "shortDescription": {"text": "Row could not be verified"},
                            "fullDescription": {"text": "The row was skipped or could not be parsed or verified, so nothing about it was proven."},
                            "defaultConfiguration": {"level": "error"}
                        }
                    ]
                }
            },
            "results": [
                {
                    "ruleId": f.get("rule_id", "QWED-FIN-001"),
                    "level": "error",
                    "message": {"text": f.get("message", "Verification failed")},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.get("file", "unknown")},
                            "region": {"startLine": f.get("line", 1)}
                        }
                    }]
                } for f in findings
            ]
        }]
    }


def generate_badge_url(verified: bool) -> str:
    """Generate badge URL based on verification status"""
    status = "passing" if verified else "failing"
    color = "brightgreen" if verified else "red"
    return f"https://img.shields.io/badge/QWED_Finance-{status}-{color}"


def action_verify():
    """Verify a single financial calculation"""
    verification_type = os.getenv("INPUT_VERIFICATION_TYPE", "npv")
    llm_output = os.getenv("INPUT_LLM_OUTPUT", "")
    
    if not llm_output:
        print("❌ Error: llm_output is required for verify mode")
        sys.exit(1)
    
    verifier = get_finance_verifier()
    result = None
    
    if verification_type == "npv":
        cashflows_str = os.getenv("INPUT_CASHFLOWS", "")
        rate = float(os.getenv("INPUT_RATE", "0.1"))
        
        if not cashflows_str:
            print("❌ Error: cashflows required for NPV verification")
            sys.exit(1)
        
        cashflows = [float(x.strip()) for x in cashflows_str.split(",")]
        result = verifier.verify_npv(cashflows, rate, llm_output)
    
    elif verification_type == "irr":
        cashflows_str = os.getenv("INPUT_CASHFLOWS", "")
        
        if not cashflows_str:
            print("❌ Error: cashflows required for IRR verification")
            sys.exit(1)
        
        cashflows = [float(x.strip()) for x in cashflows_str.split(",")]
        result = verifier.verify_irr(cashflows, llm_output)
    
    elif verification_type == "monthly_payment":
        principal = float(os.getenv("INPUT_PRINCIPAL", "100000"))
        rate = float(os.getenv("INPUT_RATE", "0.06"))
        months = int(os.getenv("INPUT_MONTHS", "360"))
        result = verifier.verify_monthly_payment(principal, rate, months, llm_output)
    
    elif verification_type == "ytm":
        guard = get_bond_guard()
        face_value = float(os.getenv("INPUT_FACE_VALUE", "1000"))
        coupon_rate = float(os.getenv("INPUT_COUPON_RATE", "0.05"))
        price = float(os.getenv("INPUT_PRICE", "950"))
        years = float(os.getenv("INPUT_YEARS", "10"))
        result = guard.verify_ytm(face_value, coupon_rate, price, years, llm_output)
    
    elif verification_type == "duration":
        guard = get_bond_guard()
        face_value = float(os.getenv("INPUT_FACE_VALUE", "1000"))
        coupon_rate = float(os.getenv("INPUT_COUPON_RATE", "0.05"))
        ytm = float(os.getenv("INPUT_YTM", "0.06"))
        years = float(os.getenv("INPUT_YEARS", "10"))
        result = guard.verify_duration(face_value, coupon_rate, ytm, years, llm_output)
    
    elif verification_type == "forward_rate":
        guard = get_fx_guard()
        spot = float(os.getenv("INPUT_SPOT_RATE", "1.10"))
        domestic = float(os.getenv("INPUT_DOMESTIC_RATE", "0.05"))
        foreign = float(os.getenv("INPUT_FOREIGN_RATE", "0.02"))
        days = int(os.getenv("INPUT_DAYS", "90"))
        result = guard.verify_forward_rate(spot, domestic, foreign, days, llm_output)
    
    elif verification_type == "var":
        guard = get_risk_guard()
        portfolio = float(os.getenv("INPUT_PORTFOLIO_VALUE", "1000000"))
        volatility = float(os.getenv("INPUT_VOLATILITY", "0.02"))
        confidence = float(os.getenv("INPUT_CONFIDENCE", "0.95"))
        days = int(os.getenv("INPUT_DAYS", "1"))
        result = guard.verify_var(portfolio, volatility, confidence, days, llm_output)
    
    elif verification_type == "sharpe":
        guard = get_risk_guard()
        portfolio_return = float(os.getenv("INPUT_RETURN", "0.12"))
        risk_free = float(os.getenv("INPUT_RISK_FREE", "0.03"))
        volatility = float(os.getenv("INPUT_VOLATILITY", "0.15"))
        result = guard.verify_sharpe_ratio(portfolio_return, risk_free, volatility, llm_output)
    
    else:
        print(f"❌ Error: Unknown verification type: {verification_type}")
        sys.exit(1)
    
    # Output results
    output_format = os.getenv("INPUT_OUTPUT_FORMAT", "text")
    
    if output_format == "json":
        print(json.dumps({
            "verified": result.verified,
            "llm_value": result.llm_value,
            "computed_value": result.computed_value,
            "difference": result.difference,
            "formula_used": result.formula_used
        }, indent=2))
    else:
        if result.verified:
            print(f"✅ VERIFIED: LLM output matches computed value")
            print(f"   LLM Said: {result.llm_value}")
            print(f"   QWED Proved: {result.computed_value}")
        else:
            print(f"🛑 HALLUCINATION DETECTED:")
            print(f"   LLM Said: {result.llm_value}")
            print(f"   QWED Proved: {result.computed_value}")
            print(f"   Difference: {result.difference}")
    
    # Set outputs
    set_output("verified", str(result.verified).lower())
    set_output("computed_value", result.computed_value)
    set_output("badge_url", generate_badge_url(result.verified))
    
    if not result.verified and os.getenv("INPUT_FAIL_ON_ERROR", "true").lower() == "true":
        sys.exit(1)


def _shown(text: str) -> str:
    """Row text as it may be printed to the Actions log: one escaped line."""
    from qwed_finance._numeric import shown

    return shown(text)


def _cell(row, column: str):
    """A required or present cell; blank or NaN is an error, never a default."""
    import pandas as pd

    value = row[column]
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{column} is empty or NaN")
    return value


def _optional(row, column: str, optional: dict):
    """A column absent from the file uses its documented default; a present
    but blank cell is an error for the row."""
    if column not in row.index:
        return optional[column]
    return _cell(row, column)


def _finite(value, column: str) -> float:
    """A cell read as a finite float: float() accepts "inf" and "nan", and an
    infinite rate leaves an NPV of only the first cash flow."""
    import math

    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{column} must be finite")
    return number


# Largest day count a scan row may carry (about 2,700 years).
MAX_DAY_COUNT = 1_000_000


def _whole(value, column: str) -> int:
    """A cell that counts days: int() would truncate 1.9 to 1 and verify the
    claim against a different period, so a fraction is an error. It is checked
    on the exact decimal text — files are read without float conversion — as
    0.99999999999999999 becomes 1.0 in float."""
    from decimal import Decimal, InvalidOperation

    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{column} must be a whole number") from None
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"{column} must be a whole number")
    # Bounded before int(): 1e1000000 is integral and would materialise a
    # million-digit integer. No day count in these formulas comes near this.
    if number.copy_abs() > MAX_DAY_COUNT:
        raise ValueError(f"{column} must be at most {MAX_DAY_COUNT}")
    return int(number)


def _npv_row(verifier, row, optional):
    cashflows = [_finite(x, "cashflows") for x in str(_cell(row, "cashflows")).split(",")]
    rate = _finite(_optional(row, "rate", optional), "rate")
    return verifier.verify_npv(cashflows, rate, str(_cell(row, "llm_npv")))


def _bond_row(guard, row, optional):
    return guard.verify_ytm(
        _finite(_cell(row, "face_value"), "face_value"),
        _finite(_optional(row, "coupon_rate", optional), "coupon_rate"),
        _finite(_optional(row, "price", optional), "price"),
        _finite(_optional(row, "years", optional), "years"),
        str(_cell(row, "llm_ytm")),
    )


def _fx_row(guard, row, optional):
    return guard.verify_forward_rate(
        _finite(_cell(row, "spot_rate"), "spot_rate"),
        _finite(_optional(row, "domestic_rate", optional), "domestic_rate"),
        _finite(_optional(row, "foreign_rate", optional), "foreign_rate"),
        _whole(_optional(row, "days", optional), "days"),
        str(_cell(row, "llm_forward")),
    )


def _risk_row(guard, row, optional):
    return guard.verify_var(
        _finite(_cell(row, "portfolio_value"), "portfolio_value"),
        _finite(_optional(row, "volatility", optional), "volatility"),
        _finite(_optional(row, "confidence", optional), "confidence"),
        _whole(_optional(row, "holding_days", optional), "holding_days"),
        str(_cell(row, "llm_var")),
    )


def _csv_record_lines(path: str) -> list:
    """The 1-based line each CSV data record starts on, skipping blank lines
    as pandas does. A quoted value spanning lines or a blank line shifts rows
    off their line, so row position + 2 is not a line number."""
    import csv

    def blank(record) -> bool:
        # pandas skips a line that is empty or only whitespace; a line with
        # delimiters (",,") is a row of empty cells, and pandas keeps it.
        return not record or (len(record) == 1 and not record[0].strip())

    lines = []
    header_seen = False
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            previous = 0
            for record in reader:
                start, previous = previous + 1, reader.line_num
                if blank(record):
                    continue
                if not header_seen:
                    header_seen = True  # leading blank lines precede the header
                    continue
                lines.append(start)
    except csv.Error:
        # A file pandas read but the csv module cannot (a field past its
        # 131,072-character limit) has no line map: findings use line 1.
        return []
    return lines


def _json_frame(data):
    """A DataFrame from decoded JSON: an array of objects, or an object of
    columns. Anything else (an array holding null or a number, a bare value)
    is unreadable rather than a pandas AttributeError."""
    import pandas as pd

    if isinstance(data, list):
        if not all(isinstance(record, dict) for record in data):
            raise ValueError("a JSON array must contain only objects")
        return pd.DataFrame(data)
    if isinstance(data, dict):
        return pd.DataFrame(data)
    raise ValueError("JSON must be an array of objects or an object of columns")


# Each scan mode: the columns a row must have, the optional columns and their
# documented defaults, and how a row is verified.
SCAN_MODES = {
    "scan-npv": {"label": "NPV", "guard": get_finance_verifier, "verify": _npv_row,
                 "required": ("cashflows", "llm_npv"), "optional": {"rate": 0.1}},
    "scan-bonds": {"label": "YTM", "guard": get_bond_guard, "verify": _bond_row,
                   "required": ("face_value", "llm_ytm"),
                   "optional": {"coupon_rate": 0.05, "price": 1000, "years": 10}},
    "scan-fx": {"label": "Forward rate", "guard": get_fx_guard, "verify": _fx_row,
                "required": ("spot_rate", "llm_forward"),
                "optional": {"domestic_rate": 0.05, "foreign_rate": 0.02, "days": 90}},
    "scan-risk": {"label": "VaR", "guard": get_risk_guard, "verify": _risk_row,
                  "required": ("portfolio_value", "llm_var"),
                  "optional": {"volatility": 0.02, "confidence": 0.95, "holding_days": 1}},
}


def action_scan_file(scan_type: str):
    """Scan a CSV/JSON file for financial calculation errors"""
    import pandas as pd
    
    data_file = os.getenv("INPUT_DATA_FILE", "")

    if not data_file:
        print("❌ Error: No data file specified")
        sys.exit(1)

    try:
        data_file = _safe_resolve(data_file)
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    if not os.path.exists(data_file):
        print(f"❌ Error: Data file not found: {data_file}")
        sys.exit(1)
    
    print(f"🔍 QWED Finance Guard scanning: {data_file}")
    print(f"   Mode: {scan_type}")
    
    # Read data
    # Values are read as their exact text (CSV) or as Decimal (JSON numbers),
    # never through float, so a check such as "whole number of days" sees
    # what the file says. An empty or unreadable file is a scan with no rows,
    # which fails with its outputs set, rather than an exception.
    from decimal import Decimal, DecimalException

    read_error = None
    try:
        if data_file.endswith(".json"):
            with open(data_file, encoding="utf-8") as f:
                text = f.read()
            df = _json_frame(json.loads(text, parse_float=Decimal, parse_int=Decimal)) if text.strip() else pd.DataFrame()
        else:
            df = pd.read_csv(data_file, dtype=str)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()
    # DecimalException: a JSON number whose exponent is past Decimal's limit
    # (1e9999999999999999999) raises InvalidOperation, an ArithmeticError.
    except (OSError, ValueError, TypeError, DecimalException, pd.errors.ParserError) as e:
        df = pd.DataFrame()
        read_error = f"{type(e).__name__}: {_shown(str(e))}"
        print(f"❌ Could not read {data_file}: {read_error}")
    
    findings = []
    spec = SCAN_MODES[scan_type]
    guard = spec["guard"]()
    outcomes = {"verified": 0, "mismatch": 0, "skipped": 0, "error": 0}

    # Where each row starts in the file, for SARIF. JSON records carry no
    # line, and a CSV whose records do not line up with the parsed rows
    # cannot be mapped, so those findings point at line 1.
    wants_sarif = os.getenv("INPUT_OUTPUT_FORMAT", "text") == "sarif"
    record_lines = (
        _csv_record_lines(data_file)
        if wants_sarif and read_error is None and not data_file.endswith(".json")
        else []
    )
    if len(record_lines) != len(df):
        record_lines = []

    def not_verified(position, rule_id, message):
        line = record_lines[position] if 0 <= position < len(record_lines) else 1
        findings.append({
            "file": data_file, "line": line, "rule_id": rule_id, "message": message,
        })

    # A required column missing from the file means no row can be checked:
    # every row is skipped and counted as a failure, never as passed (#101).
    missing = [c for c in spec["required"] if c not in df.columns]
    if missing:
        print(f"⚠️ Missing required column(s): {', '.join(missing)}; "
              f"expected {', '.join(spec['required'])}")

    # An optional column absent from the whole file keeps its documented
    # default, and the summary says so. One present but blank in a row is an
    # error for that row, never silently replaced by the default.
    defaulted = [c for c in spec["optional"] if c not in df.columns]
    for column in defaulted:
        print(f"ℹ️ Column '{column}' not in file; default {spec['optional'][column]} used for every row")

    # Rows are numbered by position: a JSON index may be labels ("trade-1").
    for idx, (_, row) in enumerate(df.iterrows()):
        if missing:
            outcomes["skipped"] += 1
            not_verified(idx, "QWED-FIN-002",
                         f"Row skipped: missing column(s) {', '.join(missing)}")
            continue
        try:
            result = spec["verify"](guard, row, spec["optional"])
        except Exception as e:  # any parse or verification failure is a failed row
            outcomes["error"] += 1
            reason = f"{type(e).__name__}: {_shown(str(e))}"
            not_verified(idx, "QWED-FIN-002", f"Row not verified: {reason}")
            print(f"⚠️ Row {idx}: not verified - {reason}")
            continue
        if result.verified:
            outcomes["verified"] += 1
        elif str(result.computed_value).startswith("UNVERIFIABLE"):
            # The guard refused the row: nothing was compared, so it is an
            # error, not a calculation mismatch.
            outcomes["error"] += 1
            reason = _shown(str(result.computed_value))
            not_verified(idx, "QWED-FIN-002", f"Row not verified: {reason}")
            print(f"⚠️ Row {idx}: not verified - {reason}")
        else:
            outcomes["mismatch"] += 1
            label = spec["label"]
            not_verified(idx, "QWED-FIN-001",
                         f"{label} mismatch: LLM={result.llm_value}, Computed={result.computed_value}")
            print(f"🛑 Row {idx}: {label} error - LLM: {result.llm_value}, QWED: {result.computed_value}")

    # Summary
    total = len(df)
    failed = outcomes["mismatch"] + outcomes["skipped"] + outcomes["error"]
    if outcomes["verified"] == 0 and failed == 0:
        # An empty file verified nothing: that is a failure, not a pass.
        failed = 1
        not_verified(-1, "QWED-FIN-002", f"File not read: {read_error}" if read_error else "No rows to verify")
    passed = failed == 0

    print(f"\n{'='*50}")
    print(f"📊 Scan Complete: {outcomes['verified']}/{total} rows verified "
          f"({outcomes['mismatch']} mismatch, {outcomes['skipped']} skipped, {outcomes['error']} error)")
    if passed:
        print("✅ All calculations verified!")
    elif outcomes["verified"] == 0:
        print("❌ No rows were verified")
    else:
        print(f"❌ {failed} rows not verified")

    # Set outputs
    set_output("errors_count", str(failed))
    set_output("verified_count", str(outcomes["verified"]))
    set_output("badge_url", generate_badge_url(passed))

    # SARIF output
    output_format = os.getenv("INPUT_OUTPUT_FORMAT", "text")
    if output_format == "sarif" and findings:
        repo = os.getenv("GITHUB_REPOSITORY", "unknown")
        sarif = generate_sarif(findings, repo)
        sarif_path = "qwed-finance-results.sarif"
        with open(sarif_path, "w") as f:
            json.dump(sarif, f, indent=2)
        set_output("sarif_file", sarif_path)
        print(f"📄 SARIF output: {sarif_path}")

    if not passed and os.getenv("INPUT_FAIL_ON_ERROR", "true").lower() == "true":
        sys.exit(1)


def main():
    from qwed_finance import __version__
    action = os.getenv("INPUT_ACTION", "verify")
    
    print(f"🏦 QWED Finance Guard v{__version__}")
    print(f"   Action: {action}")
    print(f"{'='*50}")
    
    if action == "verify":
        action_verify()
    elif action in ["scan-npv", "scan-bonds", "scan-fx", "scan-risk"]:
        action_scan_file(action)
    else:
        print(f"❌ Unknown action: {action}")
        print("   Available: verify, scan-npv, scan-bonds, scan-fx, scan-risk")
        sys.exit(1)


if __name__ == "__main__":
    main()
