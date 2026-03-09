#!/bin/bash
# Deploy script for VPS 207.154.217.212 (devpunks.io)
# Prerequisites: Docker, nginx, certbot already installed
#
# Usage:
#   scp -r deploy/production/ root@207.154.217.212:/opt/ai-agents-p2p/deploy/production/
#   ssh root@207.154.217.212 'bash /opt/ai-agents-p2p/deploy/production/setup.sh'

set -e

REPO_DIR="/opt/ai-agents-p2p"
DEPLOY_DIR="$REPO_DIR/deploy/production"

echo "=== A2A Agent Network — Production Deploy ==="

# 1. Clone or pull repo
if [ -d "$REPO_DIR/.git" ]; then
    echo "→ Pulling latest code..."
    cd "$REPO_DIR" && git pull
else
    echo "→ Cloning repository..."
    git clone https://github.com/nickzasukhin/ai-agents-p2p.git "$REPO_DIR"
fi

# 2. Copy nginx configs + enable sites
echo "→ Configuring nginx..."
cp "$DEPLOY_DIR/agents.devpunks.io.nginx" /etc/nginx/sites-available/agents.devpunks.io
cp "$DEPLOY_DIR/registry.devpunks.io.nginx" /etc/nginx/sites-available/registry.devpunks.io
ln -sf /etc/nginx/sites-available/agents.devpunks.io /etc/nginx/sites-enabled/
ln -sf /etc/nginx/sites-available/registry.devpunks.io /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
echo "  ✓ nginx configured"

# 3. SSL certificates (certbot)
echo "→ Setting up SSL certificates..."
certbot --nginx -d agents.devpunks.io --non-interactive --agree-tos --redirect 2>/dev/null || echo "  ⚠ certbot for agents.devpunks.io needs manual setup (DNS not ready?)"
certbot --nginx -d registry.devpunks.io --non-interactive --agree-tos --redirect 2>/dev/null || echo "  ⚠ certbot for registry.devpunks.io needs manual setup (DNS not ready?)"

# 4. Create .env if not exists
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
    echo ""
    echo "⚠️  IMPORTANT: Edit $DEPLOY_DIR/.env with your secrets!"
    echo "   Required: OPENAI_API_KEY, API_TOKEN"
    echo "   Then re-run this script."
    echo ""
    exit 1
fi

# 5. Build & start containers
echo "→ Building and starting Docker containers..."
cd "$DEPLOY_DIR"

# Use docker-compose (available at /usr/local/bin/docker-compose)
COMPOSE_CMD="docker-compose"
if command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
fi

$COMPOSE_CMD -f docker-compose.prod.yml up -d --build
echo "  ✓ Containers started"

# 6. Verify
echo "→ Waiting for services to start..."
sleep 15

echo "→ Verifying services..."
if curl -sf http://localhost:9100/health > /dev/null 2>&1; then
    echo "  ✓ Agent is healthy"
else
    echo "  ✗ Agent health check failed"
fi

if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    echo "  ✓ Registry is healthy"
else
    echo "  ✗ Registry health check failed"
fi

echo ""
echo "=== Deploy complete ==="
echo "  Agent:    https://agents.devpunks.io"
echo "  Registry: https://registry.devpunks.io"
echo "  Card:     https://agents.devpunks.io/.well-known/agent-card.json"
echo ""
