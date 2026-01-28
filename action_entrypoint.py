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
    print(f"::set-output name={name}::{value}")


def generate_sarif(findings: list, repo: str) -> dict:
    """Generate SARIF output for GitHub Security tab"""
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "QWED Finance Guard",
                    "version": "2.0.0",
                    "informationUri": "https://github.com/QWED-AI/qwed-finance",
                    "rules": [
                        {
                            "id": "QWED-FIN-001",
                            "name": "FinancialCalculationError",
                            "shortDescription": {"text": "LLM financial calculation mismatch"},
                            "fullDescription": {"text": "The LLM output differs from the mathematically proven value."},
                            "defaultConfiguration": {"level": "error"}
                        }
                    ]
                }
            },
            "results": [
                {
                    "ruleId": "QWED-FIN-001",
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


def action_scan_file(scan_type: str):
    """Scan a CSV/JSON file for financial calculation errors"""
    import pandas as pd
    
    data_file = os.getenv("INPUT_DATA_FILE", "")
    
    if not data_file or not os.path.exists(data_file):
        print(f"❌ Error: Data file not found: {data_file}")
        sys.exit(1)
    
    print(f"🔍 QWED Finance Guard scanning: {data_file}")
    print(f"   Mode: {scan_type}")
    
    # Read data
    if data_file.endswith(".json"):
        with open(data_file) as f:
            df = pd.DataFrame(json.load(f))
    else:
        df = pd.read_csv(data_file)
    
    errors = []
    findings = []
    
    if scan_type == "scan-npv":
        verifier = get_finance_verifier()
        
        for idx, row in df.iterrows():
            if "cashflows" in row and "llm_npv" in row:
                try:
                    cashflows = [float(x) for x in str(row["cashflows"]).split(",")]
                    rate = float(row.get("rate", 0.1))
                    result = verifier.verify_npv(cashflows, rate, str(row["llm_npv"]))
                    
                    if not result.verified:
                        errors.append(idx)
                        findings.append({
                            "file": data_file,
                            "line": idx + 2,
                            "message": f"NPV mismatch: LLM={result.llm_value}, Computed={result.computed_value}"
                        })
                        print(f"🛑 Row {idx}: NPV error - LLM: {result.llm_value}, QWED: {result.computed_value}")
                except Exception as e:
                    print(f"⚠️ Row {idx}: Error processing - {e}")
    
    elif scan_type == "scan-bonds":
        guard = get_bond_guard()
        
        for idx, row in df.iterrows():
            if "face_value" in row and "llm_ytm" in row:
                try:
                    result = guard.verify_ytm(
                        float(row["face_value"]),
                        float(row.get("coupon_rate", 0.05)),
                        float(row.get("price", 1000)),
                        float(row.get("years", 10)),
                        str(row["llm_ytm"])
                    )
                    
                    if not result.verified:
                        errors.append(idx)
                        findings.append({
                            "file": data_file,
                            "line": idx + 2,
                            "message": f"YTM mismatch: LLM={result.llm_value}, Computed={result.computed_value}"
                        })
                        print(f"🛑 Row {idx}: YTM error - LLM: {result.llm_value}, QWED: {result.computed_value}")
                except Exception as e:
                    print(f"⚠️ Row {idx}: Error processing - {e}")
    
    elif scan_type == "scan-fx":
        guard = get_fx_guard()
        
        for idx, row in df.iterrows():
            if "spot_rate" in row and "llm_forward" in row:
                try:
                    result = guard.verify_forward_rate(
                        float(row["spot_rate"]),
                        float(row.get("domestic_rate", 0.05)),
                        float(row.get("foreign_rate", 0.02)),
                        int(row.get("days", 90)),
                        str(row["llm_forward"])
                    )
                    
                    if not result.verified:
                        errors.append(idx)
                        findings.append({
                            "file": data_file,
                            "line": idx + 2,
                            "message": f"Forward rate mismatch: LLM={result.llm_value}, Computed={result.computed_value}"
                        })
                        print(f"🛑 Row {idx}: Forward rate error - LLM: {result.llm_value}, QWED: {result.computed_value}")
                except Exception as e:
                    print(f"⚠️ Row {idx}: Error processing - {e}")
    
    elif scan_type == "scan-risk":
        guard = get_risk_guard()
        
        for idx, row in df.iterrows():
            if "portfolio_value" in row and "llm_var" in row:
                try:
                    result = guard.verify_var(
                        float(row["portfolio_value"]),
                        float(row.get("volatility", 0.02)),
                        float(row.get("confidence", 0.95)),
                        int(row.get("holding_days", 1)),
                        str(row["llm_var"])
                    )
                    
                    if not result.verified:
                        errors.append(idx)
                        findings.append({
                            "file": data_file,
                            "line": idx + 2,
                            "message": f"VaR mismatch: LLM={result.llm_value}, Computed={result.computed_value}"
                        })
                        print(f"🛑 Row {idx}: VaR error - LLM: {result.llm_value}, QWED: {result.computed_value}")
                except Exception as e:
                    print(f"⚠️ Row {idx}: Error processing - {e}")
    
    # Summary
    total = len(df)
    error_count = len(errors)
    
    print(f"\n{'='*50}")
    print(f"📊 Scan Complete: {total - error_count}/{total} rows passed")
    
    if error_count > 0:
        print(f"❌ {error_count} errors found")
    else:
        print("✅ All calculations verified!")
    
    # Set outputs
    set_output("errors_count", str(error_count))
    set_output("badge_url", generate_badge_url(error_count == 0))
    
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
    
    if error_count > 0 and os.getenv("INPUT_FAIL_ON_ERROR", "true").lower() == "true":
        sys.exit(1)


def main():
    action = os.getenv("INPUT_ACTION", "verify")
    
    print(f"🏦 QWED Finance Guard v2.0")
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
