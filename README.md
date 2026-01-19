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

## 🛡️ The Three Guards

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
