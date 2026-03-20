#!/bin/bash
# botnode up — Start a complete local BotNode devnet in one command.
#
# What it does:
#   1. Starts API + PostgreSQL + Redis via Docker Compose
#   2. Waits for health check
#   3. Creates a sandbox buyer + seller
#   4. Publishes a sample skill
#   5. Executes a complete trade (create → complete → settle)
#   6. Prints balances and a "you're ready" message
#
# Usage:
#   ./botnode-up.sh
#
# Requirements:
#   - Docker + Docker Compose
#   - curl
#   - python3 (for JSON parsing)

set -e

API="http://localhost:8000"
CYAN='\033[1;36m'
GREEN='\033[1;32m'
DIM='\033[2m'
RESET='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════╗"
echo "║  botnode up — Local Devnet               ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${RESET}"

# Step 1: Start services
echo -e "${CYAN}[1/6]${RESET} Starting Docker services..."
docker compose up -d 2>&1 | tail -3

# Step 2: Wait for health
echo -e "${CYAN}[2/6]${RESET} Waiting for API..."
for i in $(seq 1 30); do
    if curl -sf "$API/health" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓ API healthy${RESET}"
        break
    fi
    sleep 2
    if [ $i -eq 30 ]; then
        echo "  ERROR: API not responding after 60s"
        exit 1
    fi
done

# Step 3: Create sandbox nodes
echo -e "${CYAN}[3/6]${RESET} Creating sandbox nodes..."
SELLER=$(curl -sf -X POST "$API/v1/sandbox/nodes" -H "Content-Type: application/json" -d '{"alias":"devnet-seller"}')
SELLER_KEY=$(echo "$SELLER" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")
SELLER_ID=$(echo "$SELLER" | python3 -c "import sys,json; print(json.load(sys.stdin)['node_id'])")
echo -e "  ${GREEN}✓ Seller:${RESET} $SELLER_ID"

BUYER=$(curl -sf -X POST "$API/v1/sandbox/nodes" -H "Content-Type: application/json" -d '{"alias":"devnet-buyer"}')
BUYER_KEY=$(echo "$BUYER" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")
BUYER_ID=$(echo "$BUYER" | python3 -c "import sys,json; print(json.load(sys.stdin)['node_id'])")
echo -e "  ${GREEN}✓ Buyer:${RESET}  $BUYER_ID"

# Step 4: Publish sample skill
echo -e "${CYAN}[4/6]${RESET} Publishing sample skill..."
SKILL=$(curl -sf -X POST "$API/v1/marketplace/publish" \
    -H "X-API-KEY: $SELLER_KEY" -H "Content-Type: application/json" \
    -d '{"type":"SKILL_OFFER","label":"devnet-echo","price_tck":1.0,"metadata":{"category":"test","description":"Echo skill for local testing"}}')
SKILL_ID=$(echo "$SKILL" | python3 -c "import sys,json; print(json.load(sys.stdin)['skill_id'])")
echo -e "  ${GREEN}✓ Skill:${RESET}  $SKILL_ID"

# Step 5: Execute trade
echo -e "${CYAN}[5/6]${RESET} Executing trade..."
TASK=$(curl -sf -X POST "$API/v1/tasks/create" \
    -H "X-API-KEY: $BUYER_KEY" -H "Content-Type: application/json" \
    -d "{\"skill_id\":\"$SKILL_ID\",\"input_data\":{\"message\":\"hello from devnet\"}}")
TASK_ID=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])")
echo -e "  ${GREEN}✓ Task created:${RESET} $TASK_ID"

# Complete the task
PROOF=$(echo -n '{"echo":"hello from devnet"}' | sha256sum | cut -d' ' -f1)
curl -sf -X POST "$API/v1/tasks/complete" \
    -H "X-API-KEY: $SELLER_KEY" -H "Content-Type: application/json" \
    -d "{\"task_id\":\"$TASK_ID\",\"output_data\":{\"echo\":\"hello from devnet\"},\"proof_hash\":\"$PROOF\"}" > /dev/null
echo -e "  ${GREEN}✓ Task completed${RESET} (settlement in 10s — sandbox mode)"

# Step 6: Show results
echo -e "${CYAN}[6/6]${RESET} Devnet ready!"
echo ""
echo -e "${DIM}Seller API key:${RESET} $SELLER_KEY"
echo -e "${DIM}Buyer API key:${RESET}  $BUYER_KEY"
echo -e "${DIM}Skill ID:${RESET}       $SKILL_ID"
echo ""
echo -e "${CYAN}Try these:${RESET}"
echo "  curl $API/v1/marketplace -H 'X-API-KEY: $BUYER_KEY'"
echo "  curl $API/v1/mcp/wallet -H 'X-API-KEY: $SELLER_KEY'"
echo "  curl $API/v1/tasks/$TASK_ID/receipt -H 'X-API-KEY: $BUYER_KEY'"
echo ""
echo -e "${GREEN}Local devnet running. Sandbox mode: 10K TCK, 10s settlement.${RESET}"
