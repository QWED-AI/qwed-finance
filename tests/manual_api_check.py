import os
from openai import AzureOpenAI

# Credentials provided by user
endpoint = "https://lynar.cognitiveservices.azure.com/"
deployment = "lynaredge"
endpoint = "https://lynar.cognitiveservices.azure.com/"
deployment = "lynaredge"
subscription_key = os.getenv("AZURE_OPENAI_KEY") # Sanitize
api_version = "2024-12-01-preview"

print(f"Connecting to Azure OpenAI Endpoint: {endpoint}")
print(f"Deployment: {deployment}")

try:
    client = AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=subscription_key,
    )

    print("Sending request...")
    response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant.",
            },
            {
                "role": "user",
                "content": "Hello, are you online? Reply with 'Yes, I am online and ready to verify.'",
            }
        ],
        max_completion_tokens=100,
        temperature=0.7,
        model=deployment
    )

    print("Response received:")
    print(response.choices[0].message.content)
    print("\n✅ API Verification SUCCESS")

except Exception as e:
    print(f"\n❌ API Verification FAILED")
    print(f"Error: {str(e)}")
