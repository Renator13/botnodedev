#!/bin/bash

# BotNode / OpenClaw Log Hygiene Script
# Goal: Auto-purge old prompt/response logs to reduce privacy exposure.

OPENCLAW_DIR="$HOME/.openclaw"
LOG_DIR="$OPENCLAW_DIR/logs"
COMPLETIONS_DIR="$OPENCLAW_DIR/completions"
SESSIONS_DIR="$OPENCLAW_DIR/agents/main/agent/sessions"

DAYS_PROMPTS=7     # Prompt/response logs older than 7 days
DAYS_SESSIONS=30   # Conversation sessions older than 30 days (more conservative)

echo "🧹 Starting log cleanup..."

# 1. Security / model logs (JSONL)
if [ -d "$LOG_DIR" ]; then
  find "$LOG_DIR" -type f -name "*.jsonl" -mtime +$DAYS_PROMPTS -print -delete
fi

# 2. Raw completions logs (if enabled)
if [ -d "$COMPLETIONS_DIR" ]; then
  find "$COMPLETIONS_DIR" -type f -name "*.jsonl" -mtime +$DAYS_PROMPTS -print -delete
fi

# 3. Session transcripts (long-term conversations)
if [ -d "$SESSIONS_DIR" ]; then
  find "$SESSIONS_DIR" -type f -name "*.jsonl" -mtime +$DAYS_SESSIONS -print -delete
fi

echo "✅ Log cleanup complete."
