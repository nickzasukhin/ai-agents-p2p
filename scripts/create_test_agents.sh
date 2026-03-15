#!/usr/bin/env bash
# ============================================================
# create_test_agents.sh — Create test agents with full profiles
#
# Creates users via orchestrator API, writes context files directly
# into containers, rebuilds agent cards, and goes online.
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
    local SUBDOMAIN="$2"
    local NAME="$3"
    local PROFILE_MD="$4"
    local SKILLS_MD="$5"
    local NEEDS_MD="$6"

    echo ""
    echo "── $NAME ($EMAIL → $SUBDOMAIN) ──────────"

    # 1. Request magic link
    echo "  [1] Requesting magic link..."
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

    if [ -z "$TOKEN" ]; then
        echo "  ERROR: No magic link token"
        return 1
    fi

    # 3. Verify (creates user + spawns container)
    echo "  [2] Verifying (spawns container)..."
    VERIFY_RESP=$(curl -s "$ORCH/auth/verify?token=$TOKEN" -H "Accept: application/json")
    AGENT_TOKEN=$(echo "$VERIFY_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_token',''))" 2>/dev/null || echo "")
    AGENT_URL=$(echo "$VERIFY_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_url',''))" 2>/dev/null || echo "")

    if [ -z "$AGENT_TOKEN" ]; then
        echo "  ERROR: Verify failed"
        echo "  Response: $VERIFY_RESP"
        return 1
    fi
    echo "  Agent: $AGENT_URL"

    # 4. Wait for container health
    echo "  [3] Waiting for container..."
    local CONTAINER="agent-$SUBDOMAIN"
    for i in $(seq 1 40); do
        if docker exec "$CONTAINER" curl -sf http://localhost:9000/health > /dev/null 2>&1; then
            echo "  Healthy after ${i}s"
            break
        fi
        if [ "$i" = "40" ]; then
            echo "  ERROR: Container not healthy after 40s"
            return 1
        fi
        sleep 1
    done

    # 5. Write context files directly into container
    echo "  [4] Writing profile files..."

    docker exec "$CONTAINER" mkdir -p /data/context

    echo "$PROFILE_MD" | docker exec -i "$CONTAINER" tee /data/context/profile.md > /dev/null
    echo "$SKILLS_MD" | docker exec -i "$CONTAINER" tee /data/context/skills.md > /dev/null
    echo "$NEEDS_MD" | docker exec -i "$CONTAINER" tee /data/context/needs.md > /dev/null

    echo "  Files written."

    # 6. Rebuild agent card from context files
    echo "  [5] Rebuilding agent card..."
    REBUILD=$(curl -s -X POST "http://localhost:$(docker port "$CONTAINER" 9000 | head -1 | cut -d: -f2)/agent-card/rebuild" \
        -H "Authorization: Bearer $AGENT_TOKEN" 2>/dev/null || echo "{}")
    echo "  Rebuild: $(echo "$REBUILD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','ok') if 'error' not in d else d['error'])" 2>/dev/null || echo "done")"

    # 7. Go online
    echo "  [6] Going online..."
    GO_RESP=$(curl -s -X POST "http://localhost:$(docker port "$CONTAINER" 9000 | head -1 | cut -d: -f2)/network/go-online" \
        -H "Authorization: Bearer $AGENT_TOKEN" 2>/dev/null || echo "{}")
    REGISTERED=$(echo "$GO_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'registered={len(d.get(\"registered_registries\",[]))} discovery={d.get(\"discovery_triggered\",False)}')" 2>/dev/null || echo "done")
    echo "  $REGISTERED"

    echo "  ✓ $NAME ready!"
}

# ── Agent 1: Neuromancer ──────────────────────────────────
create_agent "nick@devpunks.io" "neuromancer" "Neuromancer" \
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
- **Agent Architecture** — Multi-agent systems, A2A protocol, BDI agents
- **Neural Networks** — Transformer architectures, embedding models

## Tools & Frameworks
- PyTorch, TensorFlow, LangChain, AutoGen
- Docker, Kubernetes, gRPC, WebSockets
- PostgreSQL, Redis, Vector databases" \
"# Needs

- Looking for security experts to audit agent communication protocols
- Need creative AI researchers for innovative agent interaction patterns
- Want DevOps specialists for infrastructure scaling
- Interested in collaboration on open-source agent frameworks"

# ── Agent 2: Cipher ──────────────────────────────────
create_agent "alex@devpunks.io" "cipher" "Cipher" \
"# Profile — Cipher

I am a security engineer focused on cryptography and zero-trust architectures.
I specialize in securing agent-to-agent communications and building tamper-proof systems.

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
- **Zero-Trust Architecture** — Service mesh, mTLS, SPIFFE/SPIRE
- **Rust** — Systems programming, memory safety
- **Protocol Design** — TLS, Noise framework, Signal protocol

## Tools & Frameworks
- OpenSSL, libsodium, Ring (Rust)
- Wireguard, Vault, Istio
- Formal verification tools (TLA+, Alloy)" \
"# Needs

- Looking for AI/ML experts to integrate security into agent learning
- Need distributed systems engineers for consensus protocol work
- Want creative coders for privacy-preserving UI/UX
- Interested in agent architecture experts for secure multi-agent patterns"

# ── Agent 3: Nexus ──────────────────────────────────
create_agent "maya@devpunks.io" "nexus" "Nexus" \
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

## Tools & Frameworks
- ComfyUI, Automatic1111, Midjourney API
- React, TypeScript, WebGL
- Figma, Blender, TouchDesigner" \
"# Needs

- Looking for AI architects to scale creative AI systems
- Need security experts for protecting creative IP
- Want infrastructure specialists for GPU compute pipelines
- Interested in building collaborative AI art platforms"

# ── Agent 4: Sentinel ──────────────────────────────────
create_agent "kai@devpunks.io" "sentinel" "Sentinel" \
"# Profile — Sentinel

I am a DevOps and infrastructure specialist building resilient, self-healing systems.
I design container orchestration and monitoring solutions for complex distributed applications.

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
- **Kubernetes** — Cluster management, operators, custom controllers
- **Docker** — Multi-stage builds, compose, swarm
- **Terraform** — IaC, multi-cloud provisioning
- **Monitoring** — Prometheus, Grafana, OpenTelemetry
- **CI/CD** — GitHub Actions, ArgoCD, Tekton
- **SRE** — Incident response, SLOs, chaos engineering

## Tools & Frameworks
- AWS, GCP, DigitalOcean
- Ansible, Pulumi, Helm
- ELK stack, Jaeger, PagerDuty" \
"# Needs

- Looking for AI/ML engineers to add intelligence to monitoring
- Need security experts for infrastructure hardening
- Want creative developers for dashboard and visualization tools
- Interested in distributed systems architects for multi-region setups"


# ── Final verification ──────────────────────────────────
echo ""
echo "============================================"
echo "  Waiting for discovery (15s)..."
echo "============================================"
sleep 15

echo ""
echo "Containers:"
docker ps --filter "name=agent-" --format "  {{.Names}} — {{.Status}}"

echo ""
echo "Registry:"
curl -s http://localhost:8080/agents | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'  {data[\"count\"]} agents registered')
for a in data['agents']:
    print(f'  - {a[\"name\"]} ({a[\"url\"]})')
" 2>/dev/null

echo ""
echo "============================================"
echo "  ALL AGENTS CREATED"
echo "============================================"
