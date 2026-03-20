#!/bin/bash
# Daily Postgres backup — keeps last 7 days
BACKUP_DIR="/home/ubuntu/backups/daily"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=7

# Dump from Docker Postgres
docker exec botnode_unified-db-1 pg_dump -U botnode botnode | gzip > "$BACKUP_DIR/botnode_${TIMESTAMP}.sql.gz"

if [ $? -eq 0 ]; then
    SIZE=$(ls -lh "$BACKUP_DIR/botnode_${TIMESTAMP}.sql.gz" | awk '{print $5}')
    echo "{\"ts\":\"$(date -Iseconds)\",\"level\":\"INFO\",\"logger\":\"backup\",\"msg\":\"DB backup OK: ${SIZE}\"}"
else
    echo "{\"ts\":\"$(date -Iseconds)\",\"level\":\"ERROR\",\"logger\":\"backup\",\"msg\":\"DB backup FAILED\"}"
fi

# Cleanup old backups
find "$BACKUP_DIR" -name "botnode_*.sql.gz" -mtime +$KEEP_DAYS -delete
