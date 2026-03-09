"""Tunnel integration for NAT traversal.

Supports:
  - bore   (free, open-source, self-hostable via bore.pub)
  - ngrok  (freemium, widely used)
  - cloudflared (free, Cloudflare Tunnel)

Each tunnel is started as a subprocess and its public URL is parsed from stdout.
No Python dependencies — only requires the tunnel binary on PATH.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass

import structlog

log = structlog.get_logger()


@dataclass
class TunnelInfo:
    """Active tunnel information."""

    provider: str
    public_url: str
    process: asyncio.subprocess.Process | None = None

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "public_url": self.public_url,
            "running": self.process is not None and self.process.returncode is None,
        }


# Regex patterns to extract public URL from tunnel stdout/stderr
TUNNEL_PATTERNS = {
    "bore": re.compile(r"listening at ([\w.\-]+:\d+)"),
    "ngrok": re.compile(r"url=(https?://[\w.\-]+\.ngrok[\w.\-]*/?)"),
    "cloudflared": re.compile(r"(https://[\w.\-]+\.trycloudflare\.com)"),
}


def _build_command(provider: str, local_port: int, bore_server: str) -> list[str] | None:
    """Build the command line for each tunnel provider."""
    commands = {
        "bore": ["bore", "local", str(local_port), "--to", bore_server],
        "ngrok": [
            "ngrok", "http", str(local_port),
            "--log", "stdout", "--log-format", "logfmt",
        ],
        "cloudflared": [
            "cloudflared", "tunnel", "--url", f"http://localhost:{local_port}",
        ],
    }
    return commands.get(provider)


async def start_tunnel(
    provider: str,
    local_port: int,
    bore_server: str = "bore.pub",
    timeout: float = 15.0,
) -> TunnelInfo | None:
    """Start a tunnel and return the public URL.

    Args:
        provider: "bore", "ngrok", or "cloudflared"
        local_port: The local HTTP port to tunnel
        bore_server: Bore relay server (default: bore.pub, free)
        timeout: Seconds to wait for tunnel URL to appear in output
    """
    # Check if the tunnel binary is available
    if not shutil.which(provider):
        log.warning("tunnel_binary_not_found", provider=provider)
        return None

    cmd = _build_command(provider, local_port, bore_server)
    if not cmd:
        log.error("tunnel_unknown_provider", provider=provider)
        return None

    pattern = TUNNEL_PATTERNS.get(provider)
    if not pattern:
        log.error("tunnel_no_pattern", provider=provider)
        return None

    log.info("tunnel_starting", provider=provider, port=local_port)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    # Read output lines until we find the public URL or timeout
    public_url = None
    try:
        async with asyncio.timeout(timeout):
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                log.debug("tunnel_output", line=text)

                match = pattern.search(text)
                if match:
                    raw_url = match.group(1)
                    # bore outputs host:port, needs http:// prefix
                    if provider == "bore" and not raw_url.startswith("http"):
                        public_url = f"http://{raw_url}"
                    else:
                        public_url = raw_url
                    break
    except TimeoutError:
        log.error("tunnel_timeout", provider=provider)
        proc.kill()
        return None

    if public_url:
        log.info("tunnel_ready", provider=provider, url=public_url)
        return TunnelInfo(provider=provider, public_url=public_url, process=proc)

    log.error("tunnel_no_url_found", provider=provider)
    proc.kill()
    return None


async def stop_tunnel(tunnel: TunnelInfo) -> None:
    """Stop a running tunnel process."""
    if tunnel.process and tunnel.process.returncode is None:
        tunnel.process.terminate()
        try:
            await asyncio.wait_for(tunnel.process.wait(), timeout=5.0)
        except TimeoutError:
            tunnel.process.kill()
        log.info("tunnel_stopped", provider=tunnel.provider)
