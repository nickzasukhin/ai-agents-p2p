"""Auth Middleware — Bearer token check on owner-facing endpoints.

Owner endpoints (mutations: POST, PUT, DELETE on /negotiations, /chats,
/profile, /card, /projects, /discovery/run) require a Bearer token.

Peer endpoints (agent-card, gossip, A2A, health, identity, relay) stay open
for inter-agent communication.
"""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = structlog.get_logger()

# Paths that require authentication (owner-facing mutations)
OWNER_PATHS = [
    ("/negotiations/", "POST"),       # approve, reject, start, send
    ("/chats/", "POST"),              # send message
    ("/profile", "PUT"),              # edit profile
    ("/card/rebuild", "POST"),        # rebuild card
    ("/projects", "POST"),            # create project
    ("/discovery/run", "POST"),       # trigger discovery
    ("/events/", "DELETE"),           # clear events
    ("/peers/", "POST"),             # add peer by URL (Phase 12.1)
]

# Paths that are always open (peer-facing / read-only)
OPEN_PREFIXES = [
    "/.well-known/",       # A2A agent card
    "/a2a",                # A2A JSON-RPC
    "/health",             # health check
    "/identity",           # DID identity
    "/gossip",             # gossip protocol
    "/relay/",             # relay endpoints
    "/ws",                 # WebSocket
    "/api/ws",             # WebSocket (via proxy)
]


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token authentication for owner endpoints.

    If api_token is empty, all requests pass through (no auth).
    If api_token is set, owner-facing mutation endpoints require
    Authorization: Bearer <token> header.
    """

    def __init__(self, app, api_token: str = ""):
        super().__init__(app)
        self.api_token = api_token

    async def dispatch(self, request: Request, call_next):
        # No auth configured — pass through
        if not self.api_token:
            return await call_next(request)

        path = request.url.path
        method = request.method

        # Always allow open paths
        for prefix in OPEN_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Allow all GET requests (read-only)
        if method == "GET":
            return await call_next(request)

        # Allow OPTIONS (CORS preflight)
        if method == "OPTIONS":
            return await call_next(request)

        # Check if this is an owner path requiring auth
        requires_auth = False
        for owner_path, owner_method in OWNER_PATHS:
            if owner_path in path and method == owner_method:
                requires_auth = True
                break

        # If not explicitly listed, allow it (peer POST endpoints like gossip)
        if not requires_auth:
            return await call_next(request)

        # Verify Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            log.warning("auth_missing_token", path=path, method=method)
            return JSONResponse(
                status_code=401,
                content={"error": "Authorization required", "detail": "Bearer token missing"},
            )

        token = auth_header[7:]  # Strip "Bearer "
        if token != self.api_token:
            log.warning("auth_invalid_token", path=path, method=method)
            return JSONResponse(
                status_code=403,
                content={"error": "Forbidden", "detail": "Invalid token"},
            )

        return await call_next(request)
