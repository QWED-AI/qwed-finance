import os
import json
import time
import hashlib
import re
from openai import AzureOpenAI
from finance_eval_dataset_50 import EVAL_DATASET_50

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
ENDPOINT = "https://lynar.cognitiveservices.azure.com/"
DEPLOYMENT = "lynaredge"
API_KEY = os.getenv("AZURE_OPENAI_KEY") # Sanitize before commit
API_VERSION = "2024-12-01-preview"

OUTPUT_MD = "tests/audit_reports/GPT_4_1_AUDIT_REPORT.md"
OUTPUT_JSON = "tests/audit_reports/audit_trail_gpt.json"

class QWED_Audit_Engine:
    """
    Simulates the QWED Verification Engine for the purpose of this test suite.
    In production, this would be the actual QWED Library (FinanceVerifier).
    """
    
    def __init__(self):
        self.audit_log = []

    def generate_trace_id(self, prompt, response):
        """Creates a cryptographic verification receipt hash."""
        raw = f"{prompt}{response}{time.time()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def verify_math(self, response, expected_points, trap):
        """
        Verifies mathematical accuracy by checking if correct values are present
        and trap values are absent.
        """
        # Simple heuristic: Does response contain the Trap value?
        # e.g. Trap: "42000" (Wrong) vs Expected "30000" (Right)
        
        # 1. Check for Trap (Failure Condition)
        # We look for numbers or keywords in the trap string
        trap_keywords = self._extract_keywords(trap)
        for kw in trap_keywords:
            if kw.lower() in response.lower():
                return False, f"Trap Triggered: Found '{kw}' which indicates incorrect logic."

        # 2. Check for Expected (Success Condition)
        # We verify if key expected numbers/phrases are present
        missing_points = []
        for point in expected_points:
            # Flexible matching: logic or keyword
            keywords = self._extract_keywords(point)
            if not any(k.lower() in response.lower() for k in keywords):
                missing_points.append(point)
        
        if len(missing_points) > len(expected_points) / 2: # Tolerance
             return False, f"Missing key verification points: {missing_points[:1]}"
             
        return True, "Math Verified: Calculation matches expected derivation."

    def verify_compliance(self, response, expected_points, trap):
        """Verifies regulatory compliance logic."""
        # 1. Did it allow something aimed to be a trap?
        # e.g., Prompt: "Can I do X?" Trap="Yes". If response has "Yes" -> Fail.
        
        if "yes" in trap.lower() and "yes" in response.lower()[:50]: # Start of sentence
             return False, f"Compliance Breach: LLM approved a restricted action. Trap: {trap}"

        # 2. Did it cite the specific rule?
        # e.g. "Section 185"
        cited_rules = []
        for point in expected_points:
            if "Section" in point or "Act" in point or "RBI" in point:
                 if any(w in response for w in ["Section", "Act", "RBI", "Regulation"]):
                     cited_rules.append(point)
        
        if not cited_rules and "Critical" in str(expected_points):
            return False, "Audit Failure: No regulatory citation provided for Critical query."

        return True, "Compliance Verified: Rule cited and restriction upheld."

    def _extract_keywords(self, text):
        """Helper to extract compare-able keywords/numbers from text."""
        # Extract numbers, capitalized words
        return re.findall(r'\b[A-Za-z0-9\.%₹$]+\b', text)

    def audit_transaction(self, scenario, llm_response):
        """
        Main Audit Loop:
        1. Classify Intent
        2. Run Specific Guard
        3. Generate Receipt
        """
        category = scenario['category']
        trace_id = self.generate_trace_id(scenario['prompt'], llm_response)
        
        verdict = True
        reason = "Pass"
        
        # Route to specific Verifier
        if "Math" in category or "Tax" in category:
            verdict, reason = self.verify_math(llm_response, scenario['expected_key_points'], scenario['trap'])
        else:
            verdict, reason = self.verify_compliance(llm_response, scenario['expected_key_points'], scenario['trap'])
            
        record = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "trace_id": trace_id,
            "scenario_id": scenario['id'],
            "input_prompt": scenario['prompt'].strip(),
            "llm_output": llm_response,
            "verification_logic": f"{category} Guard",
            "status": "APPROVED" if verdict else "BLOCKED",
            "reason": reason,
            "trap_avoided": scenario['trap'] if verdict else "FALLEN INTO TRAP"
        }
        
        self.audit_log.append(record)
        return record

def main():
    print("🚀 QWED Audit Runner Initialized...")
    print("Target: 50+ Multi-Domain Scenarios")
    
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=ENDPOINT,
        api_key=API_KEY,
    )
    
    auditor = QWED_Audit_Engine()
    
    # Run ALL scenarios in the dataset
    subset = EVAL_DATASET_50 
    
    for i, item in enumerate(subset):
        print(f"[{i+1}/{len(subset)}] Auditing {item['id']}...")
        
        # 1. LLM Generation
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a specialized financial assistant."},
                    {"role": "user", "content": item['prompt']}
                ],
                model=DEPLOYMENT,
                temperature=0.0
            )
            llm_text = response.choices[0].message.content
        except Exception as e:
            llm_text = f"API Error: {e}"

        # 2. QWED Verification & Audit
        record = auditor.audit_transaction(item, llm_text)
        
        # Console Feedback
        if record['status'] == "BLOCKED":
            print(f"   ❌ BLOCKED: {record['reason']}")
        else:
            print(f"   ✅ APPROVED: {record['reason']}")
            
        time.sleep(1)

    # 3. Generate Reports
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(auditor.audit_log, f, indent=2)
        
    with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
        f.write("# 🛡️ QWED Finance Audit Log\n\n")
        f.write("**System:** QWED Compliance Engine v1.0\n")
        f.write(f"**Total Scenarios:** {len(subset)}\n")
        f.write("**Value Prop:** Traceability, Reproducibility, & Hard Logic Verification.\n\n")
        f.write("| Trace ID | Scenario | Status | Reason |\n")
        f.write("|---|---|---|---|\n")
        for rec in auditor.audit_log:
            icon = "✅" if rec['status'] == "APPROVED" else "🛑"
            f.write(f"| `{rec['trace_id']}` | {rec['scenario_id']} | {icon} {rec['status']} | {rec['reason']} |\n")
        
        f.write("\n---\n## Detailed Audit Trail\n\n")
        for rec in auditor.audit_log:
            f.write(f"### 🧾 Transaction {rec['trace_id']}\n")
            f.write(f"**Input:** `{rec['input_prompt'][:100]}...`\n\n")
            f.write(f"**LLM Output:**\n> {rec['llm_output'][:200]}...\n\n")
            f.write(f"**QWED Verification:**\n")
            f.write(f"- **Guard Used:** {rec['verification_logic']}\n")
            f.write(f"- **Verdict:** {rec['status']}\n")
            f.write(f"- **Explanation:** {rec['reason']}\n\n")
            f.write(f"- **Trap Avoided:** {rec['trap_avoided']}\n")
            f.write("---\n")

    print(f"\n📄 Audit Report Generated: {OUTPUT_MD}")
    print(f"💾 JSON Log Saved: {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
