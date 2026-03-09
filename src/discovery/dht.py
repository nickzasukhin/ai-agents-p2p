"""Kademlia DHT — decentralized agent discovery via distributed hash table.

Each agent publishes its Agent Card URL to the DHT under its DID hash key.
Other agents can discover peers by bootstrapping to known nodes and
querying the DHT for known DID→URL mappings.

Flow:
  1. Agent starts → joins DHT via bootstrap node(s)
  2. Agent publishes: set(hash(did), agent_card_url)
  3. Other agents discover by iterating known keys or via gossip+DHT hybrid
  4. Periodically refreshes own record (Kademlia handles TTL)

Integration:
  - Uses DIDManager.node_id() as DHT key (SHA-256 of DID)
  - Runs on a UDP port (default: agent HTTP port + 1000)
  - Works alongside Gossip for maximum connectivity
"""

from __future__ import annotations

import asyncio
import json
import structlog
from datetime import datetime, timezone

from kademlia.network import Server

log = structlog.get_logger()


class DHTNode:
    """Kademlia DHT node for decentralized agent discovery.

    Publishes agent URL and card info to the DHT, and discovers
    other agents by querying known keys.
    """

    def __init__(
        self,
        udp_port: int,
        own_url: str,
        node_id: bytes | None = None,
    ):
        self.udp_port = udp_port
        self.own_url = own_url.rstrip("/")
        self.node_id = node_id
        self._server: Server | None = None
        self._is_running = False
        # Cache of discovered URLs from DHT
        self._discovered: dict[str, dict] = {}  # did_hash_hex → {url, name, ...}

    async def start(self, bootstrap_nodes: list[tuple[str, int]] | None = None) -> None:
        """Start the DHT node and optionally bootstrap to existing nodes.

        Gracefully falls back if UDP port bind fails (Phase 10 — firewall-friendly).

        Args:
            bootstrap_nodes: List of (host, port) tuples for bootstrapping.
        """
        self._server = Server()
        try:
            await self._server.listen(self.udp_port)
        except OSError as e:
            log.warning(
                "dht_udp_bind_failed",
                port=self.udp_port,
                error=str(e),
                msg="DHT disabled — continuing without it. This is normal if UDP is blocked by firewall.",
            )
            self._server = None
            return
        self._is_running = True

        if bootstrap_nodes:
            try:
                await asyncio.wait_for(
                    self._server.bootstrap(bootstrap_nodes),
                    timeout=5.0,
                )
                log.info(
                    "dht_bootstrapped",
                    port=self.udp_port,
                    bootstrap=bootstrap_nodes,
                )
            except asyncio.TimeoutError:
                log.warning("dht_bootstrap_timeout", bootstrap=bootstrap_nodes)
            except Exception as e:
                log.warning("dht_bootstrap_error", error=str(e))
        else:
            log.info("dht_started_standalone", port=self.udp_port)

    async def publish(self, did: str, agent_info: dict) -> None:
        """Publish agent info to the DHT.

        Args:
            did: The agent's DID string (used to derive key).
            agent_info: Dict with {url, name, did, skills_summary}.
        """
        if not self._server:
            log.warning("dht_not_started")
            return

        import hashlib
        key = hashlib.sha256(did.encode()).hexdigest()

        value = json.dumps({
            **agent_info,
            "published_at": datetime.now(timezone.utc).isoformat(),
        })

        await self._server.set(key, value)
        log.info("dht_published", did=did[:30], key=key[:16])

    async def lookup(self, did: str) -> dict | None:
        """Look up an agent by DID in the DHT.

        Args:
            did: The DID to look up.

        Returns:
            Agent info dict or None if not found.
        """
        if not self._server:
            return None

        import hashlib
        key = hashlib.sha256(did.encode()).hexdigest()

        result = await self._server.get(key)
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                log.warning("dht_invalid_value", key=key[:16])
        return None

    async def discover_from_registry(self, known_dids: list[str]) -> list[dict]:
        """Discover agents by looking up known DIDs in the DHT.

        Args:
            known_dids: List of DID strings to look up.

        Returns:
            List of agent info dicts found in DHT.
        """
        if not self._server:
            return []

        found = []
        for did in known_dids:
            info = await self.lookup(did)
            if info:
                found.append(info)
                # Cache
                import hashlib
                key = hashlib.sha256(did.encode()).hexdigest()
                self._discovered[key] = info

        log.info("dht_discovery", queried=len(known_dids), found=len(found))
        return found

    async def stop(self) -> None:
        """Stop the DHT node."""
        if self._server:
            self._server.stop()
            self._is_running = False
            log.info("dht_stopped", port=self.udp_port)

    def get_stats(self) -> dict:
        """Return DHT node statistics."""
        return {
            "is_running": self._is_running,
            "udp_port": self.udp_port,
            "cached_peers": len(self._discovered),
            "own_url": self.own_url,
        }
