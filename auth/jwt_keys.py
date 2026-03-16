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

_raw_private = os.environ.get("BOTNODE_JWT_PRIVATE_KEY", "")
_raw_public = os.environ.get("BOTNODE_JWT_PUBLIC_KEY", "")

# Support single-line PEM with | as newline separator (for .env files)
BOTNODE_JWT_PRIVATE_KEY: str | None = _raw_private.replace("|", "\n") if _raw_private else None
BOTNODE_JWT_PUBLIC_KEY: str | None = _raw_public.replace("|", "\n") if _raw_public else None

if not BOTNODE_JWT_PRIVATE_KEY or not BOTNODE_JWT_PUBLIC_KEY:
    logger.critical("BOTNODE_JWT RSA keys not found in environment — aborting.")
    sys.exit(1)
