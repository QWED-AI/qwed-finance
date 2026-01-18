# QWED-Finance 🏦

**Deterministic verification middleware for banking and financial AI.**

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
