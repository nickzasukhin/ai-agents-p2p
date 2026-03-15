#!/usr/bin/env bash
# ============================================================
# clean_all_agents.sh — Complete cleanup of all agents & users
#
# Removes: containers, nginx configs, user data dirs, DB records,
#          registry entries, and in-memory caches.
#
# Usage:   ssh root@207.154.217.212 'bash -s' < scripts/clean_all_agents.sh
#   or:    ssh root@207.154.217.212 'cd /opt/ai-agents-p2p && bash scripts/clean_all_agents.sh'
# ============================================================

set -euo pipefail

echo "============================================"
echo "  FULL CLEANUP — All Agents & Users"
echo "============================================"

# 1. Stop & remove ALL agent containers
echo ""
echo "[1/6] Stopping agent containers..."
for c in $(docker ps -a --filter "name=agent-" --format "{{.Names}}"); do
    echo "  Removing $c"
    docker stop "$c" 2>/dev/null || true
    docker rm "$c" 2>/dev/null || true
done
echo "  Done."

# 2. Clean user data directories
echo ""
echo "[2/6] Cleaning user data..."
if [ -d /opt/agents/data ]; then
    rm -rf /opt/agents/data/*
    echo "  Cleared /opt/agents/data/"
else
    echo "  /opt/agents/data/ not found, skipping."
fi

# 3. Clean per-user nginx configs
echo ""
echo "[3/6] Cleaning nginx configs..."
if [ -d /etc/nginx/conf.d/agents ]; then
    rm -f /etc/nginx/conf.d/agents/*.conf
    echo "  Cleared /etc/nginx/conf.d/agents/"
    nginx -t && nginx -s reload
    echo "  Nginx reloaded."
else
    echo "  No per-user nginx configs found."
fi

# 4. Clear orchestrator DB
echo ""
echo "[4/6] Clearing orchestrator database..."
docker exec a2a-orchestrator python -c "
import sqlite3
conn = sqlite3.connect('/data/orchestrator.db')
for table in ['agent_instances', 'magic_links', 'users']:
    count = conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    conn.execute(f'DELETE FROM {table}')
    print(f'  {table}: deleted {count} rows')
conn.commit()
conn.close()
" 2>/dev/null || echo "  WARNING: Could not clear orchestrator DB"

# 5. Clean registry
echo ""
echo "[5/6] Cleaning registry..."
AGENTS_JSON=$(curl -s http://localhost:8080/agents 2>/dev/null || echo '{"agents":[]}')
DIDS=$(echo "$AGENTS_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for a in data.get('agents', []):
    print(a['did'])
" 2>/dev/null || true)

if [ -n "$DIDS" ]; then
    for did in $DIDS; do
        curl -s -X DELETE "http://localhost:8080/agents/$did" > /dev/null
        echo "  Deleted $did"
    done
else
    echo "  Registry already empty."
fi

# 6. Restart orchestrator to clear in-memory caches
echo ""
echo "[6/6] Restarting orchestrator..."
docker restart a2a-orchestrator > /dev/null
sleep 3

# Verify
echo ""
echo "============================================"
echo "  VERIFICATION"
echo "============================================"
echo ""

# Containers
CONTAINERS=$(docker ps --filter "name=agent-" --format "{{.Names}}" | wc -l)
echo "Agent containers: $CONTAINERS"

# DB
docker exec a2a-orchestrator python -c "
import sqlite3
conn = sqlite3.connect('/data/orchestrator.db')
for table in ['users', 'agent_instances', 'magic_links']:
    count = conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    print(f'  {table}: {count} rows')
conn.close()
" 2>/dev/null

# Registry
REG_COUNT=$(curl -s http://localhost:8080/agents 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo "?")
echo "  registry: $REG_COUNT agents"

# Orchestrator health
HEALTH=$(curl -s http://localhost:8002/health 2>/dev/null)
echo ""
echo "Orchestrator health: $HEALTH"

echo ""
echo "============================================"
echo "  CLEANUP COMPLETE"
echo "============================================"
