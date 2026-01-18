from qwed_finance import ComplianceGuard

def test_aml_compliance():
    guard = ComplianceGuard()
    result = guard.verify_aml_flag(
        amount=15000,
        country_code="US",
        llm_flagged=True
    )
    print("✅ AML verification passed!" if result.compliant else "❌ Failed")

if __name__ == "__main__":
    test_aml_compliance()
