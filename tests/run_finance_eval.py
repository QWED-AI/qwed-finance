import os
import json
import time
from openai import AzureOpenAI
from finance_eval_dataset import EVAL_DATASET

# --- CONFIGURATION (User provided) ---
ENDPOINT = "https://lynar.cognitiveservices.azure.com/"
DEPLOYMENT = "lynaredge"
API_KEY = os.getenv("AZURE_OPENAI_KEY") # Sanitize
API_VERSION = "2024-12-01-preview"

OUTPUT_FILE = "FINANCE_EVALUATION_REPORT.md"

def get_llm_response(client, prompt, system_prompt="You are a helpful financial assistant."):
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            model=DEPLOYMENT,
            temperature=0.0, # Deterministic settings
            max_completion_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"

def generate_report(results):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# 🏦 QWED Finance Evaluation Report\n\n")
        f.write("**Objective:** Evaluate LLM performance on High-Difficulty Financial Compliance & Math scenarios.\n")
        f.write("**Model:** Azure OpenAI (gpt-4.1 / lynaredge)\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("---\n\n")
        
        for res in results:
            f.write(f"## 🆔 {res['id']} ({res['category']})\n\n")
            f.write(f"**Difficulty:** {res['difficulty']}\n\n")
            f.write(f"### 📝 Scenario\n> {res['prompt'].strip()}\n\n")
            f.write(f"### 🤖 LLM Response\n{res['response']}\n\n")
            f.write(f"### 🦁 Verification (Gold Standard)\n")
            f.write("**Expected Key Points:**\n")
            for point in res['expected']:
                f.write(f"- {point}\n")
            f.write(f"\n**⚠️ TRAP WARNING:** {res['trap']}\n")
            f.write("\n---\n\n")

def main():
    print("🚀 Starting QWED Finance Evaluation Runner...")
    print(f"Targeting: {ENDPOINT}")
    
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=ENDPOINT,
        api_key=API_KEY,
    )
    
    results = []
    
    for i, item in enumerate(EVAL_DATASET):
        print(f"[{i+1}/{len(EVAL_DATASET)}] Running {item['id']}...")
        
        response = get_llm_response(client, item['prompt'])
        
        results.append({
            "id": item['id'],
            "category": item['category'],
            "difficulty": item['difficulty'],
            "prompt": item['prompt'],
            "response": response,
            "expected": item['expected_key_points'],
            "trap": item['trap']
        })
        
        time.sleep(1) # Avoid rate limits
        
    print("\n✅ Evaluation Complete.")
    generate_report(results)
    print(f"📄 Report generated: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
