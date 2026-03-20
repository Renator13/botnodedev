#!/usr/bin/env python3
"""Seed protocol validators for all 29 skills.

Adds validators array to each skill's metadata_json so the dispute
engine can run them before settlement.  Idempotent — safe to run
multiple times.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
import models

# Validator definitions per skill
SKILL_VALIDATORS = {
    # ── Container skills (deterministic) ──────────────────────────
    "csv_parser_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["data"]},
    ],
    "pdf_parser_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["text"]},
        {"type": "length", "field": "text", "min_chars": 10},
    ],
    "url_fetcher_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["content"]},
        {"type": "not_contains", "patterns": ["403 Forbidden", "404 Not Found", "Access Denied"]},
    ],
    "web_scraper_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["content"]},
        {"type": "not_contains", "patterns": ["captcha", "Access Denied", "403 Forbidden"]},
    ],
    "diff_analyzer_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["diff"]},
    ],
    "image_describer_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["description"]},
        {"type": "length", "field": "description", "min_words": 5},
    ],
    "text_to_voice_v1": [
        {"type": "schema"},
    ],
    "schema_enforcer_v1": [
        {"type": "schema"},
    ],
    "notification_router_v1": [
        {"type": "schema"},
    ],

    # ── LLM skills — high exigency ───────────────────────────────
    "code_reviewer_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["issues", "summary"]},
        {"type": "not_contains", "patterns": ["I cannot review", "I'm unable to", "ERROR:"]},
        {"type": "json_path", "path": "overall_quality", "min": 1, "max": 10},
    ],
    "web_research_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["summary", "key_facts"]},
        {"type": "length", "field": "summary", "min_words": 50},
        {"type": "not_contains", "patterns": ["I cannot research", "I don't have access", "ERROR:"]},
    ],
    "hallucination_detector_v1": [
        {"type": "schema"},
        {"type": "json_path", "path": "overall_confidence", "min": 0.0, "max": 1.0},
    ],
    "performance_analyzer_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["issues"]},
        {"type": "not_contains", "patterns": ["I cannot analyze", "ERROR:"]},
    ],
    "prompt_optimizer_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["optimized_prompt"]},
        {"type": "not_contains", "patterns": ["I cannot optimize", "ERROR:"]},
    ],
    "compliance_checker_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["summary"]},
        {"type": "json_path", "path": "risk_level", "enum": ["low", "medium", "high"]},
    ],

    # ── LLM skills — medium exigency ─────────────────────────────
    "text_translator_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["translated_text"]},
        {"type": "length", "field": "translated_text", "min_words": 5},
        {"type": "not_contains", "field": "translated_text", "patterns": ["[UNTRANSLATED]", "I cannot translate", "ERROR:"]},
    ],
    "document_reporter_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["key_findings"]},
        {"type": "length", "field": "key_findings", "min_words": 10},
    ],
    "report_builder_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["report"]},
        {"type": "length", "field": "report", "min_words": 50},
    ],
    "report_compiler_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["compiled_report"]},
        {"type": "length", "field": "compiled_report", "min_words": 30},
    ],
    "schema_generator_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["json_schema"]},
    ],
    "logic_visualizer_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["mermaid"]},
    ],
    "quality_gate_v1": [
        {"type": "schema"},
        {"type": "json_path", "path": "overall_score", "min": 0, "max": 100},
    ],
    "scheduler_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["schedule"]},
    ],
    "google_search_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["results"]},
    ],

    # ── LLM skills — low exigency ────────────────────────────────
    "sentiment_analyzer_v1": [
        {"type": "schema"},
        {"type": "json_path", "path": "sentiment", "enum": ["positive", "negative", "neutral", "mixed"]},
        {"type": "json_path", "path": "confidence", "min": 0.0, "max": 1.0},
    ],
    "key_point_extractor_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["key_points"]},
    ],
    "language_detector_v1": [
        {"type": "schema"},
    ],
    "lead_enricher_v1": [
        {"type": "schema"},
        {"type": "non_empty", "fields": ["enriched_data"]},
    ],
    "vector_memory_v1": [
        {"type": "schema"},
    ],
}


def main():
    db = SessionLocal()
    updated = 0
    skipped = 0

    skills = db.query(models.Skill).all()
    for skill in skills:
        validators = SKILL_VALIDATORS.get(skill.label)
        if not validators:
            skipped += 1
            continue

        metadata = skill.metadata_json or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}

        # Don't overwrite if already has validators
        if metadata.get("validators"):
            print(f"  SKIP {skill.label} — already has validators")
            skipped += 1
            continue

        metadata["validators"] = validators
        skill.metadata_json = metadata
        updated += 1
        print(f"  SET  {skill.label} — {len(validators)} validators")

    db.commit()
    db.close()
    print(f"\nDone. Updated: {updated}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
