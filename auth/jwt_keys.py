"""Load RSA key-pair from environment variables at import time.

File-system persistence of private keys is **structurally disabled** by
design.  If either ``BOTNODE_JWT_PRIVATE_KEY`` or ``BOTNODE_JWT_PUBLIC_KEY``
is missing the process exits immediately to prevent the API from starting
in an insecure state.
"""

import logging
import os
import sys

logger = logging.getLogger("botnode.auth")

BOTNODE_JWT_PRIVATE_KEY: str | None = os.environ.get("BOTNODE_JWT_PRIVATE_KEY")
BOTNODE_JWT_PUBLIC_KEY: str | None = os.environ.get("BOTNODE_JWT_PUBLIC_KEY")

if not BOTNODE_JWT_PRIVATE_KEY or not BOTNODE_JWT_PUBLIC_KEY:
    logger.critical("BOTNODE_JWT RSA keys not found in environment — aborting.")
    sys.exit(1)
