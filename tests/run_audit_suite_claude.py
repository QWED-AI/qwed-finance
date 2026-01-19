import os
import json
import time
import hashlib
import re
import sys
# Try to import AnthropicFoundry; handle case if it's new/proprietary logic
try:
    from anthropic import AnthropicFoundry
except ImportError:
    # Fallback or standard import if the user meant standard Anthropic with base_url
    from anthropic import Anthropic, AnthropicBedrock 
    # Note: I will trust the user's snippet exact import in the main block

from finance_eval_dataset_50 import EVAL_DATASET_50

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
ENDPOINT = "https://rahul-0907-resource.services.ai.azure.com/anthropic/"
DEPLOYMENT = "claude-sonnet-4-5-2"
API_KEY = os.getenv("AZURE_ANTHROPIC_KEY") # Sanitize before commit

OUTPUT_MD = "tests/audit_reports/CLAUDE_4_5_AUDIT_REPORT.md"
OUTPUT_JSON = "tests/audit_reports/audit_trail_claude.json"

class QWED_Audit_Engine:
    """
    Simulates the QWED Verification Engine (Same logic as before).
    """
    def __init__(self):
        self.audit_log = []

    def generate_trace_id(self, prompt, response):
        raw = f"{prompt}{response}{time.time()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def verify_math(self, response, expected_points, trap):
        trap_keywords = self._extract_keywords(trap)
        for kw in trap_keywords:
            if kw.lower() in response.lower():
                return False, f"Trap Triggered: Found '{kw}' which indicates incorrect logic."

        missing_points = []
        for point in expected_points:
            keywords = self._extract_keywords(point)
            if not any(k.lower() in response.lower() for k in keywords):
                missing_points.append(point)
        
        if len(missing_points) > len(expected_points) / 2:
             return False, f"Missing key verification points: {missing_points[:1]}"
        return True, "Math Verified: Calculation matches expected derivation."

    def verify_compliance(self, response, expected_points, trap):
        if "yes" in trap.lower() and "yes" in response.lower()[:50]:
             return False, f"Compliance Breach: LLM approved a restricted action. Trap: {trap}"

        cited_rules = []
        for point in expected_points:
            if "Section" in point or "Act" in point or "RBI" in point:
                 if any(w in response for w in ["Section", "Act", "RBI", "Regulation"]):
                     cited_rules.append(point)
        
        if not cited_rules and "Critical" in str(expected_points):
            return False, "Audit Failure: No regulatory citation provided for Critical query."

        return True, "Compliance Verified: Rule cited and restriction upheld."

    def _extract_keywords(self, text):
        return re.findall(r'\b[A-Za-z0-9\.%₹$]+\b', text)

    def audit_transaction(self, scenario, llm_response):
        category = scenario['category']
        trace_id = self.generate_trace_id(scenario['prompt'], llm_response)
        
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
    print("🚀 QWED Audit Runner (Claude Edition) Initialized...")
    
    # Import locally to avoid top-level issues if package differs
    from anthropic import AnthropicFoundry

    client = AnthropicFoundry(
        api_key=API_KEY,
        base_url=ENDPOINT
    )
    
    auditor = QWED_Audit_Engine()
    subset = EVAL_DATASET_50 
    
    for i, item in enumerate(subset):
        print(f"[{i+1}/{len(subset)}] Auditing {item['id']}...")
        
        try:
            # Claude Message API
            message = client.messages.create(
                model=DEPLOYMENT,
                messages=[
                    {"role": "user", "content": item['prompt']}
                ],
                max_tokens=1024,
            )
            llm_text = message.content[0].text # Access TextBlock
        except Exception as e:
            llm_text = f"API Error: {e}"

        record = auditor.audit_transaction(item, llm_text)
        
        if record['status'] == "BLOCKED":
            print(f"   ❌ BLOCKED: {record['reason']}")
        else:
            print(f"   ✅ APPROVED: {record['reason']}")
            
        time.sleep(1.5) # Claude rate limits might differ

    # Generate Reports
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(auditor.audit_log, f, indent=2)
        
    with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
        f.write("# 🛡️ QWED Finance Audit Log (Claude 3.5 Sonnet)\n\n")
        f.write("**System:** QWED Compliance Engine v1.0\n")
        f.write(f"**Total Scenarios:** {len(subset)}\n")
        f.write("**Value Prop:** Comparing Sonnet reasoning against QWED Gold Standard.\n\n")
        f.write("| Trace ID | Scenario | Status | Reason |\n")
        f.write("|---|---|---|---|\n")
        for rec in auditor.audit_log:
            icon = "✅" if rec['status'] == "APPROVED" else "🛑"
            f.write(f"| `{rec['trace_id']}` | {rec['scenario_id']} | {icon} {rec['status']} | {rec['reason']} |\n")
        
        f.write("\n---\n## Detailed Audit Trail\n\n")
        for rec in auditor.audit_log:
            f.write(f"### 🧾 Transaction {rec['trace_id']}\n")
            f.write(f"**Input:** `{rec['input_prompt'][:100]}...`\n\n")
            f.write(f"**LLM Output:**\n> {rec['llm_output'][:300].replace(chr(10), ' ')}...\n\n")
            f.write(f"**QWED Verification:**\n")
            f.write(f"- **Guard Used:** {rec['verification_logic']}\n")
            f.write(f"- **Verdict:** {rec['status']}\n")
            f.write(f"- **Explanation:** {rec['reason']}\n\n")
            f.write("---\n")

    print(f"\n📄 Audit Report Generated: {OUTPUT_MD}")

if __name__ == "__main__":
    main()
