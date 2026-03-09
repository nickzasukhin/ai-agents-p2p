"""Gossip Protocol — peer-to-peer exchange of known agent lists.

Each agent periodically shares its known peers with neighbors.
When an agent receives a peer list, it adds new entries to its
local registry, expanding the network organically.

Flow:
  Agent A knows [B]
  Agent B knows [A, C]
  After gossip: Agent A knows [B, C]  ← learned C from B

Endpoints:
  GET  /gossip/peers  → return own peer list
  POST /gossip/peers  → receive peer list from another agent, merge

Production features (Phase 6.6):
  - Peer failure tracking with exponential backoff
  - Skip repeatedly unreachable peers to save resources
"""

from __future__ import annotations

import asyncio
import httpx
import structlog
from datetime import datetime, timezone
from dataclasses import dataclass, field

from src.discovery.registry import StaticRegistry

log = structlog.get_logger()


@dataclass
class GossipStats:
    """Statistics about gossip exchanges."""
    rounds: int = 0
    peers_learned: int = 0
    peers_shared: int = 0
    last_round: str | None = None


class GossipProtocol:
    """Gossip-based peer discovery protocol.

    Periodically exchanges peer lists with known agents to discover
    new peers in the network without a central registry.

    Features:
    - Peer failure tracking with exponential backoff
    - Peers with 3+ consecutive failures are skipped, with periodic retry
    """

    def __init__(
        self,
        registry: StaticRegistry,
        own_url: str,
        max_peers_per_exchange: int = 20,
        timeout: float = 5.0,
        skip_localhost_peers: bool = False,
    ):
        self.registry = registry
        self.own_url = own_url.rstrip("/")
        self.max_peers = max_peers_per_exchange
        self.timeout = timeout
        self.skip_localhost = skip_localhost_peers
        self.stats = GossipStats()
        # Track which peers we've seen (url → first_seen timestamp)
        self._seen: dict[str, str] = {}
        # Failure tracking for backoff (Phase 6.6)
        self._failures: dict[str, int] = {}  # url → consecutive failure count
        self._max_failures: int = 3           # Skip peers with this many failures

    def _record_failure(self, peer_url: str) -> None:
        """Record a failed exchange with a peer."""
        url = peer_url.rstrip("/")
        self._failures[url] = self._failures.get(url, 0) + 1
        log.debug("gossip_peer_failure", url=url[:60], count=self._failures[url])

    def _record_success(self, peer_url: str) -> None:
        """Reset failure count on successful exchange."""
        url = peer_url.rstrip("/")
        if url in self._failures:
            del self._failures[url]

    def _should_skip(self, peer_url: str) -> bool:
        """Check if a peer should be skipped due to repeated failures."""
        url = peer_url.rstrip("/")
        count = self._failures.get(url, 0)
        if count >= self._max_failures:
            # Allow retry every N rounds (exponential: 3, 6, 12, ...)
            skip_rounds = self._max_failures * (2 ** (count - self._max_failures))
            # Clamp to avoid huge skip windows
            skip_rounds = min(skip_rounds, 100)
            if self.stats.rounds % max(skip_rounds, 1) != 0:
                return True
        return False

    def get_peer_list(self) -> list[dict]:
        """Return the list of known peers for sharing.

        Returns a list of dicts with {url, name, status, last_seen}.
        Does NOT include self.
        """
        peers = []
        for rec in self.registry.get_all_records():
            if rec.url.rstrip("/") == self.own_url:
                continue
            peers.append({
                "url": rec.url,
                "name": rec.name,
                "status": rec.status,
                "last_seen": rec.last_seen,
            })
        return peers[:self.max_peers]

    def merge_peer_list(self, peers: list[dict], source_url: str) -> list[str]:
        """Merge received peer list into the local registry.

        Args:
            peers: List of peer dicts from another agent.
            source_url: URL of the agent that sent the list.

        Returns:
            List of newly discovered peer URLs.
        """
        new_peers = []
        now = datetime.now(timezone.utc).isoformat()

        for peer in peers:
            url = peer.get("url", "").rstrip("/")
            if not url:
                continue
            # Skip self
            if url == self.own_url:
                continue
            # Skip localhost peers when operating cross-network
            if self.skip_localhost and ("localhost" in url or "127.0.0.1" in url):
                log.debug("gossip_skip_localhost_peer", url=url)
                continue
            # Check if already known
            known_urls = {u.rstrip("/") for u in self.registry.get_all_urls()}
            if url in known_urls:
                continue

            # New peer discovered via gossip!
            self.registry.add(url, name=peer.get("name"))
            self._seen[url] = now
            new_peers.append(url)
            log.info(
                "gossip_new_peer",
                url=url,
                name=peer.get("name"),
                via=source_url,
            )

        if new_peers:
            self.stats.peers_learned += len(new_peers)
            self.registry.save()
            log.info("gossip_merged", new_count=len(new_peers), total=len(self.registry))

        return new_peers

    async def exchange_with_peer(self, peer_url: str) -> list[str]:
        """Exchange peer lists with a single peer.

        Sends our peer list and receives theirs.
        Tracks failures for backoff.

        Returns:
            List of newly discovered peer URLs.
        """
        if self._should_skip(peer_url):
            log.debug("gossip_peer_skipped_backoff", url=peer_url[:60],
                      failures=self._failures.get(peer_url.rstrip("/"), 0))
            return []

        url = peer_url.rstrip("/") + "/gossip/peers"
        our_peers = self.get_peer_list()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # POST our peer list and get theirs back
                resp = await client.post(
                    url,
                    json={
                        "source": self.own_url,
                        "peers": our_peers,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    their_peers = data.get("peers", [])
                    self.stats.peers_shared += len(our_peers)
                    self._record_success(peer_url)
                    return self.merge_peer_list(their_peers, peer_url)
                else:
                    self._record_failure(peer_url)
                    log.debug("gossip_peer_error", url=peer_url, status=resp.status_code)
        except httpx.ConnectError:
            self._record_failure(peer_url)
            log.debug("gossip_peer_unreachable", url=peer_url)
        except Exception as e:
            self._record_failure(peer_url)
            log.debug("gossip_exchange_error", url=peer_url, error=str(e))

        return []

    async def run_round(self) -> list[str]:
        """Run a single gossip round — exchange with all known peers.

        Returns:
            List of all newly discovered peer URLs.
        """
        all_urls = self.registry.get_all_urls()
        if not all_urls:
            return []

        # Exchange with each peer concurrently
        tasks = [
            self.exchange_with_peer(url)
            for url in all_urls
            if url.rstrip("/") != self.own_url
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        new_peers = []
        for result in results:
            if isinstance(result, list):
                new_peers.extend(result)
            elif isinstance(result, Exception):
                log.debug("gossip_round_error", error=str(result))

        self.stats.rounds += 1
        self.stats.last_round = datetime.now(timezone.utc).isoformat()

        if new_peers:
            log.info(
                "gossip_round_complete",
                round=self.stats.rounds,
                new_peers=len(new_peers),
                urls=new_peers,
            )
        else:
            log.debug("gossip_round_complete", round=self.stats.rounds, new_peers=0)

        return new_peers

    def get_stats(self) -> dict:
        """Return gossip statistics."""
        return {
            "rounds": self.stats.rounds,
            "peers_learned": self.stats.peers_learned,
            "peers_shared": self.stats.peers_shared,
            "last_round": self.stats.last_round,
            "known_peers": len(self.registry),
            "peers_in_backoff": sum(1 for c in self._failures.values() if c >= self._max_failures),
        }
