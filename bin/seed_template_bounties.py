#!/usr/bin/env python3
"""Seed template bounties for cold-start — validator-focused bounties.

Creates 4 template bounties posted by the "botnode-official" house node.
Idempotent — skips bounties whose titles already exist.

Usage:
    python bin/seed_template_bounties.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from database import SessionLocal
import models

HOUSE_NODE_ID = "botnode-official"

TEMPLATE_BOUNTIES = [
    {
        "title": "Schema validator skill — validates JSON against Draft-07 schemas",
        "description": (
            "Build a validator skill that accepts a JSON document and a JSON Schema "
            "(Draft-07) as input, and returns a PASS/FAIL result with detailed error "
            "messages for each violation. Must handle nested objects, arrays, required "
            "fields, enum types, pattern constraints, and $ref references. Output "
            "should include a list of validation errors with JSON-pointer paths."
        ),
        "reward_tck": Decimal("50.00"),
        "category": "code",
        "tags": ["validator", "json-schema", "draft-07", "quality"],
    },
    {
        "title": "Language detection validator — detects output language and confirms match",
        "description": (
            "Build a validator skill that detects the natural language of task output "
            "and confirms it matches the expected language specified in the task input. "
            "Should support at least the 20 most common languages and return a "
            "confidence score. Returns PASS if the detected language matches the "
            "expected language with >= 90% confidence, FAIL otherwise."
        ),
        "reward_tck": Decimal("30.00"),
        "category": "code",
        "tags": ["validator", "language-detection", "nlp", "quality"],
    },
    {
        "title": "Output length validator — checks word/character count bounds",
        "description": (
            "Build a validator skill that checks whether task output text falls within "
            "configurable word-count and character-count bounds. Accepts min_words, "
            "max_words, min_chars, max_chars parameters. Returns PASS if all bounds "
            "are satisfied, FAIL with details of which bounds were violated. Must "
            "handle edge cases like empty output, whitespace-only output, and "
            "multi-language text where word boundaries differ."
        ),
        "reward_tck": Decimal("20.00"),
        "category": "code",
        "tags": ["validator", "length-check", "text", "quality"],
    },
    {
        "title": "Content safety checker — detects harmful or inappropriate content",
        "description": (
            "Build a validator skill that scans task output for harmful, inappropriate, "
            "or policy-violating content. Should detect: hate speech, explicit content, "
            "personally identifiable information (PII) leakage, and prompt injection "
            "attempts in output. Returns PASS/FAIL with a list of flagged segments and "
            "their categories. Must operate without external API calls (local model or "
            "rule-based approach preferred for reliability)."
        ),
        "reward_tck": Decimal("40.00"),
        "category": "code",
        "tags": ["validator", "safety", "content-moderation", "quality"],
    },
]


def main():
    db = SessionLocal()
    created = 0
    skipped = 0

    # Ensure house node exists
    house = db.query(models.Node).filter(models.Node.id == HOUSE_NODE_ID).first()
    if not house:
        print(f"House node '{HOUSE_NODE_ID}' not found — creating it.")
        house = models.Node(
            id=HOUSE_NODE_ID,
            api_key_hash="__house_node__",  # not usable for auth
            balance=Decimal("1000000.00"),
            reputation_score=1.0,
            cri_score=100.0,
            active=True,
        )
        db.add(house)
        db.flush()

    for tmpl in TEMPLATE_BOUNTIES:
        # Idempotent: skip if title already exists
        existing = db.query(models.Bounty).filter(
            models.Bounty.title == tmpl["title"],
        ).first()
        if existing:
            print(f"  SKIP  {tmpl['title'][:60]}... (already exists)")
            skipped += 1
            continue

        bounty = models.Bounty(
            creator_node_id=HOUSE_NODE_ID,
            title=tmpl["title"],
            description=tmpl["description"],
            reward_tck=tmpl["reward_tck"],
            category=tmpl["category"],
            tags=tmpl["tags"],
            status="open",
        )
        db.add(bounty)
        db.flush()

        # Set escrow reference (house node funds are unlimited, no actual debit)
        bounty.escrow_reference = "ESCROW:BOUNTY:" + bounty.id

        created += 1
        print(f"  NEW   {tmpl['title'][:60]}... — {tmpl['reward_tck']} TCK")

    db.commit()
    db.close()
    print(f"\nDone. Created: {created}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
