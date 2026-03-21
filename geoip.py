"""GeoIP country resolution — enriches node registration with country code.

Uses MaxMind GeoLite2-Country database. Returns (country_code, country_name)
or (None, None) for private/unresolvable IPs. Never raises.
"""

import os
import logging

logger = logging.getLogger("botnode.geoip")

_reader = None
_loaded = False


def _get_reader():
    global _reader, _loaded
    if _loaded:
        return _reader
    _loaded = True
    db_path = os.getenv("GEOIP_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "GeoLite2-Country.mmdb"))
    try:
        import geoip2.database
        _reader = geoip2.database.Reader(db_path)
        logger.info(f"GeoIP database loaded: {db_path}")
    except Exception as e:
        logger.warning(f"GeoIP database not available ({e}) — country resolution disabled")
        _reader = None
    return _reader


def resolve_country(ip: str) -> tuple:
    """Resolve an IP address to (country_code, country_name). Never raises."""
    if not ip or ip in ("127.0.0.1", "::1", "localhost", "testclient"):
        return (None, None)
    reader = _get_reader()
    if not reader:
        return (None, None)
    try:
        resp = reader.country(ip)
        return (resp.country.iso_code, resp.country.name)
    except Exception:
        return (None, None)
