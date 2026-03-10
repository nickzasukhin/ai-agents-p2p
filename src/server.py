"""Main FastAPI application — A2A + discovery + negotiation + SSE notifications."""

import asyncio
import json
import time
import structlog
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

from a2a.types import AgentCard
from src.a2a_server.server import build_a2a_app
from src.discovery.loop import DiscoveryLoop
from src.negotiation.manager import NegotiationManager
from src.notification.events import EventBus
from src.discovery.gossip import GossipProtocol
from src.privacy.guard import PrivacyGuard
from src.notification.events import EventType
from src.negotiation.project_manager import ProjectManager
from src.notification.websocket import WSConnectionManager
from src.security.middleware import AuthMiddleware

log = structlog.get_logger()


def create_app(
    agent_card: AgentCard,
    discovery_loop: DiscoveryLoop | None = None,
    negotiation_manager: NegotiationManager | None = None,
    event_bus: EventBus | None = None,
    privacy_guard: PrivacyGuard | None = None,
    storage=None,
    did_manager=None,
    gossip: GossipProtocol | None = None,
    dht_node=None,
    dht_config: dict | None = None,
    data_dir: str | None = None,
    card_config: dict | None = None,
    project_manager: ProjectManager | None = None,
    relay_config: dict | None = None,
    tunnel_info=None,
    own_url: str | None = None,
    config=None,
    chat_manager=None,
) -> FastAPI:
    """Create the FastAPI application with all services mounted."""

    app = FastAPI(
        title=f"Agent Social Network — {agent_card.name}",
        version="0.9.0",
    )

    # Mutable state — card can be regenerated after profile edits
    app.state.agent_card = agent_card
    app.state.card_regenerating = False
    app.state.last_card_rebuild: str | None = None

    # Network state (Phase 6.3)
    app.state.own_url = own_url or agent_card.url
    app.state.tunnel_info = tunnel_info
    app.state.relay_config = relay_config

    # Init relay store if this node is in relay mode
    relay_store = None
    if relay_config and relay_config.get("relay_mode"):
        from src.network.relay import RelayStore
        relay_store = RelayStore()
        log.info("relay_mode_enabled")

    # CORS for frontend
    api_token = config.api_token if config else ""
    cors_origins = config.cors_origins if config else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth middleware (Phase 10) — must be added after CORS
    if api_token:
        app.add_middleware(AuthMiddleware, api_token=api_token)
        log.info("auth_middleware_enabled")

    # ── WebSocket Manager (Phase 6.8) ────────────────────────────
    ws_manager = WSConnectionManager()
    app.state.ws_manager = ws_manager

    # Wire into EventBus
    if event_bus:
        event_bus.ws_manager = ws_manager

    # ── Global Exception Handler (Phase 6.6) ─────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse({"error": "Internal server error"}, status_code=500)

    # ── Rate Limiter (Phase 6.6) ─────────────────────────────────
    _request_counts: dict[str, list[float]] = defaultdict(list)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()
            window = _request_counts[client_ip]
            # Prune entries older than 60s
            window[:] = [t for t in window if now - t < 60]
            rpm = config.rate_limit_rpm if config else 120
            if rpm > 0 and len(window) >= rpm:
                return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
            window.append(now)
        return await call_next(request)

    # ── Safe JSON parser (Phase 6.6) ─────────────────────────────
    async def _safe_json(request: Request) -> tuple[dict | None, JSONResponse | None]:
        """Parse request JSON safely."""
        try:
            body = await request.json()
            return body, None
        except Exception:
            return None, JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # ── HTML escape helper (Phase 12.2) ────────────────────────────
    def _esc(text: str) -> str:
        """Escape HTML special characters for safe embedding."""
        import html as _html_mod
        return _html_mod.escape(str(text), quote=True)

    # ── Card Regeneration (Phase 6.1) ──────────────────────────────
    async def rebuild_agent_card() -> dict:
        """Re-read context files, rebuild Agent Card via LLM, re-sign, re-publish."""
        if not data_dir or not card_config:
            return {"error": "Card config not available"}

        if app.state.card_regenerating:
            return {"status": "already_regenerating"}

        app.state.card_regenerating = True
        old_name = app.state.agent_card.name
        old_skills_count = len(app.state.agent_card.skills)

        try:
            # Step 1: Re-read context from files
            from src.profile.mcp_reader import read_context_from_files
            context = await read_context_from_files(data_dir)
            log.info("card_rebuild_context_read", chars=len(context.raw_text))

            # Step 2: Rebuild card via LLM (sync call → run in executor)
            from src.profile.builder import build_agent_card_from_context
            loop = asyncio.get_event_loop()
            new_card = await loop.run_in_executor(
                None,
                build_agent_card_from_context,
                context,
                card_config["agent_name"],
                card_config["agent_url"],
                card_config.get("llm"),
            )
            log.info("card_rebuilt", name=new_card.name, skills=len(new_card.skills))

            # Step 3: Update in-memory card
            app.state.agent_card = new_card

            # Step 4: Update discovery loop context
            if discovery_loop:
                discovery_loop.own_context_raw = context.raw_text

            # Step 5: Re-sign and re-publish to DHT
            if dht_node and did_manager and dht_config:
                new_agent_info = {
                    "url": card_config["agent_url"],
                    "name": new_card.name,
                    "did": did_manager.did,
                    "skills_summary": ", ".join(s.name for s in new_card.skills),
                }
                # Update DHT config for future re-publishes
                dht_config["agent_info"] = new_agent_info
                if discovery_loop:
                    discovery_loop.dht_agent_info = new_agent_info
                try:
                    await dht_node.publish(did_manager.did, new_agent_info)
                    log.info("card_rebuild_dht_published")
                except Exception as e:
                    log.warning("card_rebuild_dht_error", error=str(e))

            # Step 6: Emit event
            if event_bus:
                event_bus.emit(
                    event_type=EventType.CARD_REGENERATED,
                    data={
                        "old_name": old_name,
                        "new_name": new_card.name,
                        "old_skills": old_skills_count,
                        "new_skills": len(new_card.skills),
                        "skills": [s.name for s in new_card.skills],
                    },
                )

            app.state.last_card_rebuild = datetime.now(timezone.utc).isoformat()
            result = {
                "status": "rebuilt",
                "old_name": old_name,
                "new_name": new_card.name,
                "old_skills": old_skills_count,
                "new_skills": len(new_card.skills),
                "skills": [s.name for s in new_card.skills],
                "rebuilt_at": app.state.last_card_rebuild,
            }
            log.info("card_regeneration_complete", **result)
            return result

        except Exception as e:
            log.error("card_rebuild_error", error=str(e))
            return {"error": str(e)}
        finally:
            app.state.card_regenerating = False

    # ── Health check ──────────────────────────────────────────────
    @app.get("/health")
    async def health():
        card = app.state.agent_card
        healthy = True
        checks = {}

        # Storage health check
        if storage:
            storage_health = await storage.health_check()
            checks["storage"] = storage_health
            if not storage_health.get("healthy"):
                healthy = False

        result = {
            "status": "ok" if healthy else "degraded",
            "agent": card.name,
            "skills": len(card.skills),
            "version": card.version,
            "did": did_manager.did if did_manager else None,
            "card_regenerating": app.state.card_regenerating,
            "checks": checks,
        }
        if discovery_loop:
            result["discovery"] = discovery_loop.get_status()
        if negotiation_manager:
            result["negotiations"] = negotiation_manager.get_status()
        if event_bus:
            result["events"] = {
                "total": event_bus.total_events,
                "subscribers": event_bus.subscriber_count,
            }
        if project_manager:
            result["projects"] = project_manager.get_status()
        result["websocket"] = ws_manager.get_stats()
        return result

    # ── Agent Card info (Phase 6.1) ──────────────────────────────
    @app.get("/card")
    async def get_card():
        """Return current Agent Card summary."""
        card = app.state.agent_card
        return {
            "name": card.name,
            "description": card.description,
            "url": card.url,
            "skills": [
                {"id": s.id, "name": s.name, "description": s.description, "tags": s.tags}
                for s in (card.skills or [])
            ],
            "last_rebuild": app.state.last_card_rebuild,
            "regenerating": app.state.card_regenerating,
        }

    @app.post("/card/rebuild")
    async def trigger_card_rebuild():
        """Manually trigger Agent Card regeneration."""
        return await rebuild_agent_card()

    # ── Identity API (Phase 5.2 — DID) ─────────────────────────────
    @app.get("/identity")
    async def identity():
        """Return the agent's DID identity and signed Agent Card."""
        if not did_manager:
            return JSONResponse({"error": "DID identity not configured"}, status_code=503)
        # Build signed card on each request (card may change)
        card = app.state.agent_card
        card_dict = json.loads(card.model_dump_json())
        signed = did_manager.sign_card(card_dict)
        return {
            "did": did_manager.did,
            "public_key": did_manager.public_key_b64,
            "signed_card": signed,
        }

    # ── Profile API (Phase 5.5) ─────────────────────────────────────
    PROFILE_FILES = ["profile.md", "skills.md", "needs.md"]

    @app.get("/profile")
    async def get_profile():
        """Return the agent's profile files."""
        if not data_dir:
            return {"error": "Data directory not configured"}
        ctx_dir = Path(data_dir) / "context"
        files = {}
        for fname in PROFILE_FILES:
            fpath = ctx_dir / fname
            if fpath.exists():
                files[fname] = fpath.read_text(encoding="utf-8")
            else:
                files[fname] = ""
        return {
            "data_dir": data_dir,
            "files": files,
            "did": did_manager.did if did_manager else None,
        }

    @app.put("/profile/{filename}")
    async def update_profile(filename: str, request: Request):
        """Update a profile file and trigger Agent Card regeneration."""
        if not data_dir:
            return JSONResponse({"error": "Data directory not configured"}, status_code=503)
        if filename not in PROFILE_FILES:
            return JSONResponse({"error": f"Invalid file: {filename}. Must be one of {PROFILE_FILES}"}, status_code=400)
        body, err = await _safe_json(request)
        if err:
            return err
        content = body.get("content", "")
        fpath = Path(data_dir) / "context" / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
        log.info("profile_updated", file=filename, chars=len(content))

        # Auto-regenerate Agent Card after profile edit
        rebuild_result = None
        if card_config:
            rebuild_result = await rebuild_agent_card()

        return {
            "status": "ok",
            "file": filename,
            "chars": len(content),
            "card_rebuild": rebuild_result,
        }

    # ── Gossip API (Phase 5.3) ──────────────────────────────────────
    @app.get("/gossip/peers")
    async def gossip_peers():
        """Return the list of known peers for gossip exchange."""
        if not gossip:
            return {"peers": [], "error": "Gossip not configured"}
        return {"peers": gossip.get_peer_list()}

    @app.post("/gossip/peers")
    async def gossip_receive(request: Request):
        """Receive a peer list from another agent, merge and return ours."""
        if not gossip:
            return JSONResponse({"peers": [], "error": "Gossip not configured"}, status_code=503)
        body, err = await _safe_json(request)
        if err:
            return err
        source_url = body.get("source", "unknown")
        their_peers = body.get("peers", [])

        # Also add the sender itself as a potential peer
        if source_url and source_url != "unknown":
            their_peers.append({"url": source_url})

        new_peers = gossip.merge_peer_list(their_peers, source_url)
        return {
            "peers": gossip.get_peer_list(),
            "new_peers_added": len(new_peers),
        }

    @app.get("/gossip/stats")
    async def gossip_stats():
        """Return gossip statistics."""
        if not gossip:
            return {"error": "Gossip not configured"}
        return gossip.get_stats()

    # ── DHT API (Phase 5.4) ─────────────────────────────────────────
    @app.get("/dht/stats")
    async def dht_stats():
        """Return DHT node statistics."""
        if not dht_node:
            return {"error": "DHT not configured"}
        return dht_node.get_stats()

    @app.get("/dht/lookup/{did}")
    async def dht_lookup(did: str):
        """Look up an agent by DID in the DHT."""
        if not dht_node:
            return {"error": "DHT not configured"}
        result = await dht_node.lookup(did)
        if result:
            return {"found": True, "agent": result}
        return {"found": False}

    # ── Discovery API (Phase 2) ───────────────────────────────────
    @app.get("/discovery/status")
    async def discovery_status():
        if not discovery_loop:
            return {"error": "Discovery not configured"}
        return discovery_loop.get_status()

    @app.get("/discovery/agents")
    async def discovered_agents():
        if not discovery_loop:
            return {"agents": []}
        agents = discovery_loop.get_discovered_agents()
        return {
            "count": len(agents),
            "agents": [
                {
                    "url": a.url,
                    "name": a.card.name,
                    "description": a.card.description,
                    "did": getattr(a, "did", ""),
                    "verified": getattr(a, "verified", False),
                    "skills": [
                        {"name": s.name, "description": s.description, "tags": s.tags}
                        for s in (a.card.skills or [])
                    ],
                }
                for a in agents
            ],
        }

    @app.get("/discovery/matches")
    async def matches():
        if not discovery_loop:
            return {"matches": []}
        match_list = discovery_loop.get_matches()
        return {
            "count": len(match_list),
            "matches": [
                {
                    "agent_url": m.agent_url,
                    "agent_name": m.agent_name,
                    "overall_score": round(m.overall_score, 4),
                    "is_mutual": m.is_mutual,
                    "description": m.their_description[:200],
                    "score_breakdown": m.score_breakdown.to_dict() if m.score_breakdown else None,
                    "top_matches": [
                        {
                            "our_text": sm.our_text,
                            "their_text": sm.their_text,
                            "similarity": round(sm.similarity, 4),
                            "direction": sm.direction,
                        }
                        for sm in m.skill_matches[:5]
                    ],
                }
                for m in match_list
            ],
        }

    @app.post("/discovery/run")
    async def run_discovery():
        if not discovery_loop:
            return {"error": "Discovery not configured"}
        results = await discovery_loop.run_once()
        # Push updated matches and health via WebSocket
        await _ws_push_matches()
        await _ws_push_health()
        return {
            "status": "completed",
            "matches_found": len(results),
            "matches": [
                {
                    "agent_name": m.agent_name,
                    "score": round(m.overall_score, 4),
                    "is_mutual": m.is_mutual,
                }
                for m in results
            ],
        }

    # ── Negotiation API (Phase 3) ────────────────────────────────
    @app.get("/negotiations")
    async def list_negotiations():
        """List all negotiations."""
        if not negotiation_manager:
            return {"negotiations": []}
        negs = negotiation_manager.get_all_negotiations()
        return {
            "count": len(negs),
            "status": negotiation_manager.get_status(),
            "negotiations": [n.to_dict() for n in negs],
        }

    @app.post("/negotiations/start")
    async def start_negotiation():
        """Start negotiations with all current matches."""
        if not negotiation_manager or not discovery_loop:
            return {"error": "Negotiation or discovery not configured"}

        match_list = discovery_loop.get_matches()
        started = []
        for match in match_list:
            try:
                neg = await negotiation_manager.start_negotiation(match)
                started.append({
                    "negotiation_id": neg.id,
                    "peer": match.agent_name,
                    "score": round(match.overall_score, 4),
                    "state": neg.state.value,
                })
            except Exception as e:
                log.error("negotiation_start_error", peer=match.agent_name, error=str(e))

        await _ws_push_negotiations()
        await _ws_push_health()
        return {
            "status": "ok",
            "started": len(started),
            "negotiations": started,
        }

    @app.post("/negotiations/start-one")
    async def start_single_negotiation(request: Request):
        """Start negotiation with a single matched agent by URL."""
        if not negotiation_manager or not discovery_loop:
            return JSONResponse({"error": "Negotiation or discovery not configured"}, 400)

        body = await request.json()
        agent_url = body.get("agent_url", "").rstrip("/")
        if not agent_url:
            return JSONResponse({"error": "agent_url required"}, 400)

        match_list = discovery_loop.get_matches()
        match = next((m for m in match_list if m.agent_url.rstrip("/") == agent_url), None)
        if not match:
            return JSONResponse({"error": "Agent not found in current matches"}, 404)

        try:
            neg = await negotiation_manager.start_negotiation(match)
            await _ws_push_negotiations()
            await _ws_push_health()
            return {
                "status": "ok",
                "negotiation_id": neg.id,
                "peer": match.agent_name,
                "state": neg.state.value,
            }
        except Exception as e:
            return JSONResponse({"error": str(e)}, 409)

    @app.post("/negotiations/{negotiation_id}/send")
    async def send_negotiation_message(negotiation_id: str):
        """Send the current negotiation proposal to the peer agent via A2A."""
        if not negotiation_manager:
            return {"error": "Negotiation not configured"}

        neg = negotiation_manager.get_negotiation(negotiation_id)
        if not neg:
            return JSONResponse({"error": f"Negotiation {negotiation_id} not found"}, status_code=404)

        if not neg.messages:
            return JSONResponse({"error": "No messages to send"}, status_code=400)

        # Get the latest message from us to send
        our_messages = [m for m in neg.messages if m.sender == neg.our_url]
        if not our_messages:
            return JSONResponse({"error": "No outgoing messages to send"}, status_code=400)

        latest = our_messages[-1]

        # Send via A2A to the peer
        import httpx
        a2a_payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": f"neg-{neg.id}-{neg.current_round}",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": json.dumps({
                        "negotiation": True,
                        "negotiation_id": neg.id,
                        "sender_url": neg.our_url,
                        "sender_name": neg.our_name,
                        "message": latest.content,
                    })}],
                    "messageId": f"msg-{neg.id}-{neg.current_round}",
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    neg.their_url.rstrip("/") + "/",
                    json=a2a_payload,
                    headers={"Content-Type": "application/json"},
                )
                resp_data = resp.json()

                # Parse A2A JSON-RPC response
                # Format: result.parts[].kind=="text" with .text field
                response_text = ""
                result = resp_data.get("result", {})
                if isinstance(result, dict):
                    parts = result.get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            response_text = text
                            break

                # If we got a negotiation response, process it
                if response_text:
                    try:
                        resp_neg = json.loads(response_text)
                        if resp_neg.get("negotiation"):
                            # Process their response
                            result = await negotiation_manager.handle_incoming_message(
                                sender_url=resp_neg.get("sender_url", neg.their_url),
                                sender_name=resp_neg.get("sender_name", neg.their_name),
                                message=resp_neg.get("message", response_text),
                                negotiation_id=neg.id,
                            )
                            return {
                                "status": "sent_and_response_received",
                                "their_action": result.get("action", ""),
                                "their_response": result.get("response_text", "")[:200],
                                "negotiation_state": neg.state.value,
                                "negotiation": neg.to_dict(),
                            }
                    except json.JSONDecodeError:
                        pass

                return {
                    "status": "sent",
                    "response_raw": response_text[:200] if response_text else "no text in response",
                    "negotiation_state": neg.state.value,
                }

        except Exception as e:
            log.error("negotiation_send_error", error=str(e), peer=neg.their_url)
            return {"error": f"Failed to send: {str(e)}"}

    @app.get("/negotiations/pending")
    async def pending_approvals():
        """Get negotiations waiting for owner approval."""
        if not negotiation_manager:
            return {"pending": []}
        pending = negotiation_manager.get_pending_approvals()
        return {
            "count": len(pending),
            "pending": [n.to_dict() for n in pending],
        }

    @app.get("/negotiations/{negotiation_id}")
    async def get_negotiation(negotiation_id: str):
        """Get a specific negotiation by ID."""
        if not negotiation_manager:
            return JSONResponse({"error": "Negotiation not configured"}, status_code=503)
        neg = negotiation_manager.get_negotiation(negotiation_id)
        if not neg:
            return JSONResponse({"error": f"Negotiation {negotiation_id} not found"}, status_code=404)
        return neg.to_dict()

    @app.post("/negotiations/{negotiation_id}/approve")
    async def approve_negotiation(negotiation_id: str):
        """Owner approves a negotiation."""
        if not negotiation_manager:
            return {"error": "Negotiation not configured"}
        result = await negotiation_manager.owner_decision(negotiation_id, "approve")
        if project_manager:
            for p in project_manager.get_all_projects():
                for role in p.roles:
                    if role.negotiation_id == negotiation_id:
                        await project_manager.sync(p.id)
                        break
        # Auto-start chat after confirmed (Phase 9)
        if chat_manager and result.get("status") == "confirmed":
            neg = negotiation_manager.get_negotiation(negotiation_id)
            if neg:
                asyncio.ensure_future(_start_chat_after_confirm(neg))
        await _ws_push_negotiations()
        await _ws_push_health()
        return result

    @app.post("/negotiations/{negotiation_id}/reject")
    async def reject_negotiation(negotiation_id: str):
        """Owner rejects a negotiation."""
        if not negotiation_manager:
            return {"error": "Negotiation not configured"}
        result = await negotiation_manager.owner_decision(negotiation_id, "reject")
        if project_manager:
            for p in project_manager.get_all_projects():
                for role in p.roles:
                    if role.negotiation_id == negotiation_id:
                        await project_manager.sync(p.id)
                        break
        await _ws_push_negotiations()
        await _ws_push_health()
        return result

    # ── Projects API (Phase 6.4) ────────────────────────────────
    @app.get("/projects")
    async def list_projects():
        """List all multi-agent collaboration projects."""
        if not project_manager:
            return {"projects": []}
        projects = project_manager.get_all_projects()
        return {
            "count": len(projects),
            "status": project_manager.get_status(),
            "projects": [p.to_dict() for p in projects],
        }

    @app.post("/projects")
    async def create_project(request: Request):
        """Create a new project with roles."""
        if not project_manager:
            return JSONResponse({"error": "Project manager not configured"}, status_code=503)
        body, err = await _safe_json(request)
        if err:
            return err
        name = body.get("name", "Untitled Project")
        description = body.get("description", "")
        roles = body.get("roles", [])
        if not roles:
            return JSONResponse({"error": "At least one role required"}, status_code=400)
        project = project_manager.create_project(name, description, roles)
        await project_manager._persist(project)
        return project.to_dict()

    @app.post("/projects/suggest")
    async def suggest_project():
        """LLM suggests a project based on current matches."""
        if not project_manager or not discovery_loop:
            return {"error": "Project manager or discovery not configured"}
        match_list = discovery_loop.get_matches()
        matches_data = [
            {
                "agent_url": m.agent_url,
                "agent_name": m.agent_name,
                "overall_score": m.overall_score,
                "description": m.their_description[:200],
            }
            for m in match_list
        ]
        return await project_manager.suggest_project(matches_data)

    @app.get("/projects/{project_id}")
    async def get_project(project_id: str):
        """Get project details with role status."""
        if not project_manager:
            return {"error": "Project manager not configured"}
        project = project_manager.get_project(project_id)
        if not project:
            return JSONResponse({"error": f"Project {project_id} not found"}, status_code=404)
        return project.to_dict()

    @app.post("/projects/{project_id}/recruit")
    async def recruit_project(project_id: str):
        """Start negotiations for unfilled project roles."""
        if not project_manager:
            return {"error": "Project manager not configured"}
        return await project_manager.recruit(project_id)

    @app.post("/projects/{project_id}/sync")
    async def sync_project(project_id: str):
        """Sync negotiation statuses into project role statuses."""
        if not project_manager:
            return {"error": "Project manager not configured"}
        return await project_manager.sync(project_id)

    @app.post("/projects/{project_id}/complete")
    async def complete_project(project_id: str):
        """Mark project as completed."""
        if not project_manager:
            return {"error": "Project manager not configured"}
        return await project_manager.complete(project_id)

    # ── Chat API (Phase 9) ──────────────────────────────────────

    async def _start_chat_after_confirm(neg) -> None:
        """Background task: start chat after negotiation is confirmed."""
        try:
            neg_info = {
                "id": neg.id,
                "their_url": neg.their_url,
                "their_name": neg.their_name,
                "our_name": neg.our_name,
                "collaboration_summary": neg.collaboration_summary,
            }
            await chat_manager.start_chat(neg_info)
            await _ws_push_chat()
        except Exception as e:
            log.error("chat_auto_start_error", error=str(e), neg_id=neg.id)

    @app.get("/chats")
    async def list_chats():
        """List all chat channels (confirmed negotiations)."""
        if not chat_manager:
            return {"chats": []}
        chats = await chat_manager.get_chats()
        return {"chats": chats, "chat_mode": chat_manager.chat_mode}

    @app.get("/chats/{negotiation_id}/messages")
    async def get_chat_messages(negotiation_id: str):
        """Get chat message history for a negotiation."""
        if not chat_manager:
            return {"messages": []}
        messages = await chat_manager.get_messages(negotiation_id)
        return {"messages": messages, "count": len(messages)}

    @app.post("/chats/{negotiation_id}/send")
    async def send_chat_message(negotiation_id: str, request: Request):
        """Owner sends a chat message (manual mode or 'Join' in auto mode)."""
        if not chat_manager:
            return JSONResponse({"error": "Chat not configured"}, status_code=503)
        body, err = await _safe_json(request)
        if err:
            return err
        text = body.get("message", "").strip()
        if not text:
            return JSONResponse({"error": "Message text required"}, status_code=400)

        # Get peer URL from negotiation
        their_url = ""
        if negotiation_manager:
            neg = negotiation_manager.get_negotiation(negotiation_id)
            if neg:
                their_url = neg.their_url

        msg = await chat_manager.send_owner_message(negotiation_id, text, their_url)
        await _ws_push_chat()
        return msg

    @app.post("/chats/{negotiation_id}/start")
    async def start_chat(negotiation_id: str):
        """Manually start a chat for a confirmed negotiation."""
        if not chat_manager:
            return JSONResponse({"error": "Chat not configured"}, status_code=503)
        if not negotiation_manager:
            return JSONResponse({"error": "Negotiation not configured"}, status_code=503)
        neg = negotiation_manager.get_negotiation(negotiation_id)
        if not neg:
            return JSONResponse({"error": f"Negotiation {negotiation_id} not found"}, status_code=404)
        neg_info = {
            "id": neg.id,
            "their_url": neg.their_url,
            "their_name": neg.their_name,
            "our_name": neg.our_name,
            "collaboration_summary": neg.collaboration_summary,
        }
        msg = await chat_manager.start_chat(neg_info)
        await _ws_push_chat()
        if msg:
            return msg
        return {"status": "chat_already_started_or_manual_mode"}

    # ── WebSocket Endpoint (Phase 6.8) ─────────────────────────
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        client = await ws_manager.connect(websocket)

        # Send initial agent info
        card = app.state.agent_card
        await websocket.send_json({
            "type": "state",
            "channel": "health",
            "data": {
                "agent": card.name,
                "skills": len(card.skills),
                "version": card.version,
            },
        })

        try:
            while True:
                raw = await websocket.receive_text()
                await ws_manager.handle_message(client, raw)
        except WebSocketDisconnect:
            ws_manager.disconnect(client)
        except Exception:
            ws_manager.disconnect(client)

    # ── WebSocket state push helpers (Phase 6.8) ─────────────────

    async def _ws_push_matches():
        """Push current matches to WS subscribers."""
        if not discovery_loop or ws_manager.client_count == 0:
            return
        match_list = discovery_loop.get_matches()
        await ws_manager.push_state("matches", [
            {
                "agent_url": m.agent_url,
                "agent_name": m.agent_name,
                "overall_score": round(m.overall_score, 4),
                "is_mutual": m.is_mutual,
                "description": m.their_description[:200],
                "score_breakdown": m.score_breakdown.to_dict() if m.score_breakdown else None,
                "top_matches": [
                    {
                        "our_text": sm.our_text,
                        "their_text": sm.their_text,
                        "similarity": round(sm.similarity, 4),
                        "direction": sm.direction,
                    }
                    for sm in m.skill_matches[:5]
                ],
            }
            for m in match_list
        ])

    async def _ws_push_negotiations():
        """Push current negotiations to WS subscribers."""
        if not negotiation_manager or ws_manager.client_count == 0:
            return
        negs = negotiation_manager.get_all_negotiations()
        await ws_manager.push_state("negotiations", [n.to_dict() for n in negs])

    async def _ws_push_chat():
        """Push chat update to WS subscribers."""
        if not chat_manager or ws_manager.client_count == 0:
            return
        chats = await chat_manager.get_chats()
        await ws_manager.push_state("chat", chats)

    async def _ws_push_health():
        """Push health state to WS subscribers."""
        if ws_manager.client_count == 0:
            return
        card = app.state.agent_card
        data = {
            "status": "ok",
            "agent": card.name,
            "skills": len(card.skills),
            "version": card.version,
        }
        if discovery_loop:
            data["discovery"] = discovery_loop.get_status()
        if negotiation_manager:
            data["negotiations"] = negotiation_manager.get_status()
        if event_bus:
            data["events"] = {
                "total": event_bus.total_events,
                "subscribers": event_bus.subscriber_count,
            }
        if project_manager:
            data["projects"] = project_manager.get_status()
        await ws_manager.push_state("health", data)

    # ── AG-UI SSE Notifications (Phase 3) ────────────────────────
    @app.get("/events/stream")
    async def event_stream(request: Request):
        """SSE endpoint for real-time AG-UI notifications."""
        if not event_bus:
            return {"error": "Event bus not configured"}

        last_id = int(request.headers.get("Last-Event-ID", "0"))

        async def generate():
            async for event in event_bus.subscribe(last_event_id=last_id):
                if await request.is_disconnected():
                    break
                yield event.to_sse()

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/events/recent")
    async def recent_events():
        """Get recent events (for polling fallback)."""
        if not event_bus:
            return {"events": []}
        events = event_bus.get_recent_events(50)
        return {
            "count": len(events),
            "events": [e.to_dict() for e in events],
        }

    # ── Network Status (Phase 6.3) ───────────────────────────────
    @app.get("/network/status")
    async def network_status():
        """Return the agent's network configuration and reachability info."""
        result = {
            "own_url": app.state.own_url,
            "is_localhost": "localhost" in app.state.own_url or "127.0.0.1" in app.state.own_url,
            "tunnel": app.state.tunnel_info.to_dict() if app.state.tunnel_info else None,
            "relay_mode": relay_store is not None,
            "relay_url": (relay_config or {}).get("relay_url"),
        }
        return result

    @app.post("/network/check")
    async def network_check():
        """Actively check if this agent is reachable at its public URL."""
        from src.network.address import check_reachability
        card = app.state.agent_card
        result = await check_reachability(
            app.state.own_url,
            expected_agent_name=card.name,
        )
        return result

    # ── Go Online (Phase 12.4) ──────────────────────────────────
    @app.post("/network/go-online")
    async def go_online():
        """One-click: start tunnel → update URL → re-sign card → register → discover.

        Tries tunnel providers in order: bore → cloudflared → ngrok.
        Falls back to current URL if no tunnel available.
        """
        from src.network.tunnel import start_tunnel, TunnelInfo
        from src.discovery.registry_client import RegistryClient

        current_url = app.state.own_url
        tunnel_provider = None
        public_url = current_url
        tunnel_started = False

        # Skip tunnel if already on a public URL
        is_local = "localhost" in current_url or "127.0.0.1" in current_url
        existing_tunnel = app.state.tunnel_info

        if is_local and not existing_tunnel:
            # Try tunnel providers in order
            local_port = config.port if config else 9000
            for provider in ["bore", "cloudflared", "ngrok"]:
                log.info("go_online_trying_tunnel", provider=provider)
                tunnel = await start_tunnel(provider, local_port)
                if tunnel:
                    public_url = tunnel.public_url
                    tunnel_provider = provider
                    tunnel_started = True
                    app.state.tunnel_info = tunnel
                    app.state.own_url = public_url
                    log.info("go_online_tunnel_ready", provider=provider, url=public_url)
                    break
        elif existing_tunnel:
            public_url = existing_tunnel.public_url
            tunnel_provider = existing_tunnel.provider
            tunnel_started = True

        # Update agent card URL if it changed
        if public_url != app.state.agent_card.url:
            import json as json_mod
            card_dict = json_mod.loads(app.state.agent_card.model_dump_json())
            card_dict["url"] = public_url
            from a2a.types import AgentCard as AgentCardType
            app.state.agent_card = AgentCardType(**card_dict)
            log.info("go_online_card_url_updated", new_url=public_url)

            # Re-sign card with DID if available
            if did_manager:
                try:
                    card_dict_updated = json_mod.loads(app.state.agent_card.model_dump_json())
                    signed = did_manager.sign_card(card_dict_updated)
                    log.info("go_online_card_re_signed")
                except Exception as e:
                    log.warning("go_online_sign_failed", error=str(e))

        # Register with registries
        registered_registries: list[str] = []
        registry_client = RegistryClient()

        # Register with configured registries
        if config and config.registry_urls:
            for reg_url in config.registry_urls:
                try:
                    ok = await registry_client.register(reg_url, public_url)
                    if ok:
                        registered_registries.append(reg_url)
                except Exception as e:
                    log.warning("go_online_register_failed", registry=reg_url, error=str(e))

        # Register with a2aregistry.org
        if config and config.a2a_registry_enabled and not is_local:
            try:
                ok = await registry_client.register_a2a_global(public_url)
                if ok:
                    registered_registries.append("https://a2aregistry.org")
            except Exception as e:
                log.warning("go_online_a2a_register_failed", error=str(e))

        # Trigger discovery run
        discovery_triggered = False
        if discovery_loop:
            try:
                discovery_loop.run_once()
                discovery_triggered = True
            except Exception as e:
                log.warning("go_online_discovery_failed", error=str(e))

        result = {
            "status": "online" if tunnel_started or not is_local else "local_only",
            "public_url": public_url,
            "tunnel_provider": tunnel_provider,
            "tunnel_started": tunnel_started,
            "registered_registries": registered_registries,
            "discovery_triggered": discovery_triggered,
        }

        log.info("go_online_complete", **result)
        return result

    @app.get("/network/go-online/status")
    async def go_online_status():
        """Check current online status."""
        tunnel = app.state.tunnel_info
        current_url = app.state.own_url
        is_local = "localhost" in current_url or "127.0.0.1" in current_url

        return {
            "is_online": not is_local or (tunnel is not None),
            "public_url": tunnel.public_url if tunnel else current_url,
            "tunnel_active": tunnel is not None and tunnel.to_dict().get("running", False),
            "tunnel_provider": tunnel.provider if tunnel else None,
        }

    # ── Global Search (Phase 12.5) ──────────────────────────────
    @app.get("/search")
    async def search_agents(q: str = "", limit: int = 20):
        """Search agents by natural language query across local + registries.

        Query params:
            q: search query text
            limit: max results (default 20)
        """
        if not q.strip():
            return {"query": "", "results": [], "total": 0}

        results: list[dict] = []
        limit = min(limit, 100)

        # Search local discovered agents using embeddings
        if discovery_loop and hasattr(discovery_loop, 'discovered_agents'):
            try:
                from src.matching.engine import MatchingEngine
                engine = MatchingEngine()
                agents = list(discovery_loop.discovered_agents.values())
                local_results = engine.search_agents(q, agents, limit=limit)
                for r in local_results:
                    r["source"] = "local"
                results.extend(local_results)
            except Exception as e:
                log.warning("search_local_error", error=str(e))

        # Search registries via API
        if config and config.registry_urls:
            import httpx as httpx_mod
            for reg_url in config.registry_urls:
                try:
                    search_url = f"{reg_url.rstrip('/')}/agents"
                    async with httpx_mod.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(search_url, params={"q": q})
                        if resp.status_code == 200:
                            data = resp.json()
                            for agent in data.get("agents", []):
                                results.append({
                                    "agent_url": agent.get("url", ""),
                                    "agent_name": agent.get("name", ""),
                                    "description": agent.get("description", ""),
                                    "skills": agent.get("skills", []),
                                    "match_score": agent.get("score", 0.5),
                                    "source": reg_url,
                                })
                except Exception as e:
                    log.warning("search_registry_error", registry=reg_url, error=str(e))

        # Deduplicate by agent_url
        seen_urls = set()
        deduped = []
        for r in results:
            url = r.get("agent_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduped.append(r)

        # Sort by match_score descending
        deduped.sort(key=lambda r: r.get("match_score", 0), reverse=True)
        deduped = deduped[:limit]

        return {
            "query": q,
            "results": deduped,
            "total": len(deduped),
        }

    # ── Peer Management (Phase 12.1) ─────────────────────────────
    @app.post("/peers/add")
    async def add_peer(request: Request):
        """Add a peer agent by URL — fetches card, verifies DID, runs matching.

        Body: {"url": "https://some-agent.example.com"}
        """
        body, err = await _safe_json(request)
        if err:
            return err

        peer_url = body.get("url", "").strip().rstrip("/")
        if not peer_url:
            return JSONResponse({"error": "Missing 'url' field"}, status_code=400)

        # Reject adding self
        if own_url and peer_url.rstrip("/") == own_url.rstrip("/"):
            return JSONResponse({"error": "Cannot add self as peer"}, status_code=400)

        # Validate URL format
        if not peer_url.startswith("http://") and not peer_url.startswith("https://"):
            return JSONResponse(
                {"error": "Invalid URL — must start with http:// or https://"},
                status_code=400,
            )

        # Fetch the agent's card
        from src.a2a_client.client import A2AClient
        client = A2AClient(
            timeout=config.http_timeout if config else 10.0,
            own_url=own_url or "",
        )
        try:
            discovered = await client.discover_agents([peer_url])
        except Exception as e:
            log.warning("add_peer_fetch_failed", url=peer_url, error=str(e))
            return JSONResponse(
                {"error": f"Failed to fetch agent card from {peer_url}", "detail": str(e)},
                status_code=502,
            )

        if not discovered:
            return JSONResponse(
                {"error": f"No agent card found at {peer_url}"},
                status_code=404,
            )

        agent = discovered[0]

        # Add to local static registry
        if discovery_loop and discovery_loop.registry:
            discovery_loop.registry.add(peer_url, name=agent.card.name if agent.card else None)
            discovery_loop.registry.save()

        # Run matching if discovery loop available
        match_score = 0.0
        if discovery_loop:
            try:
                matches = discovery_loop.get_matches()
                # Trigger a discovery run to include the new peer
                await discovery_loop.run_once()
                matches = discovery_loop.get_matches()
                for m in matches:
                    if m.get("agent_url", "").rstrip("/") == peer_url.rstrip("/"):
                        match_score = m.get("overall_score", 0.0)
                        break
            except Exception as e:
                log.warning("add_peer_matching_error", error=str(e))

        # Verify DID if available
        did_verified = False
        agent_did = ""
        if agent.did:
            agent_did = agent.did
            did_verified = agent.verified

        result = {
            "status": "added",
            "agent": {
                "name": agent.card.name if agent.card else "Unknown",
                "url": peer_url,
                "did": agent_did,
                "did_verified": did_verified,
                "description": agent.card.description if agent.card else "",
                "skills": [s.name for s in (agent.card.skills or [])] if agent.card else [],
                "match_score": round(match_score, 4),
            },
        }

        if event_bus:
            event_bus.emit(EventType.AGENT_DISCOVERED, {
                "agent_url": peer_url,
                "agent_name": result["agent"]["name"],
                "source": "manual_add",
            })

        log.info("peer_added", url=peer_url, name=result["agent"]["name"], match_score=match_score)
        return result

    # ── Invite Links (Phase 12.2) ────────────────────────────────
    @app.get("/invite/data")
    async def invite_data():
        """Return invite data as JSON for programmatic use."""
        card = app.state.agent_card
        agent_did = did_manager.did if did_manager else ""
        return {
            "agent_name": card.name,
            "description": card.description or "",
            "skills": [
                {"name": s.name, "description": s.description, "tags": s.tags}
                for s in (card.skills or [])
            ],
            "agent_url": app.state.own_url,
            "did": agent_did,
        }

    @app.get("/invite")
    async def invite_page():
        """Render shareable HTML invite page with Open Graph meta tags."""
        card = app.state.agent_card
        agent_url = app.state.own_url
        name = card.name or "AI Agent"
        desc = card.description or "An AI agent on the DevPunks P2P network."
        skills_list = card.skills or []
        skills_text = ", ".join(s.name for s in skills_list[:5])
        if len(skills_list) > 5:
            skills_text += f" +{len(skills_list) - 5} more"

        # Build skill tags HTML
        skill_tags_html = ""
        for s in skills_list[:8]:
            skill_tags_html += (
                f'<span style="display:inline-block;background:#1a1a2e;'
                f'border:1px solid #E50051;border-radius:20px;padding:6px 14px;'
                f'margin:4px;font-size:14px;color:#fff">{_esc(s.name)}</span>\n'
            )

        og_title = f"{name} — DevPunks Agent Network"
        og_desc = desc[:200] if len(desc) > 200 else desc
        if skills_text:
            og_desc = f"{og_desc} | Skills: {skills_text}"
        og_desc = og_desc[:300]

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(og_title)}</title>

<!-- Open Graph / Social Preview -->
<meta property="og:type" content="website">
<meta property="og:title" content="{_esc(og_title)}">
<meta property="og:description" content="{_esc(og_desc)}">
<meta property="og:url" content="{_esc(agent_url)}/invite">
<meta property="og:site_name" content="DevPunks Agent Network">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{_esc(og_title)}">
<meta name="twitter:description" content="{_esc(og_desc)}">

<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
    background: #0a0a0f;
    color: #fff;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }}
  .card {{
    background: #12121a;
    border: 1px solid #1a1a2e;
    border-radius: 16px;
    max-width: 480px;
    width: 100%;
    padding: 40px 32px;
    text-align: center;
  }}
  .logo {{
    color: #E50051;
    font-size: 14px;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 24px;
  }}
  .agent-name {{
    font-size: 28px;
    font-weight: 700;
    margin-bottom: 12px;
  }}
  .description {{
    color: #8888aa;
    font-size: 16px;
    line-height: 1.5;
    margin-bottom: 24px;
  }}
  .skills {{
    margin-bottom: 28px;
  }}
  .skills-label {{
    color: #555570;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 10px;
  }}
  .connect-btn {{
    display: inline-block;
    background: #E50051;
    color: #fff;
    text-decoration: none;
    padding: 14px 36px;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    transition: background 0.2s;
  }}
  .connect-btn:hover {{ background: #FF1A6C; }}
  .url {{
    color: #555570;
    font-size: 12px;
    margin-top: 16px;
    word-break: break-all;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">DevPunks Agent Network</div>
  <h1 class="agent-name">{_esc(name)}</h1>
  <p class="description">{_esc(desc)}</p>
  <div class="skills">
    <div class="skills-label">Skills</div>
    {skill_tags_html if skill_tags_html else '<span style="color:#555570">No skills listed</span>'}
  </div>
  <a class="connect-btn" href="{_esc(agent_url)}/.well-known/agent-card.json">
    View Agent Card
  </a>
  <div class="url">{_esc(agent_url)}</div>
</div>
</body>
</html>"""
        return HTMLResponse(content=html)

    # ── Onboarding Interview (Phase 12.3) ────────────────────────
    from src.onboarding.interview import OnboardingInterviewer

    # Try to create LLM provider for onboarding
    _onboarding_llm = None
    if config and config.openai_api_key:
        try:
            from src.llm.factory import LLMFactory
            _onboarding_llm = LLMFactory.create(
                config.llm_provider, api_key=config.openai_api_key, model=config.openai_model
            )
        except Exception as e:
            log.warning("onboarding_llm_init_failed", error=str(e))

    _onboarding = OnboardingInterviewer(llm=_onboarding_llm)

    @app.get("/onboarding/status")
    async def onboarding_status():
        """Check if the agent has been onboarded (has profile files)."""
        if not data_dir:
            return {"has_profile": False, "onboarding_complete": False}
        ctx_dir = Path(data_dir) / "context"
        has_profile = (ctx_dir / "profile.md").exists()
        has_skills = (ctx_dir / "skills.md").exists()
        return {
            "has_profile": has_profile,
            "has_skills": has_skills,
            "onboarding_complete": has_profile and has_skills,
        }

    @app.post("/onboarding/start")
    async def onboarding_start():
        """Start a new onboarding interview session."""
        result = await _onboarding.process_start()
        return result

    @app.post("/onboarding/chat")
    async def onboarding_chat(request: Request):
        """Send a message in the onboarding interview."""
        body, err = await _safe_json(request)
        if err:
            return err

        session_id = body.get("session_id", "")
        message = body.get("message", "").strip()

        if not session_id:
            return JSONResponse({"error": "Missing session_id"}, status_code=400)
        if not message:
            return JSONResponse({"error": "Missing message"}, status_code=400)

        result = await _onboarding.process_message(session_id, message)

        if "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=404)

        return result

    @app.post("/onboarding/confirm")
    async def onboarding_confirm(request: Request):
        """Confirm the generated profile and write files."""
        body, err = await _safe_json(request)
        if err:
            return err

        session_id = body.get("session_id", "")
        if not session_id:
            return JSONResponse({"error": "Missing session_id"}, status_code=400)

        result = await _onboarding.confirm(session_id)

        if "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=400)

        # Write generated files to context directory
        if data_dir and result.get("files"):
            ctx_dir = Path(data_dir) / "context"
            ctx_dir.mkdir(parents=True, exist_ok=True)

            files = result["files"]
            for filename, content in files.items():
                filepath = ctx_dir / filename.replace("_md", ".md").replace("_", ".")
                # Map keys: profile_md → profile.md, skills_md → skills.md, needs_md → needs.md
                if filename == "profile_md":
                    filepath = ctx_dir / "profile.md"
                elif filename == "skills_md":
                    filepath = ctx_dir / "skills.md"
                elif filename == "needs_md":
                    filepath = ctx_dir / "needs.md"
                filepath.write_text(content, encoding="utf-8")
                log.info("onboarding_file_written", file=filepath.name)

            # Rebuild agent card after writing context files
            try:
                rebuild_result = await rebuild_agent_card()
                result["card_rebuilt"] = True
                log.info("onboarding_card_rebuilt")
            except Exception as e:
                log.warning("onboarding_card_rebuild_failed", error=str(e))
                result["card_rebuilt"] = False

        return result

    # ── Relay Endpoints (Phase 6.3) ────────────────────────────────
    if relay_store:
        @app.post("/relay/register")
        async def relay_register(request: Request):
            """Register a NAT'd agent with this relay."""
            body, err = await _safe_json(request)
            if err:
                return err
            agent_did = body.get("did")
            if not agent_did:
                return JSONResponse({"error": "Missing 'did'"}, status_code=400)
            relay_store.register(agent_did, body)
            relay_url = f"{app.state.own_url}/relay/forward/{agent_did}"
            return {"status": "registered", "relay_url": relay_url}

        @app.post("/relay/forward/{agent_did}")
        async def relay_forward(agent_did: str, request: Request):
            """Forward a message to a NAT'd agent (store for pickup)."""
            body, err = await _safe_json(request)
            if err:
                return err
            sender = body.get("sender_url", "unknown")
            success = relay_store.enqueue(agent_did, sender, body)
            return {"status": "queued" if success else "failed"}

        @app.get("/relay/messages/{agent_did}")
        async def relay_messages(agent_did: str):
            """NAT'd agent polls for pending messages."""
            msgs = relay_store.dequeue(agent_did)
            return {"messages": msgs, "count": len(msgs)}

        @app.get("/relay/stats")
        async def relay_stats():
            """Return relay statistics."""
            return relay_store.get_stats()

    # ── Lifecycle events ──────────────────────────────────────────
    @app.on_event("startup")
    async def on_startup():
        if discovery_loop:
            discovery_loop.start()
            log.info("discovery_loop_started_on_startup")
        if dht_node and dht_config:
            bootstrap = dht_config.get("bootstrap_nodes") or None
            await dht_node.start(bootstrap_nodes=bootstrap)
            agent_info = dht_config.get("agent_info", {})
            if agent_info.get("did"):
                await dht_node.publish(agent_info["did"], agent_info)
            log.info("dht_started_on_startup", port=dht_node.udp_port)

        # Register with relay if configured (Phase 6.3)
        if relay_config and relay_config.get("relay_url"):
            import httpx
            relay_url = relay_config["relay_url"].rstrip("/")
            our_did = relay_config.get("our_did", "")
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        f"{relay_url}/relay/register",
                        json={
                            "did": our_did,
                            "name": app.state.agent_card.name,
                            "url": app.state.own_url,
                        },
                    )
                    if resp.status_code == 200:
                        log.info("relay_registered", relay=relay_url, did=our_did[:30])
                    else:
                        log.warning("relay_registration_failed", status=resp.status_code)
            except Exception as e:
                log.warning("relay_registration_error", error=str(e))

        # Periodic WS health push (Phase 6.8) — replaces client-side polling
        async def _ws_health_push_loop():
            while True:
                await asyncio.sleep(30)
                try:
                    await _ws_push_health()
                except Exception:
                    pass

        asyncio.create_task(_ws_health_push_loop())

    @app.on_event("shutdown")
    async def on_shutdown():
        if discovery_loop:
            discovery_loop.stop()
            log.info("discovery_loop_stopped_on_shutdown")
        if dht_node:
            await dht_node.stop()
            log.info("dht_stopped_on_shutdown")
        if storage:
            await storage.close()
            log.info("storage_closed")
        # Stop tunnel if running
        if tunnel_info and tunnel_info.process:
            from src.network.tunnel import stop_tunnel
            await stop_tunnel(tunnel_info)
            log.info("tunnel_stopped_on_shutdown")

    # ── Serve Agent Card (overrides A2A mount for live card) ──────
    @app.get("/.well-known/agent-card.json")
    async def serve_agent_card():
        """Serve the current (possibly regenerated) Agent Card."""
        card = app.state.agent_card
        return JSONResponse(
            content=json.loads(card.model_dump_json()),
            media_type="application/json",
        )

    # ── Optional frontend static serving ────────────────────────
    # When frontend/dist exists (e.g. inside Docker), serve the SPA directly.
    # This enables single-container operation without an external nginx.
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    _serving_frontend = False

    if frontend_dist.is_dir() and (frontend_dist / "index.html").exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

        @app.get("/")
        async def serve_spa_root():
            return FileResponse(str(frontend_dist / "index.html"))

        _serving_frontend = True
        log.info("frontend_static_serving_enabled", path=str(frontend_dist))

    # ── Optional 3D visualization static serving ──────────────────
    viz_dist = Path(__file__).parent.parent / "viz" / "dist"
    if viz_dist.is_dir() and (viz_dist / "index.html").exists():
        viz_assets = viz_dist / "assets"
        if viz_assets.is_dir():
            app.mount("/viz/assets", StaticFiles(directory=str(viz_assets)), name="viz-assets")

        @app.get("/viz")
        @app.get("/viz/{rest_of_path:path}")
        async def serve_viz(rest_of_path: str = ""):
            return FileResponse(str(viz_dist / "index.html"))

        log.info("viz_static_serving_enabled", path=str(viz_dist))

    # ── Mount A2A Starlette app ───────────────────────────────────
    a2a_app = build_a2a_app(
        agent_card,
        negotiation_manager=negotiation_manager,
        privacy_guard=privacy_guard,
        chat_manager=chat_manager,
    )
    app.mount("/", a2a_app)

    log.info(
        "app_created",
        agent=agent_card.name,
        skills=len(agent_card.skills),
        discovery="enabled" if discovery_loop else "disabled",
        negotiation="enabled" if negotiation_manager else "disabled",
        projects="enabled" if project_manager else "disabled",
        events="enabled" if event_bus else "disabled",
        did=did_manager.did if did_manager else "disabled",
        frontend="enabled" if _serving_frontend else "disabled",
    )

    return app
