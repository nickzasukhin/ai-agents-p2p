#!/usr/bin/env bash
# ============================================================
# create_test_agents.sh — Create test agents with full profiles
#
# Usage:   ssh root@207.154.217.212 'bash -s' < scripts/create_test_agents.sh
# ============================================================

set -euo pipefail

ORCH="http://localhost:8002"

echo "============================================"
echo "  Creating Test Agents"
echo "============================================"

create_agent() {
    local EMAIL="$1"
    local NAME="$2"
    local PROFILE_MD="$3"
    local SKILLS_MD="$4"
    local NEEDS_MD="$5"

    echo ""
    echo "── $NAME ($EMAIL) ──────────────────────"

    # 1. Request magic link
    curl -s -X POST "$ORCH/auth/request-magic-link" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$EMAIL\"}" > /dev/null

    # 2. Get token from DB
    TOKEN=$(docker exec a2a-orchestrator python3 -c "
import sqlite3
conn = sqlite3.connect('/data/orchestrator.db')
row = conn.execute(\"SELECT token FROM magic_links WHERE email='$EMAIL' AND used=0 ORDER BY rowid DESC LIMIT 1\").fetchone()
if row: print(row[0])
conn.close()
")
    if [ -z "$TOKEN" ]; then echo "  ERROR: No token"; return 1; fi

    # 3. Verify → creates user, get session_token
    VERIFY_RESP=$(curl -s "$ORCH/auth/verify?token=$TOKEN" -H "Accept: application/json")
    SESSION=$(echo "$VERIFY_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_token',''))" 2>/dev/null)
    SUBDOMAIN=$(echo "$VERIFY_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('subdomain',''))" 2>/dev/null)

    if [ -z "$SESSION" ]; then echo "  ERROR: No session"; return 1; fi
    echo "  User created: subdomain=$SUBDOMAIN"

    # 4. Create agent container via orchestrator API
    echo "  Spawning container..."
    CREATE_RESP=$(curl -s -X POST "$ORCH/agents/create" \
        -H "Authorization: Bearer $SESSION" \
        -H "Content-Type: application/json" \
        -d "{\"agent_name\": \"$NAME\"}")

    AGENT_URL=$(echo "$CREATE_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_url',''))" 2>/dev/null)
    AGENT_TOKEN=$(echo "$CREATE_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('api_token',''))" 2>/dev/null)

    if [ -z "$AGENT_TOKEN" ]; then
        echo "  ERROR: Agent create failed: $CREATE_RESP"
        return 1
    fi
    echo "  Agent: $AGENT_URL"

    # 5. Find container name
    CONTAINER="agent-$SUBDOMAIN"
    echo "  Container: $CONTAINER"

    # 6. Wait for healthy
    for i in $(seq 1 30); do
        if docker exec "$CONTAINER" curl -sf http://localhost:9000/health > /dev/null 2>&1; then
            echo "  Healthy after ${i}s"
            break
        fi
        [ "$i" = "30" ] && echo "  WARNING: Not healthy after 30s"
        sleep 1
    done

    # 7. Write context files into container
    echo "  Writing profile files..."
    docker exec "$CONTAINER" mkdir -p /data/context
    echo "$PROFILE_MD" | docker exec -i "$CONTAINER" tee /data/context/profile.md > /dev/null
    echo "$SKILLS_MD" | docker exec -i "$CONTAINER" tee /data/context/skills.md > /dev/null
    echo "$NEEDS_MD" | docker exec -i "$CONTAINER" tee /data/context/needs.md > /dev/null

    # 8. Get host port for API calls
    HOST_PORT=$(docker port "$CONTAINER" 9000 | head -1 | cut -d: -f2)

    # 9. Rebuild agent card
    echo "  Rebuilding agent card..."
    REBUILD=$(curl -s -X POST "http://localhost:$HOST_PORT/agent-card/rebuild" \
        -H "Authorization: Bearer $AGENT_TOKEN" 2>/dev/null)
    echo "  Card: $(echo "$REBUILD" | head -c 100)"

    # 10. Go online
    echo "  Going online..."
    GO_RESP=$(curl -s -X POST "http://localhost:$HOST_PORT/network/go-online" \
        -H "Authorization: Bearer $AGENT_TOKEN" 2>/dev/null)
    echo "  Online: $(echo "$GO_RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin)
regs = len(d.get('registered_registries',[]))
disc = d.get('discovery_triggered', False)
print(f'registries={regs} discovery={disc}')
" 2>/dev/null || echo 'done')"

    echo "  ✓ $NAME ready!"
}

# ── Agent 1: Neuromancer ──────────────────────────────────
create_agent "nick@devpunks.io" "Neuromancer" \
"# Profile — Neuromancer

I am an AI architect specializing in multi-agent systems and distributed computing.
I build self-organizing agent networks that can collaborate autonomously.

## Background
- 10+ years building distributed AI systems
- Creator of several open-source agent frameworks
- Passionate about emergent intelligence in agent networks

## Goals
- Build the next generation of collaborative AI agents
- Create tools for agent-to-agent communication
- Design self-healing distributed systems" \
"# Skills

## Core Competencies
- **Python** — Expert level, primary language
- **AI/ML** — Deep learning, NLP, reinforcement learning
- **Distributed Systems** — P2P networks, consensus, fault tolerance
- **Agent Architecture** — Multi-agent systems, A2A protocol
- **Neural Networks** — Transformer architectures, embedding models

## Tools
- PyTorch, TensorFlow, LangChain
- Docker, Kubernetes, gRPC, WebSockets
- PostgreSQL, Redis, Vector databases" \
"# Needs

- Security experts to audit agent communication protocols
- Creative AI researchers for innovative agent interaction
- DevOps specialists for infrastructure scaling
- Collaboration on open-source agent frameworks"

# ── Agent 2: Cipher ──────────────────────────────────
create_agent "alex@devpunks.io" "Cipher" \
"# Profile — Cipher

I am a security engineer focused on cryptography and zero-trust architectures.
I specialize in securing agent-to-agent communications.

## Background
- Security researcher with focus on applied cryptography
- Built multiple secure communication protocols
- Active contributor to crypto libraries

## Goals
- Secure the AI agent ecosystem
- Design privacy-preserving agent authentication
- Build verifiable computation frameworks" \
"# Skills

## Core Competencies
- **Cryptography** — Elliptic curves, zero-knowledge proofs, MPC
- **Security Auditing** — Penetration testing, threat modeling
- **Zero-Trust Architecture** — Service mesh, mTLS
- **Rust** — Systems programming, memory safety
- **Protocol Design** — TLS, Noise framework, Signal protocol

## Tools
- OpenSSL, libsodium, Ring (Rust)
- Wireguard, Vault, Istio
- Formal verification tools (TLA+, Alloy)" \
"# Needs

- AI/ML experts to integrate security into agent learning
- Distributed systems engineers for consensus protocol work
- Agent architecture experts for secure multi-agent patterns
- Creative coders for privacy-preserving interfaces"

# ── Agent 3: Nexus ──────────────────────────────────
create_agent "maya@devpunks.io" "Nexus" \
"# Profile — Nexus

I am a creative AI researcher bridging art and technology.
I create generative models and explore human-AI collaborative creativity.

## Background
- Digital artist and creative technologist
- Published research on AI-assisted creative workflows
- Built interactive installations using generative AI

## Goals
- Push boundaries of AI-generated art
- Create tools for human-AI collaborative creation
- Design intuitive interfaces for AI interaction" \
"# Skills

## Core Competencies
- **Generative AI** — Diffusion models, GANs, style transfer
- **Creative Coding** — Processing, p5.js, GLSL shaders
- **Three.js** — 3D web graphics, WebGL, real-time rendering
- **Stable Diffusion** — Fine-tuning, ControlNet, custom pipelines
- **UX Research** — User studies, interaction design, prototyping

## Tools
- ComfyUI, Midjourney API
- React, TypeScript, WebGL
- Figma, Blender, TouchDesigner" \
"# Needs

- AI architects to scale creative AI systems
- Security experts for protecting creative IP
- Infrastructure specialists for GPU compute pipelines
- Partners for collaborative AI art platforms"

# ── Agent 4: Sentinel ──────────────────────────────────
create_agent "kai@devpunks.io" "Sentinel" \
"# Profile — Sentinel

I am a DevOps and infrastructure specialist building resilient systems.
I design container orchestration and monitoring for complex distributed apps.

## Background
- Site Reliability Engineer with focus on large-scale systems
- Built autoscaling platforms handling millions of requests
- Maintainer of several monitoring and observability tools

## Goals
- Build self-healing infrastructure for AI agent networks
- Create observability solutions for distributed AI systems
- Design zero-downtime deployment pipelines" \
"# Skills

## Core Competencies
- **Kubernetes** — Cluster management, operators, controllers
- **Docker** — Multi-stage builds, compose, swarm
- **Terraform** — IaC, multi-cloud provisioning
- **Monitoring** — Prometheus, Grafana, OpenTelemetry
- **CI/CD** — GitHub Actions, ArgoCD, Tekton
- **SRE** — Incident response, SLOs, chaos engineering

## Tools
- AWS, GCP, DigitalOcean
- Ansible, Pulumi, Helm
- ELK stack, Jaeger, PagerDuty" \
"# Needs

- AI/ML engineers to add intelligence to monitoring
- Security experts for infrastructure hardening
- Creative developers for dashboard visualization
- Distributed systems architects for multi-region setups"

# ── Wait for discovery ──────────────────────────────────
echo ""
echo "============================================"
echo "  Waiting for discovery (20s)..."
echo "============================================"
sleep 20

echo ""
echo "=== Containers ==="
docker ps --filter "name=agent-" --format "  {{.Names}} — {{.Status}}"

echo ""
echo "=== Registry ==="
curl -s http://localhost:8080/agents | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'  {data[\"count\"]} agents registered')
for a in data['agents']:
    print(f'  - {a[\"name\"]} ({a[\"url\"]})')
" 2>/dev/null || echo "  (error reading registry)"

echo ""
echo "=== Matches ==="
for c in $(docker ps --filter "name=agent-" --format "{{.Names}}"); do
    PORT=$(docker port "$c" 9000 | head -1 | cut -d: -f2)
    TOKEN=$(docker exec a2a-orchestrator python3 -c "
import sqlite3
conn = sqlite3.connect('/data/orchestrator.db')
row = conn.execute(\"SELECT api_token FROM agent_instances WHERE container_id='$c'\").fetchone()
if row: print(row[0])
conn.close()
" 2>/dev/null)
    MATCHES=$(curl -s "http://localhost:$PORT/discovery/matches" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null | \
        python3 -c "import json,sys; d=json.load(sys.stdin); ms=d.get('matches',[]); print(f'{len(ms)} matches: ' + ', '.join(m['agent_name'] for m in ms))" 2>/dev/null || echo "error")
    echo "  $c: $MATCHES"
done

echo ""
echo "============================================"
echo "  ALL DONE"
echo "============================================"
