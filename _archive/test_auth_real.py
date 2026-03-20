import os
import sys
from dotenv import load_dotenv

# Load the real .env file BEFORE importing auth modules
env_path = "/home/ubuntu/.openclaw/.env"
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    print(f"⚠️  .env file not found at {env_path}")

from auth.jwt_tokens import issue_access_token, verify_access_token

def test_auth():
    print("🧪 Testing BotNode Python JWT Auth (RS256)...")
    
    # 1. Issue Token
    try:
        token = issue_access_token("genesis-01", "owner")
        print(f"✅ Issued Token: {token[:20]}...")
        
        # 2. Verify Token
        decoded = verify_access_token(token)
        if "error" in decoded:
            print(f"❌ Verification failed: {decoded['error']}")
        else:
            print(f"✅ Verification Success! Node: {decoded['sub']}, Role: {decoded['role']}")
            
    except Exception as e:
        print(f"❌ Test Failed: {str(e)}")

if __name__ == "__main__":
    test_auth()
