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

# Rotate health log (keep last 1000 lines)
if [ -f "$LOG" ] && [ $(wc -l < "$LOG") -gt 1000 ]; then
    tail -500 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi
