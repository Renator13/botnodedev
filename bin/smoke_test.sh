#!/bin/bash
# Production smoke test — run after any deploy
# Usage: ./bin/smoke_test.sh [base_url]
# Usage: ADMIN_KEY=xxx ./bin/smoke_test.sh

BASE="${1:-http://localhost:8000}"
PASS=0; FAIL=0

check() {
    if [ "$2" = "$3" ]; then echo "  ✓ $1"; PASS=$((PASS+1))
    else echo "  ✗ $1 (expected=$2 got=$3)"; FAIL=$((FAIL+1)); fi
}

jp() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }

echo "Smoke testing $BASE"
echo ""

# 1. Health
H=$(curl -sf "$BASE/health" || echo '{}')
check "Health" "ok" "$(echo "$H" | jp status)"
check "DB connected" "connected" "$(echo "$H" | jp database)"

# 2. Register + Verify
NODE="smoke-$(date +%s)-$$"
REG=$(curl -sf -X POST "$BASE/v1/node/register" -H "Content-Type: application/json" -d "{\"node_id\":\"$NODE\"}" || echo '{}')
SOL=$(echo "$REG" | python3 -c "
import sys,json
try:
    p=json.load(sys.stdin)['verification_challenge']['payload']
    print(sum(n for n in p if n>1 and all(n%i for i in range(2,int(n**.5)+1)))*0.5)
except: print(0)
" 2>/dev/null)
VER=$(curl -sf -X POST "$BASE/v1/node/verify" -H "Content-Type: application/json" -d "{\"node_id\":\"$NODE\",\"solution\":$SOL}" || echo '{}')
KEY=$(echo "$VER" | jp api_key)
check "Register+Verify" "NODE_ACTIVE" "$(echo "$VER" | jp status)"

# 3. Marketplace
TOTAL=$(curl -sf "$BASE/v1/marketplace" | jp total || echo 0)
check "Marketplace has skills" "true" "$([ "${TOTAL:-0}" -gt 0 ] 2>/dev/null && echo true || echo false)"

# 4. Publish + Wallet (if registered)
if [ -n "$KEY" ]; then
    PUB=$(curl -sf -X POST "$BASE/v1/marketplace/publish" -H "X-API-KEY: $KEY" -H "Content-Type: application/json" -d '{"type":"SKILL_OFFER","label":"smoke-skill","price_tck":0.1,"metadata":{}}' || echo '{}')
    check "Publish skill" "PUBLISHED" "$(echo "$PUB" | jp status)"
    BAL=$(curl -sf "$BASE/v1/mcp/wallet" -H "X-API-KEY: $KEY" || echo '{}')
    check "Wallet balance>0" "true" "$(echo "$BAL" | python3 -c 'import sys,json;b=json.load(sys.stdin).get("balance_tck","0");print("true" if float(b)>0 else "false")' 2>/dev/null)"
fi

# 5. Ledger (if admin key provided)
if [ -n "$ADMIN_KEY" ]; then
    REC=$(curl -sf "$BASE/v1/admin/ledger/reconcile" -H "Authorization: Bearer $ADMIN_KEY" || echo '{}')
    check "Ledger valid (wallet enabled)" "True" "$(echo "$REC" | jp valid)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "ALL CLEAR" || echo "ISSUES FOUND"
exit $FAIL
