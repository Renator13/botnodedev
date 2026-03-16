import os
import sys

# Load RSA keys from environment variables (Ephemerally)
# File-system persistence of private keys is structurally disabled.

BOTNODE_JWT_PRIVATE_KEY = os.environ.get("BOTNODE_JWT_PRIVATE_KEY")
BOTNODE_JWT_PUBLIC_KEY = os.environ.get("BOTNODE_JWT_PUBLIC_KEY")

if not BOTNODE_JWT_PRIVATE_KEY or not BOTNODE_JWT_PUBLIC_KEY:
    print("CRITICAL SECURITY ERROR: BOTNODE_JWT RSA keys not found in environment.")
    sys.exit(1)
