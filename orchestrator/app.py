"""Orchestrator — FastAPI service for managing personal cloud agents.

Endpoints:
    POST /auth/request-magic-link  — Send magic link email
    GET  /auth/verify              — Verify magic link token → session cookie
    GET  /auth/me                  — Get current user info
    POST /auth/logout              — Clear session

    POST /agents/create            — Spawn a new agent container
    GET  /agents/mine              — Get user's agent info
    DELETE /agents/mine            — Stop + remove user's agent

    GET  /admin/agents             — List all agents (admin only)
    GET  /admin/agents/{id}/logs   — Container logs (admin only)
    POST /admin/agents/{id}/restart — Restart container (admin only)

    GET  /health                   — Service health check
"""

from __future__ import annotations

import re
import asyncio

import structlog
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from contextlib import asynccontextmanager

from orchestrator.config import OrchestratorConfig
from orchestrator.models import OrchestratorDB
from orchestrator.auth.magic_link import MagicLinkManager, SessionManager
from orchestrator.auth.email import EmailSender
from orchestrator.containers.manager import ContainerManager
from orchestrator.containers.port_allocator import PortAllocator
from orchestrator.proxy import NginxProxy

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=True),
    ],
)
log = structlog.get_logger()

# Simple email regex for validation
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


# ── Request/Response Models ───────────────────────────────────

class MagicLinkRequest(BaseModel):
    email: str


class CreateAgentRequest(BaseModel):
    agent_name: str = "My Agent"


# ── App Factory ───────────────────────────────────────────────

def create_orchestrator_app(
    config: OrchestratorConfig | None = None,
    db: OrchestratorDB | None = None,
    container_manager: ContainerManager | None = None,
    nginx_proxy: NginxProxy | None = None,
) -> FastAPI:
    """Create the orchestrator FastAPI application.

    Accepts optional overrides for testing (mock DB, mock containers).
    """
    config = config or OrchestratorConfig()

    # Initialize services
    _db = db or OrchestratorDB(db_path=config.db_path)
    magic_links = MagicLinkManager(
        secret=config.jwt_secret,
        expiry_minutes=config.magic_link_expiry_minutes,
        base_url=config.base_url,
    )
    sessions = SessionManager(
        secret=config.jwt_secret,
        expiry_hours=config.session_expiry_hours,
    )
    email_sender = EmailSender(
        resend_api_key=config.resend_api_key,
        email_from=config.email_from,
        enabled=config.email_enabled,
    )
    port_allocator = PortAllocator(start=config.port_range_start, end=config.port_range_end)
    containers = container_manager or ContainerManager(
        agent_image=config.agent_image,
        data_root=config.agent_data_root,
        port_allocator=port_allocator,
        seed_node_url=config.seed_node_url,
        domain=config.domain,
    )
    proxy = nginx_proxy or NginxProxy(conf_dir=config.nginx_conf_dir, domain=config.domain)

    # ── Lifecycle ─────────────────────────────────────────────

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await _db.init()
        log.info("orchestrator_started", port=config.port)
        yield
        await _db.close()
        log.info("orchestrator_shutdown")

    app = FastAPI(
        title="DevPunks Agent Orchestrator",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store references for endpoint access
    app.state.db = _db
    app.state.config = config
    app.state.magic_links = magic_links
    app.state.sessions = sessions
    app.state.email_sender = email_sender
    app.state.containers = containers
    app.state.proxy = proxy

    # ── Auth helpers ──────────────────────────────────────────

    async def get_current_user(request: Request) -> dict:
        """Extract and verify user from session cookie or Bearer token."""
        # Check cookie first
        token = request.cookies.get("session")
        # Then check Authorization header
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            raise HTTPException(401, "Authentication required")

        payload = sessions.verify_session(token)
        if not payload:
            raise HTTPException(401, "Invalid or expired session")

        user = await _db.get_user_by_id(payload["user_id"])
        if not user:
            raise HTTPException(401, "User not found")

        return user

    async def get_admin_user(request: Request) -> dict:
        """Verify user is an admin."""
        user = await get_current_user(request)
        if user["email"] not in config.admin_emails:
            raise HTTPException(403, "Admin access required")
        return user

    # ── Auth Endpoints ────────────────────────────────────────

    @app.post("/auth/request-magic-link")
    async def request_magic_link(req: MagicLinkRequest):
        """Send a magic link email for passwordless authentication."""
        email = req.email.lower().strip()

        if not EMAIL_RE.match(email):
            raise HTTPException(400, "Invalid email address")

        # Generate magic link
        token, expires_at = magic_links.create_token(email)
        link = magic_links.build_link(token)

        # Store in DB
        await _db.create_magic_link(token=token, email=email, expires_at=expires_at)

        # Send email
        sent = await email_sender.send_magic_link(to_email=email, magic_link=link)

        if not sent:
            raise HTTPException(500, "Failed to send email")

        log.info("magic_link_requested", email=email)
        return {"ok": True, "message": "Magic link sent. Check your email."}

    @app.get("/auth/verify")
    async def verify_magic_link(token: str, response: Response):
        """Verify magic link token and create session."""
        # Verify token signature + expiry
        payload = magic_links.verify_token(token)
        if not payload:
            raise HTTPException(400, "Invalid or expired magic link")

        email = payload["email"]

        # Check token in DB (single-use)
        link_data = await _db.use_magic_link(token)
        if not link_data:
            raise HTTPException(400, "Magic link already used or not found")

        # Find or create user
        user = await _db.get_user_by_email(email)
        is_new = user is None

        if is_new:
            user = await _db.create_user(email)
            log.info("new_user_created", email=email, user_id=user["id"])
        else:
            await _db.update_last_login(user["id"])

        # Create session token
        session_token = sessions.create_session(user["id"], email)

        # Check if user has an agent
        agent = await _db.get_agent_by_user(user["id"])

        log.info("auth_verified", email=email, is_new=is_new, has_agent=agent is not None)

        # Return JSON with session token (frontend handles cookie/storage)
        return {
            "ok": True,
            "session_token": session_token,
            "user_id": user["id"],
            "email": email,
            "is_new_user": is_new,
            "has_agent": agent is not None,
            "agent_url": agent["agent_url"] if agent else None,
        }

    @app.get("/auth/me")
    async def get_me(request: Request):
        """Get current user info + agent status."""
        user = await get_current_user(request)
        agent = await _db.get_agent_by_user(user["id"])

        result = {
            "user_id": user["id"],
            "email": user["email"],
            "created_at": user["created_at"],
            "has_agent": agent is not None,
        }

        if agent:
            result["agent_url"] = agent["agent_url"]
            result["agent_status"] = agent["status"]
            result["agent_created_at"] = agent["created_at"]

        return result

    @app.post("/auth/logout")
    async def logout(response: Response):
        """Clear session."""
        response.delete_cookie("session")
        return {"ok": True, "message": "Logged out"}

    # ── Agent Endpoints ───────────────────────────────────────

    @app.post("/agents/create")
    async def create_agent(req: CreateAgentRequest, request: Request):
        """Spawn a new agent container for the current user."""
        user = await get_current_user(request)

        # Check if user already has an agent
        existing = await _db.get_agent_by_user(user["id"])
        if existing:
            raise HTTPException(409, "You already have an agent. Delete it first to create a new one.")

        # Check total agent count
        total = await _db.count_agents()
        if total >= config.max_agents:
            raise HTTPException(503, "Maximum number of agents reached. Please try again later.")

        # Get used ports
        all_agents = await _db.list_all_agents()
        used_ports = {a["port"] for a in all_agents if a["port"]}

        try:
            # Spawn container
            result = await containers.spawn_agent(
                user_id=user["id"],
                agent_name=req.agent_name,
                used_ports=used_ports,
            )

            # Update nginx proxy
            await proxy.add_proxy(user["id"], result["port"])

            # Store in DB
            instance = await _db.create_agent_instance(
                user_id=user["id"],
                container_id=result["container_id"],
                port=result["port"],
                api_token=result["api_token"],
                agent_url=result["agent_url"],
                status="running",
            )

            log.info("agent_created", user_id=user["id"], url=result["agent_url"])

            return {
                "ok": True,
                "agent_url": result["agent_url"],
                "api_token": result["api_token"],
                "status": "running",
                "instance_id": instance["id"],
            }

        except RuntimeError as e:
            raise HTTPException(503, str(e))
        except Exception as e:
            log.error("agent_create_error", error=str(e))
            raise HTTPException(500, f"Failed to create agent: {e}")

    @app.get("/agents/mine")
    async def get_my_agent(request: Request):
        """Get current user's agent info."""
        user = await get_current_user(request)
        agent = await _db.get_agent_by_user(user["id"])

        if not agent:
            return {"has_agent": False}

        # Check container health
        health = {"status": "unknown", "running": False}
        if agent.get("container_id"):
            try:
                health = await containers.health_check(agent["container_id"])
            except Exception:
                pass

        return {
            "has_agent": True,
            "agent_url": agent["agent_url"],
            "api_token": agent["api_token"],
            "status": agent["status"],
            "port": agent["port"],
            "container_health": health,
            "created_at": agent["created_at"],
        }

    @app.delete("/agents/mine")
    async def delete_my_agent(request: Request):
        """Stop and remove current user's agent."""
        user = await get_current_user(request)
        agent = await _db.get_agent_by_user(user["id"])

        if not agent:
            raise HTTPException(404, "No agent found")

        # Stop container
        if agent.get("container_id"):
            await containers.stop_agent(agent["container_id"])

        # Remove nginx proxy
        await proxy.remove_proxy(user["id"])

        # Remove from DB
        await _db.delete_agent_instance(agent["id"])

        log.info("agent_deleted", user_id=user["id"])
        return {"ok": True, "message": "Agent stopped and removed"}

    # ── Admin Endpoints ───────────────────────────────────────

    @app.get("/admin/agents")
    async def admin_list_agents(request: Request):
        """List all agent instances (admin only)."""
        await get_admin_user(request)

        agents = await _db.list_all_agents()
        return {
            "total": len(agents),
            "agents": agents,
        }

    @app.get("/admin/agents/{instance_id}/logs")
    async def admin_agent_logs(instance_id: str, request: Request, tail: int = 100):
        """Get container logs for an agent (admin only)."""
        await get_admin_user(request)

        agent = await _db.get_agent_by_id(instance_id)
        if not agent:
            raise HTTPException(404, "Agent not found")

        if not agent.get("container_id"):
            raise HTTPException(400, "Agent has no container")

        logs = await containers.get_logs(agent["container_id"], tail=tail)
        return {"instance_id": instance_id, "logs": logs}

    @app.post("/admin/agents/{instance_id}/restart")
    async def admin_restart_agent(instance_id: str, request: Request):
        """Restart an agent container (admin only)."""
        await get_admin_user(request)

        agent = await _db.get_agent_by_id(instance_id)
        if not agent:
            raise HTTPException(404, "Agent not found")

        if not agent.get("container_id"):
            raise HTTPException(400, "Agent has no container")

        success = await containers.restart_agent(agent["container_id"])
        if success:
            await _db.update_agent_status(agent["id"], "running")
            return {"ok": True, "message": "Agent restarted"}
        else:
            raise HTTPException(500, "Failed to restart agent")

    # ── Health ────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        """Orchestrator health check."""
        users = await _db.count_users()
        agents = await _db.count_agents()
        return {
            "status": "ok",
            "service": "agent-orchestrator",
            "users": users,
            "agents": agents,
        }

    return app
