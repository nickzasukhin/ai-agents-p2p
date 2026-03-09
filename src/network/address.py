"""Network address resolution for NAT traversal.

Resolves the best public URL for an agent using a priority chain:
  1. Explicit --public-url flag (always wins)
  2. STUN/HTTP public IP detection (--detect-ip)
  3. Default localhost (local development)

The STUN client is a minimal implementation (~50 lines) using only
stdlib socket/struct — no external dependencies.
"""

from __future__ import annotations

import asyncio
import os
import socket
import struct

import httpx
import structlog

log = structlog.get_logger()

# Default STUN servers (free, no account needed)
DEFAULT_STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
]

# STUN constants (RFC 5389)
STUN_BINDING_REQUEST = 0x0001
STUN_MAGIC_COOKIE = 0x2112A442
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020
STUN_FAMILY_IPV4 = 0x01


async def detect_public_ip(
    stun_servers: list[tuple[str, int]] | None = None,
) -> str | None:
    """Detect public IP via STUN or HTTP fallback.

    Tries STUN first (UDP, fast, no dependency), then falls back to
    HTTP API (api.ipify.org — free, no rate limits for reasonable use).
    """
    servers = stun_servers or DEFAULT_STUN_SERVERS

    # Try STUN (minimal implementation — just need MAPPED-ADDRESS)
    loop = asyncio.get_event_loop()
    ip = await loop.run_in_executor(None, _stun_query_sync, servers)
    if ip:
        return ip

    # Fallback: HTTP API
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://api.ipify.org")
            if resp.status_code == 200:
                ip = resp.text.strip()
                log.info("public_ip_detected_http", ip=ip)
                return ip
    except Exception as e:
        log.debug("public_ip_http_failed", error=str(e))

    return None


def _stun_query_sync(servers: list[tuple[str, int]]) -> str | None:
    """Minimal STUN BINDING request to get our mapped address.

    STUN RFC 5389 — we send a Binding Request (0x0001) and parse the
    XOR-MAPPED-ADDRESS (0x0020) or MAPPED-ADDRESS (0x0001) from the response.
    No external dependency required.
    """
    txn_id = os.urandom(12)
    header = struct.pack("!HHI", STUN_BINDING_REQUEST, 0x0000, STUN_MAGIC_COOKIE) + txn_id

    for host, port in servers:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            addr = (socket.gethostbyname(host), port)
            sock.sendto(header, addr)
            data, _ = sock.recvfrom(1024)
            sock.close()

            ip = _parse_stun_response(data)
            if ip:
                log.info("public_ip_detected_stun", ip=ip, server=host)
                return ip
        except Exception:
            continue

    return None


def _parse_stun_response(data: bytes) -> str | None:
    """Parse STUN response for XOR-MAPPED-ADDRESS or MAPPED-ADDRESS attribute."""
    if len(data) < 20:
        return None

    # Skip 20-byte STUN header
    offset = 20
    while offset + 4 <= len(data):
        attr_type = struct.unpack("!H", data[offset : offset + 2])[0]
        attr_len = struct.unpack("!H", data[offset + 2 : offset + 4])[0]
        attr_data = data[offset + 4 : offset + 4 + attr_len]

        if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            if family == STUN_FAMILY_IPV4:
                xip = struct.unpack("!I", attr_data[4:8])[0] ^ STUN_MAGIC_COOKIE
                return socket.inet_ntoa(struct.pack("!I", xip))

        elif attr_type == STUN_ATTR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            if family == STUN_FAMILY_IPV4:
                return socket.inet_ntoa(attr_data[4:8])

        # Move to next attribute (padded to 4-byte boundary)
        offset += 4 + ((attr_len + 3) & ~3)

    return None


async def resolve_public_url(
    port: int,
    public_url: str | None = None,
    detect_ip: bool = False,
    stun_servers: list[tuple[str, int]] | None = None,
) -> str:
    """Resolve the best public URL for this agent.

    Priority:
      1. Explicit --public-url flag
      2. STUN/HTTP IP detection (if --detect-ip enabled)
      3. Default localhost

    Returns:
        The resolved URL string (no trailing slash).
    """
    # Priority 1: explicit URL
    if public_url:
        url = public_url.rstrip("/")
        log.info("address_explicit", url=url)
        return url

    # Priority 2: auto-detect public IP
    if detect_ip:
        ip = await detect_public_ip(stun_servers)
        if ip:
            url = f"http://{ip}:{port}"
            log.info("address_auto_detected", url=url)
            return url
        log.warning("address_detect_failed_fallback_localhost")

    # Priority 3: default localhost
    url = f"http://localhost:{port}"
    log.info("address_localhost", url=url)
    return url


async def check_reachability(
    url: str,
    expected_agent_name: str | None = None,
    timeout: float = 5.0,
) -> dict:
    """Check if this agent is reachable at the given URL.

    Makes an HTTP GET to {url}/health and checks the response.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{url.rstrip('/')}/health")
            if resp.status_code == 200:
                data = resp.json()
                reachable = True
                if expected_agent_name:
                    reachable = data.get("agent") == expected_agent_name
                return {
                    "reachable": reachable,
                    "url": url,
                    "agent": data.get("agent"),
                    "latency_ms": round(resp.elapsed.total_seconds() * 1000, 1),
                }
    except Exception as e:
        return {
            "reachable": False,
            "url": url,
            "error": str(e),
        }

    return {"reachable": False, "url": url}
