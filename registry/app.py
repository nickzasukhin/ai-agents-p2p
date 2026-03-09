"""Agent Registry — lightweight FastAPI service for A2A agent discovery.

Agents register by URL; the registry fetches their Agent Card,
verifies the DID signature, and stores them for discovery.

Endpoints:
    POST /register          — Register an agent by URL
    GET  /agents            — List all agents (optional ?q=keyword search)
    GET  /agents/{did}      — Get a specific agent by DID
    DELETE /agents/{did}    — Unregister an agent
    GET  /health            — Registry health check
"""

from __future__ import annotations

import asyncio
import os

import httpx
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

from db import RegistryDB

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=True),
    ],
)
log = structlog.get_logger()

# ── Configuration ──────────────────────────────────────────────
PORT = int(os.getenv("PORT", "8080"))
DATA_DIR = os.getenv("DATA_DIR", "/data")
HEALTHCHECK_INTERVAL = int(os.getenv("HEALTHCHECK_INTERVAL", "300"))  # 5 min
MAX_FAILURES = 3
MAX_OFFLINE_HOURS = 24

# ── Database ───────────────────────────────────────────────────
db = RegistryDB(db_path=f"{DATA_DIR}/registry.db")


# ── Background healthcheck ─────────────────────────────────────
async def _healthcheck_loop() -> None:
    """Periodically check registered agents and mark failures."""
    while True:
        await asyncio.sleep(HEALTHCHECK_INTERVAL)
        try:
            agents = await db.get_all_agents(status="online")
            log.info("healthcheck_start", agents=len(agents))

            async with httpx.AsyncClient(timeout=10.0) as client:
                for agent in agents:
                    url = agent["url"].rstrip("/")
                    try:
                        resp = await client.get(f"{url}/health")
                        if resp.status_code == 200:
                            # Agent is alive — reset failures
                            await db.upsert_agent(
                                did=agent["did"],
                                url=agent["url"],
                                name=agent.get("name", ""),
                                description=agent.get("description", ""),
                                skills=agent.get("skills", []),
                            )
                        else:
                            failures = await db.increment_failure(agent["did"])
                            if failures >= MAX_FAILURES:
                                await db.mark_offline(agent["did"])
                                log.warning("agent_marked_offline", did=agent["did"][:30])
                    except Exception:
                        failures = await db.increment_failure(agent["did"])
                        if failures >= MAX_FAILURES:
                            await db.mark_offline(agent["did"])
                            log.warning("agent_unreachable_offline", did=agent["did"][:30])

            # Prune agents offline for too long
            pruned = await db.prune_dead(MAX_OFFLINE_HOURS)
            if pruned:
                log.info("agents_pruned", count=pruned)

        except Exception as e:
            log.error("healthcheck_error", error=str(e))


# ── App lifecycle ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    task = asyncio.create_task(_healthcheck_loop())
    log.info("registry_started", port=PORT)
    yield
    task.cancel()
    log.info("registry_shutdown")


app = FastAPI(title="A2A Agent Registry", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────
class RegisterRequest(BaseModel):
    url: str


class RegisterResponse(BaseModel):
    ok: bool
    did: str = ""
    name: str = ""
    message: str = ""


# ── Endpoints ──────────────────────────────────────────────────
@app.post("/register", response_model=RegisterResponse)
async def register_agent(req: RegisterRequest):
    """Register an agent by URL. Fetches agent card + verifies DID."""
    url = req.url.rstrip("/")
    log.info("register_request", url=url)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Health check
        try:
            health_resp = await client.get(f"{url}/health")
            if health_resp.status_code != 200:
                raise HTTPException(400, f"Agent health check failed: {health_resp.status_code}")
        except httpx.ConnectError:
            raise HTTPException(400, f"Cannot reach agent at {url}")
        except httpx.TimeoutException:
            raise HTTPException(400, f"Agent at {url} timed out")

        # 2. Fetch Agent Card
        try:
            card_resp = await client.get(f"{url}/.well-known/agent-card.json")
            card_resp.raise_for_status()
            card_data = card_resp.json()
        except Exception as e:
            raise HTTPException(400, f"Failed to fetch agent card: {e}")

        # 3. Fetch identity + verify DID signature
        did = ""
        try:
            identity_resp = await client.get(f"{url}/identity")
            if identity_resp.status_code == 200:
                identity = identity_resp.json()
                did = identity.get("did", "")
                signed_card = identity.get("signed_card")

                if signed_card and did:
                    # Verify signature (import locally to avoid dep on main project)
                    from _verify import verify_card_signature
                    verified = verify_card_signature(signed_card)
                    if not verified:
                        log.warning("agent_card_signature_invalid", url=url)
                        # Still register but note it's unverified
        except Exception:
            log.debug("identity_fetch_skipped", url=url)

        # If no DID from identity endpoint, generate one from URL
        if not did:
            import hashlib
            did = f"did:web:{hashlib.sha256(url.encode()).hexdigest()[:32]}"

        # 4. Extract skills
        skills = []
        for skill in card_data.get("skills", []):
            skills.append({
                "id": skill.get("id", ""),
                "name": skill.get("name", ""),
                "description": skill.get("description", ""),
                "tags": skill.get("tags", []),
            })

        name = card_data.get("name", "Unknown Agent")
        description = card_data.get("description", "")

        # 5. Save
        await db.upsert_agent(
            did=did,
            url=url,
            name=name,
            description=description,
            skills=skills,
        )

        log.info("agent_registered", did=did[:30], name=name, skills=len(skills))
        return RegisterResponse(ok=True, did=did, name=name, message="Registered successfully")


@app.get("/agents")
async def list_agents(q: str = "", status: str = ""):
    """List registered agents. Optional ?q=keyword for search."""
    if q:
        agents = await db.search_agents(q)
    elif status:
        agents = await db.get_all_agents(status=status)
    else:
        agents = await db.get_all_agents()

    return {"count": len(agents), "agents": agents}


@app.get("/agents/{did}")
async def get_agent(did: str):
    """Get a specific agent by DID."""
    agent = await db.get_agent_by_did(did)
    if not agent:
        raise HTTPException(404, f"Agent not found: {did}")
    return agent


@app.delete("/agents/{did}")
async def delete_agent(did: str):
    """Unregister an agent."""
    deleted = await db.delete_agent(did)
    if not deleted:
        raise HTTPException(404, f"Agent not found: {did}")
    return {"ok": True, "message": f"Agent {did} removed"}


@app.get("/health")
async def health():
    """Registry health check."""
    count = await db.count()
    return {
        "status": "ok",
        "service": "a2a-agent-registry",
        "registered_agents": count,
    }
