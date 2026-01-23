# QWED-Finance 🏦

**Deterministic verification middleware for banking and financial AI.**

[![Verified by QWED](https://img.shields.io/badge/Verified_by-QWED-00C853?style=flat&logo=checkmarx)](https://github.com/QWED-AI/qwed-finance)
[![GitHub Developer Program](https://img.shields.io/badge/GitHub_Developer_Program-Member-4c1?style=flat&logo=github)](https://github.com/QWED-AI)
[![PyPI](https://img.shields.io/pypi/v/qwed-finance?color=blue)](https://pypi.org/project/qwed-finance/)
[![npm](https://img.shields.io/npm/v/@qwed-ai/finance?color=red)](https://www.npmjs.com/package/@qwed-ai/finance)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

> Part of the [QWED Ecosystem](https://github.com/QWED-AI) - Verification Infrastructure for AI

---

## 🎯 What is QWED-Finance?

QWED-Finance is a **middleware layer** that applies QWED's deterministic verification to banking and financial calculations. It ensures AI-generated financial outputs are mathematically correct before they reach production.

### Key Features

| Feature | Description |
|---------|-------------|
| **NPV/IRR Verification** | Validate net present value and internal rate of return calculations |
| **Loan Amortization** | Verify payment schedules and interest calculations |
| **Compound Interest** | Check compound interest formulas with precision |
| **Currency Safety** | Prevent floating-point errors in money calculations |
| **ISO 20022 Schemas** | Built-in support for banking message standards |

---

## 💡 What QWED-Finance Is (and Isn't)

### ✅ QWED-Finance IS:
- **Verification middleware** that checks LLM-generated financial outputs
- **Deterministic** — uses symbolic math (SymPy) and formal proofs (Z3)
- **Open source** — integrate into any fintech workflow, no vendor lock-in
- **A safety layer** — catches calculation errors before they cause real losses

### ❌ QWED-Finance is NOT:
- ~~A trading platform~~ — use Bloomberg or Refinitiv for that
- ~~A market data provider~~ — use AlphaSense or FactSet for that
- ~~An analytics dashboard~~ — use Koyfin or Morningstar for that
- ~~A replacement for risk models~~ — we just verify their outputs

> **Think of QWED-Finance as the "unit test" for AI-generated financial calculations.**
> 
> Bloomberg provides data. AlphaSense analyzes. **QWED verifies the math.**

---

## 🆚 How We're Different from Financial AI Platforms

| Aspect | Bloomberg / Refinitiv / AlphaSense | QWED-Finance |
|--------|-------------------------------------|--------------|
| **Approach** | Probabilistic AI analytics | Deterministic symbolic verification |
| **Output** | "NPV is approximately $180.42" | `VERIFIED: NPV = $180.42 ✓` (with proof) |
| **Accuracy** | ~95% (estimation, approximation) | 100% mathematical certainty |
| **Tech** | ML models, LLMs | SymPy + Z3 SMT Solver |
| **Model** | $20k+/year enterprise SaaS | Free (Apache 2.0 License) |
| **Data** | Proprietary market data | Your data, verified locally |

### Use Together (Best Practice)
```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  Bloomberg   │ ──► │ QWED-Finance  │ ──► │   Verified   │
│ (AI outputs) │     │   (verifies)  │     │   Output     │
└──────────────┘     └───────────────┘     └──────────────┘
```

---

## 🛡️ The Six Guards

### 1. Compliance Guard (Z3-Powered)
**KYC/AML regulatory verification with formal boolean logic proofs.**

```python
from qwed_finance import ComplianceGuard

guard = ComplianceGuard()

# Verify AML flagging decision
result = guard.verify_aml_flag(
    amount=15000,        # Over $10k threshold
    country_code="US",
    llm_flagged=True     # LLM flagged it
)
# result.compliant = True ✅
```

**Supports:**
- AML/CTR threshold checks (BSA/FinCEN)
- KYC completion verification
- Transaction limit enforcement
- OFAC sanctions screening

### 2. Calendar Guard (Day Count Conventions)
**Deterministic day counting for interest accrual - no date hallucinations.**

```python
from qwed_finance import CalendarGuard, DayCountConvention
from datetime import date

guard = CalendarGuard()

# Verify 30/360 day count
result = guard.verify_day_count(
    start_date=date(2026, 1, 1),
    end_date=date(2026, 7, 1),
    llm_days=180,
    convention=DayCountConvention.THIRTY_360
)
# result.verified = True ✅
```

**Supports:**
- 30/360 (Corporate bonds)
- Actual/360 (T-Bills)
- Actual/365 (UK gilts)
- Business day verification

### 3. Derivatives Guard (Black-Scholes)
**Options pricing and margin verification using pure calculus.**

```python
from qwed_finance import DerivativesGuard, OptionType

guard = DerivativesGuard()

# Verify Black-Scholes call price
result = guard.verify_black_scholes(
    spot_price=100,
    strike_price=105,
    time_to_expiry=0.25,   # 3 months
    risk_free_rate=0.05,
    volatility=0.20,
    option_type=OptionType.CALL,
    llm_price="$3.50"
)
# result.greeks = {"delta": 0.4502, "gamma": 0.0389, ...}
```

### 4. Message Guard (ISO 20022 / SWIFT)
**Validate LLM-generated banking messages conform to industry standards.**

```python
from qwed_finance import MessageGuard, MessageType

guard = MessageGuard()

# Verify ISO 20022 pacs.008 message
result = guard.verify_iso20022_xml(
    xml_string=llm_generated_xml,
    msg_type=MessageType.PACS_008
)
# result.valid = True/False with detailed errors

# Verify IBAN checksum
iban_result = guard.verify_iban(
    iban="DE89370400440532013000",
    llm_says_valid=True
)
# Uses MOD 97 checksum - 100% deterministic
```

**Supports:**
- ISO 20022: pacs.008, pacs.002, camt.053, camt.054, pain.001
- SWIFT MT: MT103, MT202, MT940, MT950
- BIC/IBAN validation with MOD 97 checksum

### 5. Query Guard (SQL Safety)
**Prevent LLM-generated SQL from mutating data or accessing restricted tables.**

```python
from qwed_finance import QueryGuard

guard = QueryGuard(allowed_tables={"accounts", "transactions"})

# Verify query is read-only
result = guard.verify_readonly_safety(
    sql_query="SELECT * FROM accounts WHERE balance > 10000"
)
# result.safe = True ✅

# Block mutation attempts
result = guard.verify_readonly_safety(
    sql_query="DROP TABLE accounts;"  # LLM hallucinated this
)
# result.safe = False, result.risk_level = CRITICAL ❌
```

**Prevents:**
- DELETE, UPDATE, INSERT, DROP statements
- Unauthorized table access
- PII column exposure (SSN, passwords)
- SQL injection patterns

### 6. Cross Guard (Multi-Layer Verification)
**Combine multiple guards for comprehensive verification.**

```python
from qwed_finance import CrossGuard

guard = CrossGuard()

# SWIFT message + Sanctions check
result = guard.verify_swift_with_sanctions(
    mt_string=llm_mt103_message,
    sanctions_list=["SANCTIONED CORP", "BLOCKED ENTITY"]
)
# Validates MT format AND scans for sanctioned entities

# SQL + PII protection
result = guard.verify_query_with_pii_protection(
    sql_query="SELECT * FROM customers",
    allowed_tables=["customers", "orders"],
    pii_columns=["ssn", "password", "credit_card"]
)
```

---

## 🚀 Quick Start

### Installation

```bash
pip install qwed-finance
```

### Usage

```python
from qwed_finance import FinanceVerifier

verifier = FinanceVerifier()

# Verify NPV calculation
result = verifier.verify_npv(
    cashflows=[-1000, 300, 400, 400, 300],
    rate=0.10,
    llm_output="$180.42"
)

if result.verified:
    print(f"✅ Correct: {result.computed_value}")
else:
    print(f"❌ Wrong: LLM said {result.llm_value}, actual is {result.computed_value}")
```

---

## 📊 Supported Verifications

### 1. Time Value of Money

```python
# Net Present Value
verifier.verify_npv(cashflows, rate, llm_output)

# Internal Rate of Return
verifier.verify_irr(cashflows, llm_output)

# Future Value
verifier.verify_fv(principal, rate, periods, llm_output)

# Present Value
verifier.verify_pv(future_value, rate, periods, llm_output)
```

### 2. Loan Calculations

```python
# Monthly Payment
verifier.verify_monthly_payment(principal, annual_rate, months, llm_output)

# Amortization Schedule
verifier.verify_amortization_schedule(principal, rate, months, llm_schedule)

# Total Interest Paid
verifier.verify_total_interest(principal, rate, months, llm_output)
```

### 3. Interest Calculations

```python
# Compound Interest
verifier.verify_compound_interest(
    principal=10000,
    rate=0.05,
    periods=10,
    compounding="annual",  # "monthly", "quarterly", "daily"
    llm_output="$16,288.95"
)

# Simple Interest
verifier.verify_simple_interest(principal, rate, time, llm_output)
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│              YOUR APPLICATION                    │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│              QWED-FINANCE                        │
│  ┌─────────────┐  ┌─────────────┐               │
│  │   Finance   │  │   Banking   │               │
│  │  Verifier   │  │   Schemas   │               │
│  └─────────────┘  └─────────────┘               │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│           QWED-VERIFICATION (Core)               │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐         │
│  │  Math   │  │  Logic  │  │ Schema  │         │
│  │ (SymPy) │  │  (Z3)   │  │ (JSON)  │         │
│  └─────────┘  └─────────┘  └─────────┘         │
└─────────────────────────────────────────────────┘
```

---

## 🔒 Why Deterministic?

Financial calculations must be **exact**. AI hallucinations in banking can cause:

- 💸 Wrong loan payments
- 📉 Incorrect investment projections
- ⚖️ Regulatory violations
- 🏦 Customer trust issues

QWED-Finance uses **SymPy** (symbolic math) instead of floating-point arithmetic, ensuring:

```python
# Floating-point problem
>>> 0.1 + 0.2
0.30000000000000004

# QWED-Finance (SymPy)
>>> verifier.add_money("$0.10", "$0.20")
"$0.30"  # Exact!
```

---

## 🔒 Security & Privacy

> **Your financial data never leaves your machine.**

| Concern | QWED-Finance Approach |
|---------|----------------------|
| **Data Transmission** | ❌ No API calls, no cloud processing |
| **Storage** | ❌ Nothing stored, pure computation |
| **Dependencies** | ✅ Local-only (SymPy, Z3, SQLGlot) |
| **Audit Trail** | ✅ Cryptographic receipts, fully reproducible |

**Perfect for:**
- Banks with strict data residency requirements
- Transactions containing PII (SSN, account numbers)
- SOC 2 / PCI-DSS compliant environments
- Air-gapped trading systems

---

## ❓ FAQ

<details>
<summary><b>Is QWED-Finance free?</b></summary>

Yes! QWED-Finance is open source under the Apache 2.0 license. Use it in commercial fintech products, modify it, distribute it - no restrictions.
</details>

<details>
<summary><b>Does it handle floating-point precision issues?</b></summary>

Yes! QWED-Finance uses SymPy for symbolic mathematics, avoiding the classic `0.1 + 0.2 = 0.30000000000000004` problem. All monetary calculations are exact.
</details>

<details>
<summary><b>Can it verify Black-Scholes calculations?</b></summary>

Yes! The DerivativesGuard includes full Black-Scholes implementation with Greeks (delta, gamma, theta, vega, rho). All calculations use symbolic math for precision.
</details>

<details>
<summary><b>Does it support ISO 20022?</b></summary>

Yes! MessageGuard validates ISO 20022 XML messages (pacs.008, camt.053, pain.001) and legacy SWIFT MT formats (MT103, MT202, MT940).
</details>

<details>
<summary><b>Can I use it to prevent SQL injection in AI agents?</b></summary>

Yes! QueryGuard uses SQLGlot for AST-based analysis. It can block mutations, restrict table access, and prevent PII column exposure - all deterministically.
</details>

<details>
<summary><b>How fast is verification?</b></summary>

Typically <5ms for simple calculations, <50ms for complex derivatives pricing. The symbolic engine is highly optimized.
</details>

---

## 🗺️ Roadmap

### ✅ Released (v1.0.0)
- [x] FinanceVerifier: NPV, IRR, FV, PV calculations
- [x] ComplianceGuard: KYC/AML verification (Z3)
- [x] CalendarGuard: Day count conventions
- [x] DerivativesGuard: Black-Scholes, Greeks
- [x] MessageGuard: ISO 20022, SWIFT MT, IBAN/BIC
- [x] QueryGuard: SQL safety, PII protection
- [x] CrossGuard: Multi-layer verification
- [x] Verification Receipts with audit trail
- [x] TypeScript/npm SDK (@qwed-ai/finance)

### 🚧 In Progress
- [ ] Bond pricing verification (yield to maturity)
- [ ] FX forward rate calculations
- [ ] More regulatory frameworks (MiFID II, Basel III)

### 🔮 Planned
- [ ] Portfolio risk verification (VaR, CVaR)
- [ ] Credit risk models (PD, LGD, EAD)
- [ ] Real-time market data validation
- [ ] Integration with OpenBB Terminal
- [ ] VS Code extension for trading desk

---

## 📦 Related Packages

| Package | Description |
|---------|-------------|
| [qwed-verification](https://github.com/QWED-AI/qwed-verification) | Core verification engine |
| [qwed-ucp](https://github.com/QWED-AI/qwed-ucp) | E-commerce verification |
| [qwed-mcp](https://github.com/QWED-AI/qwed-mcp) | Claude Desktop integration |
---

## 🤖 GitHub Action for CI/CD

Automatically verify your banking AI agents in your CI/CD pipeline!

### Quick Setup

1. Create `.github/workflows/qwed-verify.yml` in your repo:

```yaml
name: QWED Finance Verification

on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: QWED-AI/qwed-finance@v1.1.1
        with:
          test-script: tests/verify_agent.py
```

2. Create your verification script `tests/verify_agent.py`:

```python
from qwed_finance import ComplianceGuard, OpenResponsesIntegration

def test_aml_compliance():
    guard = ComplianceGuard()
    result = guard.verify_aml_flag(
        amount=15000,
        country_code="US",
        llm_flagged=True
    )
    assert result.compliant, f"AML check failed!"
    print("✅ Verification passed!")

if __name__ == "__main__":
    test_aml_compliance()
```

3. Commit and push - the action runs automatically! 🚀

### Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `test-script` | ✅ | - | Path to your Python test script |
| `python-version` | ❌ | `3.11` | Python version to use |
| `fail-on-violation` | ❌ | `true` | Fail workflow on verification failure |

### Blocking Merges

To block PRs that fail verification, add this to your branch protection rules:
- Settings → Branches → Add Rule
- Check "Require status checks to pass"
- Select "verify" job

---

## 🏅 Add "Verified by QWED" Badge

Show that your project uses QWED verification! Copy this to your README:

```markdown
[![Verified by QWED](https://img.shields.io/badge/Verified_by-QWED-00C853?style=flat&logo=checkmarx)](https://github.com/QWED-AI/qwed-finance)
```

**Preview:**

[![Verified by QWED](https://img.shields.io/badge/Verified_by-QWED-00C853?style=flat&logo=checkmarx)](https://github.com/QWED-AI/qwed-finance)

---

## 📄 License

Apache 2.0 - See [LICENSE](LICENSE)

---

## 🤝 Contributing

Contributions welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

---

<div align="center">

**Built with ❤️ by [QWED-AI](https://github.com/QWED-AI)**

[![Twitter](https://img.shields.io/badge/Twitter-@rahuldass29-1DA1F2?style=flat&logo=twitter)](https://x.com/rahuldass29)

</div>
