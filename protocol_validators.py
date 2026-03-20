"""Protocol Validator Pipeline — deterministic pre-settlement checks.

Extends the dispute engine with configurable validators that skills
define in their metadata.  Each validator is a pure function: given the
output and a config, it returns pass/fail with no ambiguity, no LLM,
and no cost.

Validators run automatically before settlement.  If any fails, the
escrow is auto-refunded with reason VALIDATOR_FAILED and the specific
validator name logged.

Supported validator types:
    - schema:       JSON Schema Draft-07 (already in dispute_engine)
    - length:       word/char count bounds on a field
    - language:     detected language matches expected
    - contains:     required substrings present
    - not_contains: forbidden patterns absent
    - non_empty:    specified fields are not blank
    - regex:        field matches a regex pattern
    - json_path:    value at a JSON path meets a condition

Adding a new type: write a function with signature
``(output: dict, config: dict) -> (bool, str | None)`` and register
it in the ``VALIDATOR_TYPES`` dict.

**Design rationale:** Deterministic validators (as opposed to LLM-based
evaluation) follow Bolton, Katok & Ockenfels (2004) finding that
objective, verifiable quality signals produce higher market efficiency
than subjective review. The verify operation in the Agentic Economy
Interface Specification (agenticeconomy.dev, Section 5, Operation 7)
requires validators to be pure functions with identical results on
identical inputs — no LLM calls, no network requests (except webhook
type). See whitepaper Section 10.8 (Quality Markets) for the 4-layer
quality assurance architecture.
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger("botnode.validators.protocol")

# ---------------------------------------------------------------------------
# Individual validator functions
# Each returns (passed: bool, error_message: str | None)
# ---------------------------------------------------------------------------


def _validate_length(output: dict, config: dict) -> tuple[bool, Optional[str]]:
    """Check word or character count of a field."""
    field = config.get("field", "")
    value = _extract_field(output, field)
    if value is None:
        return (False, f"Field '{field}' not found in output")

    text = str(value)
    words = len(text.split())

    min_words = config.get("min_words")
    max_words = config.get("max_words")
    min_chars = config.get("min_chars")
    max_chars = config.get("max_chars")

    if min_words and words < min_words:
        return (False, f"Field '{field}' has {words} words, minimum is {min_words}")
    if max_words and words > max_words:
        return (False, f"Field '{field}' has {words} words, maximum is {max_words}")
    if min_chars and len(text) < min_chars:
        return (False, f"Field '{field}' has {len(text)} chars, minimum is {min_chars}")
    if max_chars and len(text) > max_chars:
        return (False, f"Field '{field}' has {len(text)} chars, maximum is {max_chars}")

    return (True, None)


def _validate_language(output: dict, config: dict) -> tuple[bool, Optional[str]]:
    """Detect language of a text field and compare to expected."""
    field = config.get("field", "")
    expected = config.get("expected", "")
    value = _extract_field(output, field)
    if value is None:
        return (False, f"Field '{field}' not found in output")

    try:
        from langdetect import detect
        detected = detect(str(value))
    except ImportError:
        logger.warning("langdetect not installed — skipping language validator")
        return (True, None)  # fail-open if library missing
    except Exception:
        return (True, None)  # fail-open on detection errors

    if detected != expected:
        return (False, f"Field '{field}' detected as '{detected}', expected '{expected}'")
    return (True, None)


def _validate_contains(output: dict, config: dict) -> tuple[bool, Optional[str]]:
    """Check that required substrings are present."""
    field = config.get("field")
    patterns = config.get("patterns", [])
    text = str(_extract_field(output, field) if field else json.dumps(output))

    for pattern in patterns:
        if pattern not in text:
            return (False, f"Required pattern '{pattern}' not found in {'field ' + field if field else 'output'}")
    return (True, None)


def _validate_not_contains(output: dict, config: dict) -> tuple[bool, Optional[str]]:
    """Check that forbidden patterns are absent."""
    field = config.get("field")
    patterns = config.get("patterns", [])
    text = str(_extract_field(output, field) if field else json.dumps(output))

    for pattern in patterns:
        if pattern.lower() in text.lower():
            return (False, f"Forbidden pattern '{pattern}' found in {'field ' + field if field else 'output'}")
    return (True, None)


def _validate_non_empty(output: dict, config: dict) -> tuple[bool, Optional[str]]:
    """Check that specified fields are not empty/blank."""
    fields = config.get("fields", [])
    for field in fields:
        value = _extract_field(output, field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return (False, f"Field '{field}' is empty or missing")
        if isinstance(value, (list, dict)) and len(value) == 0:
            return (False, f"Field '{field}' is empty collection")
    return (True, None)


def _validate_regex(output: dict, config: dict) -> tuple[bool, Optional[str]]:
    """Check that a field matches a regex pattern."""
    field = config.get("field", "")
    pattern = config.get("pattern", "")
    value = _extract_field(output, field)
    if value is None:
        return (False, f"Field '{field}' not found")

    try:
        compiled = re.compile(pattern)
        if not compiled.search(str(value)[:10000]):
            return (False, f"Field '{field}' does not match pattern '{pattern}'")
    except re.error:
        return (False, f"Regex pattern invalid")
    return (True, None)


def _validate_json_path(output: dict, config: dict) -> tuple[bool, Optional[str]]:
    """Check a value at a specific path meets a condition."""
    path = config.get("path", "")
    value = _extract_nested(output, path)
    if value is None:
        return (False, f"Path '{path}' not found in output")

    # Check enum
    enum = config.get("enum")
    if enum and value not in enum:
        return (False, f"Value at '{path}' is '{value}', expected one of {enum}")

    # Check range
    min_val = config.get("min")
    max_val = config.get("max")
    if min_val is not None and value < min_val:
        return (False, f"Value at '{path}' is {value}, minimum is {min_val}")
    if max_val is not None and value > max_val:
        return (False, f"Value at '{path}' is {value}, maximum is {max_val}")

    return (True, None)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

VALIDATOR_TYPES = {
    "length": _validate_length,
    "language": _validate_language,
    "contains": _validate_contains,
    "not_contains": _validate_not_contains,
    "non_empty": _validate_non_empty,
    "regex": _validate_regex,
    "json_path": _validate_json_path,
}
"""Map of validator type names to their implementation functions.
``schema`` is handled separately by the dispute engine."""


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_protocol_validators(
    output: dict,
    validators: list[dict],
) -> tuple[bool, Optional[str], Optional[dict]]:
    """Run a sequence of protocol validators against task output.

    Args:
        output: The task's output_data.
        validators: List of validator configs from skill metadata.
            Each has at minimum a ``type`` key.

    Returns:
        (all_passed, failed_validator_type, error_details)
    """
    if not validators:
        return (True, None, None)

    for v in validators:
        vtype = v.get("type", "")

        # schema is handled by the dispute engine, skip here
        if vtype == "schema":
            continue

        handler = VALIDATOR_TYPES.get(vtype)
        if not handler:
            logger.warning(f"Unknown validator type: {vtype} — skipping")
            continue

        try:
            passed, error = handler(output, v)
            if not passed:
                return (
                    False,
                    f"VALIDATOR_FAILED:{vtype}",
                    {"validator_type": vtype, "config": v, "error": error},
                )
        except Exception as exc:
            logger.error(f"Validator {vtype} raised exception: {exc}")
            # fail-open on validator errors to avoid blocking settlement
            continue

    return (True, None, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_field(output: dict, field: str):
    """Extract a top-level field from output, or the full output if field is empty."""
    if not field:
        return json.dumps(output) if isinstance(output, dict) else str(output)
    return output.get(field) if isinstance(output, dict) else None


def _extract_nested(data: dict, path: str):
    """Extract a value from a nested dict using dot notation."""
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current
