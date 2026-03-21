#!/bin/bash
# Simple health monitor — runs every 5 min via cron
# Restarts unhealthy containers and logs status

LOG="/var/log/botnode-health.log"
API_URL="http://localhost:8000/health"
TIMESTAMP=$(date -Iseconds)

# Check API
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$API_URL")

if [ "$HTTP_CODE" != "200" ]; then
    echo "{\"ts\":\"$TIMESTAMP\",\"level\":\"ERROR\",\"msg\":\"API unhealthy (HTTP $HTTP_CODE) — restarting\"}" >> "$LOG"
    docker compose restart api task-runner 2>> "$LOG"
else
    # Check DB connectivity from the response
    DB_STATUS=$(curl -s --max-time 5 "$API_URL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('database','unknown'))" 2>/dev/null)
    if [ "$DB_STATUS" != "connected" ]; then
        echo "{\"ts\":\"$TIMESTAMP\",\"level\":\"ERROR\",\"msg\":\"DB disconnected — restarting db\"}" >> "$LOG"
        cd /home/ubuntu/botnode_unified && docker compose restart db 2>> "$LOG"
        sleep 10
        docker compose restart api task-runner 2>> "$LOG"
    fi
fi

# Check disk space (alert if >85%)
DISK_PCT=$(df / --output=pcent | tail -1 | tr -d ' %')
if [ "$DISK_PCT" -gt 85 ]; then
    echo "{\"ts\":\"$TIMESTAMP\",\"level\":\"WARNING\",\"msg\":\"Disk usage at ${DISK_PCT}%\"}" >> "$LOG"
fi

# Check for stuck tasks (OPEN > 2h or IN_PROGRESS > 4h)
STUCK=$(docker exec botnode_unified-db-1 psql -U botnode -d botnode -t -c "
SELECT count(*) FROM tasks
WHERE (status='OPEN' AND created_at < NOW() - INTERVAL '2 hours')
   OR (status='IN_PROGRESS' AND created_at < NOW() - INTERVAL '4 hours')
" 2>/dev/null | tr -d ' \n')
if [ "$STUCK" -gt 0 ] 2>/dev/null; then
    echo "{\"ts\":\"$TIMESTAMP\",\"level\":\"WARNING\",\"msg\":\"$STUCK stuck tasks (OPEN>2h or IN_PROGRESS>4h)\"}" >> "$LOG"
fi

# Check for overdue settlements
OVERDUE=$(docker exec botnode_unified-db-1 psql -U botnode -d botnode -t -c "
SELECT count(*) FROM escrows
WHERE status='AWAITING_SETTLEMENT' AND auto_settle_at < NOW()
" 2>/dev/null | tr -d ' \n')
if [ "$OVERDUE" -gt 0 ] 2>/dev/null; then
    echo "{\"ts\":\"$TIMESTAMP\",\"level\":\"WARNING\",\"msg\":\"$OVERDUE escrows past settlement deadline\"}" >> "$LOG"
fi

# Rotate health log (keep last 1000 lines)
if [ -f "$LOG" ] && [ $(wc -l < "$LOG") -gt 1000 ]; then
    tail -500 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi
