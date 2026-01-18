"""
Banking Agent Example - Complete agentic loop with QWED verification

This example shows how to build a banking agent that:
1. Accepts user queries about loans, investments, and payments
2. Uses LLM (OpenAI) to process requests
3. Intercepts all tool calls through QWED verification
4. Returns verified results with audit receipts

Compatible with:
- OpenAI API (gpt-4, gpt-4o)
- LangChain agents
- CrewAI agents
- Any agentic framework using function calling
"""

import os
import json
from typing import Optional

# Check for OpenAI availability
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("Note: `openai` package not installed. Using mock mode.")

from qwed_finance import (
    OpenResponsesIntegration,
    UCPIntegration
)


class BankingAgent:
    """
    A banking agent that uses QWED for verified financial calculations.
    
    All LLM-generated financial data is verified before returning to the user.
    """
    
    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize the banking agent.
        
        Args:
            openai_api_key: OpenAI API key. If None, uses OPENAI_API_KEY env var.
        """
        self.api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        
        # Initialize QWED integrations
        self.qwed = OpenResponsesIntegration()
        self.ucp = UCPIntegration(max_transaction_amount=500000)
        
        # Get verified tools schema
        self.tools = self.qwed.get_tools_schema()
        
        # Initialize OpenAI client if available
        if OPENAI_AVAILABLE and self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        else:
            self.client = None
    
    def chat(self, user_message: str) -> dict:
        """
        Process a user message through the banking agent.
        
        Args:
            user_message: User's question about loans, investments, etc.
            
        Returns:
            Response with verified results
        """
        if not self.client:
            return self._mock_response(user_message)
        
        # Step 1: Send to LLM with QWED-verified tools
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a helpful banking assistant. You have access to 
                    verified financial calculation tools. Always use the appropriate tool 
                    for calculations - never estimate financial values manually.
                    
                    Available tools:
                    - calculate_npv: Calculate Net Present Value
                    - calculate_loan_payment: Calculate monthly loan payment
                    - check_aml_compliance: Check if transaction needs AML flagging
                    - price_option: Calculate Black-Scholes option price
                    """
                },
                {"role": "user", "content": user_message}
            ],
            tools=self.tools,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        
        # Step 2: If LLM made tool calls, verify them with QWED
        if message.tool_calls:
            tool_results = []
            
            for tool_call in message.tool_calls:
                # QWED intercepts and verifies the tool call
                verified_result = self.qwed.handle_tool_call(
                    tool_name=tool_call.function.name,
                    arguments=tool_call.function.arguments
                )
                
                # Format as Open Responses Item
                item = self.qwed.format_as_item(
                    verified_result,
                    tool_call_id=tool_call.id
                )
                
                tool_results.append({
                    "tool_call": tool_call.function.name,
                    "verified_result": verified_result.result,
                    "receipt_id": verified_result.receipt.receipt_id if verified_result.receipt else None,
                    "verification": {
                        "verified": verified_result.receipt.verified if verified_result.receipt else False,
                        "engine": verified_result.receipt.engine_used.value if verified_result.receipt else None,
                        "input_hash": verified_result.receipt.input_hash if verified_result.receipt else None
                    }
                })
            
            return {
                "response": "Calculation completed and verified.",
                "tool_results": tool_results,
                "verification_summary": self.qwed.audit_log.summary()
            }
        
        # No tool calls - return direct response
        return {
            "response": message.content,
            "tool_results": [],
            "verification_summary": None
        }
    
    def _mock_response(self, user_message: str) -> dict:
        """Mock response for demo without API key"""
        # Detect intent and use QWED directly
        user_lower = user_message.lower()
        
        if "loan" in user_lower and ("payment" in user_lower or "monthly" in user_lower):
            # Extract numbers (simplified)
            import re
            numbers = re.findall(r'[\d,]+', user_message)
            if len(numbers) >= 2:
                principal = float(numbers[0].replace(',', ''))
                # Assume 6% rate and 360 months if not specified
                result = self.qwed.handle_tool_call(
                    "calculate_loan_payment",
                    {"principal": principal, "annual_rate": 0.06, "months": 360}
                )
                return {
                    "response": f"Monthly payment for ${principal:,.0f} loan: {result.result['monthly_payment']}",
                    "tool_results": [{
                        "tool_call": "calculate_loan_payment",
                        "verified_result": result.result,
                        "receipt_id": result.receipt.receipt_id,
                        "verification": {
                            "verified": True,
                            "engine": result.receipt.engine_used.value,
                            "input_hash": result.receipt.input_hash
                        }
                    }],
                    "verification_summary": self.qwed.audit_log.summary()
                }
        
        elif "npv" in user_lower:
            result = self.qwed.handle_tool_call(
                "calculate_npv",
                {"cashflows": [-100000, 30000, 40000, 40000, 30000], "rate": 0.1}
            )
            return {
                "response": f"NPV calculated: {result.result['npv']}",
                "tool_results": [{
                    "tool_call": "calculate_npv",
                    "verified_result": result.result,
                    "receipt_id": result.receipt.receipt_id
                }],
                "verification_summary": self.qwed.audit_log.summary()
            }
        
        return {
            "response": "I can help with loan payments, NPV calculations, AML checks, and option pricing. What would you like to calculate?",
            "tool_results": [],
            "verification_summary": None
        }


def main():
    """Demo the banking agent"""
    print("=" * 60)
    print("QWED Banking Agent Demo")
    print("=" * 60)
    print()
    
    agent = BankingAgent()
    
    # Example queries
    queries = [
        "What's the monthly payment for a $500,000 loan?",
        "Calculate the NPV of my investment"
    ]
    
    for query in queries:
        print(f"User: {query}")
        print("-" * 40)
        
        result = agent.chat(query)
        
        print(f"Agent: {result['response']}")
        
        if result['tool_results']:
            for tr in result['tool_results']:
                print(f"\n  📊 Tool: {tr['tool_call']}")
                print(f"  ✅ Verified Result: {tr['verified_result']}")
                print(f"  🔐 Receipt ID: {tr['receipt_id']}")
                if 'verification' in tr:
                    print(f"  🔧 Engine: {tr['verification'].get('engine')}")
                    print(f"  #️⃣ Hash: {tr['verification'].get('input_hash', '')[:16]}...")
        
        print()
        print("=" * 60)
        print()


if __name__ == "__main__":
    main()
